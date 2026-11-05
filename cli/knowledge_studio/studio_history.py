"""Explicit, timestamped document revisions and optional three-step onboarding."""

from __future__ import annotations
from datetime import datetime
import hashlib
import json
import re
import yaml
from uuid import uuid4
from . import store, tasks

STEPS = ("discuss", "goals", "learning")


def _read(root, relative):
    path = tasks._inside(root, relative)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Studio record exceeds limit")
    return json.loads(path.read_text(encoding="utf-8"))


def initialize(root):
    path = tasks._inside(root, "records/studio/onboarding.json")
    if not path.exists():
        store._atomic_write(
            path,
            json.dumps(
                {
                    "schema_version": "studio-onboarding/v1",
                    "status": "not_started",
                    "steps": {s: False for s in STEPS},
                }
            )
            + "\n",
        )
    return _read(root, "records/studio/onboarding.json")


def onboarding(root, payload=None):
    path = tasks._inside(root, "records/studio/onboarding.json")
    if payload is None:
        return (
            _read(root, "records/studio/onboarding.json")
            if path.is_file()
            else {
                "schema_version": "studio-onboarding/v1",
                "status": "not_started",
                "steps": {s: False for s in STEPS},
            }
        )
    with store._file_lock(tasks._inside(root, ".oks/locks/studio-onboarding.lock")):
        state = onboarding(root)
        action = payload.get("action")
        if action == "skip":
            state["status"] = "skipped"
        elif action == "reset":
            state.update(status="not_started", steps={s: False for s in STEPS})
        elif action == "complete_step":
            step = payload.get("step")
            if step not in STEPS:
                raise ValueError("Unknown onboarding step")
            state["steps"][step] = True
            state["status"] = (
                "completed" if all(state["steps"].values()) else "in_progress"
            )
        else:
            raise ValueError("Unknown onboarding action")
        state["updated_at"] = datetime.now().astimezone().isoformat()
        store._atomic_write(
            path, json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        )
        return state


def kind(path):
    return "discuss" if path.startswith(("discuss/", "profiles/discuss/")) else "goal"


def record(
    root, path, before, after, *, action="edit", actor="unspecified", status="complete"
):
    now = datetime.now().astimezone()
    identifier = uuid4().hex
    value = {
        "schema_version": "studio-revision/v1",
        "id": identifier,
        "at": now.isoformat(),
        "kind": kind(path),
        "action": action,
        "status": status,
        "path": path,
        "actor_reported": actor,
        "actor_verified": False,
        "before": before,
        "after": after,
        "before_sha256": (
            hashlib.sha256(before.encode()).hexdigest() if before is not None else None
        ),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
    }
    from .studio import outline

    def items(text):
        return {
            (r["kind"], r["level"], r["text"]): r["checked"]
            for r in outline(text or "")
            if r["kind"] in {"heading", "task"}
        }

    old, new = items(before), items(after)
    changes = [
        {"type": "completed" if new[k] else "reopened", "title": k[2]}
        for k in old.keys() & new.keys()
        if old[k] != new[k]
    ]
    changes += [{"type": "added", "title": k[2]} for k in new if k not in old]
    changes += [{"type": "removed", "title": k[2]} for k in old if k not in new]
    value["changes"] = changes
    value["content_changed"] = before != after
    target = tasks._inside(
        root,
        "records/timeline/" + now.strftime("%Y/%m/%d") + "/" + identifier + ".json",
    )
    store._atomic_write(target, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return value


def finish(root, event, status="complete"):
    event["status"] = status
    date = datetime.fromisoformat(event["at"]).strftime("%Y/%m/%d")
    target = tasks._inside(
        root, "records/timeline/" + date + "/" + event["id"] + ".json"
    )
    store._atomic_write(target, json.dumps(event, ensure_ascii=False, indent=2) + "\n")


def events(root, date, selected_kind=None, *, snapshots=False):
    datetime.strptime(date, "%Y-%m-%d")
    result = []
    base = tasks._inside(root, "records/timeline/" + date.replace("-", "/"))
    for path in base.glob("*.json"):
        row = _read(root, path.relative_to(root).as_posix())
        if selected_kind and row["kind"] != selected_kind:
            continue
        if not snapshots:
            row = {k: v for k, v in row.items() if k not in {"before", "after"}}
        result.append(row)
    return sorted(result, key=lambda e: (e["at"], e["id"]))


def snapshot(root, identifier):
    if not re.fullmatch("[a-f0-9]{32}", identifier or ""):
        raise ValueError("Invalid revision ID")
    for path in (root / "records/timeline").glob("*/*/*/" + identifier + ".json"):
        value = _read(root, path.relative_to(root).as_posix())
        if value.get("status", "complete") != "complete":
            raise ValueError("Revision was not committed")
        return value
    raise ValueError("Revision not found")


def checkpoint(root, path, text):
    target = tasks._inside(
        root,
        ".oks/studio-observed/" + hashlib.sha256(path.encode()).hexdigest() + ".json",
    )
    store._atomic_write(
        target,
        json.dumps(
            {
                "path": path,
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
            ensure_ascii=False,
        ),
    )


def observe(root, path, text):
    target = tasks._inside(
        root,
        ".oks/studio-observed/" + hashlib.sha256(path.encode()).hexdigest() + ".json",
    )
    with store._file_lock(
        tasks._inside(
            root,
            ".oks/locks/observe-" + hashlib.sha256(path.encode()).hexdigest() + ".lock",
        )
    ):
        old = json.loads(target.read_text()) if target.is_file() else None
        if old is None or old["sha256"] != hashlib.sha256(text.encode()).hexdigest():
            record(
                root,
                path,
                old["text"] if old else None,
                text,
                action="observed_change" if old else "baseline",
            )
            checkpoint(root, path, text)


class Watcher:
    """Observe edits from other Agents too. Times mean observed-at, not guessed occurrence."""

    def __init__(self, root):
        import threading

        self.root = root
        self.stop_event = threading.Event()
        self.thread = None

    def scan(self):
        from . import studio
        from itertools import islice

        warnings = []
        roots = ("profiles/goals", "profiles/discuss", "goal", "discuss")
        for bucket in roots:
            for path in islice((self.root / bucket).rglob("*.md"), studio.MAX_SCAN):
                relative = path.relative_to(self.root).as_posix()
                try:
                    lock = tasks._inside(
                        self.root,
                        ".oks/locks/goal-"
                        + hashlib.sha256(relative.encode()).hexdigest()
                        + ".lock",
                    )
                    with store._file_lock(lock):
                        file = studio.read_file(self.root, relative)
                        if len(file["text"].encode()) <= 60000:
                            observe(self.root, relative, file["text"])
                except (OSError, ValueError, UnicodeError, yaml.YAMLError):
                    warnings.append(relative)
        return warnings

    def start(self):
        import threading

        def loop():
            while not self.stop_event.is_set():
                self.scan()
                self.stop_event.wait(2)

        self.thread = threading.Thread(
            target=loop, daemon=True, name="oks-document-history"
        )
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(3)
