"""Explicit local feedback, scoped review and withdrawal-safe candidate reads.

Scope labels are routing constraints, NOT authentication. Private data is kept
outside the KB by default; only an explicit export creates a shared Draft.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re

import yaml

from . import handoff, store

SCHEMA = "feedback-store/v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 500
ACTIONS = {"observed", "adopted", "revised", "rejected"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _text(value, name, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty text, at most {maximum} characters")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value):
        raise ValueError("Invalid feedback/candidate ID")
    return value


def scope(value):
    if not isinstance(value, dict) or set(value) != {"subject", "project", "task"}:
        raise ValueError("Explicit subject, project and task are required")
    return {key: _text(value[key], key, 120) for key in ("subject", "project", "task")}


def _location(root: Path, key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("Invalid private scope reference")
    base = Path(os.environ.get("OKS_FEEDBACK_HOME", str(Path.home() / ".oks/private-feedback"))).expanduser()
    base = base.resolve()
    if base.is_relative_to(root.resolve()):
        raise ValueError("Private feedback storage must be outside the knowledge repository")
    target = base / digest(str(root.resolve())) / (key + ".json")
    if target.resolve() != target or target.parent.resolve() != target.parent:
        raise ValueError("Private feedback path must not traverse symlinks")
    return target


def _load(path):
    if not path.exists():
        return {"schema_version": SCHEMA, "events": {}, "candidates": {}, "forgotten": [], "exports": []}
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Private feedback store exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("Invalid feedback store; existing data preserved")
    if not isinstance(value.get("events"), dict) or not isinstance(value.get("candidates"), dict):
        raise ValueError("Invalid feedback collections")
    if not isinstance(value.get("forgotten"), list) or not isinstance(value.get("exports"), list):
        raise ValueError("Invalid feedback receipts")
    return value


def _save(path, state):
    text = json.dumps(state, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    if len(text.encode()) > MAX_BYTES or len(state["events"]) + len(state["candidates"]) > MAX_ITEMS:
        raise ValueError("Feedback capacity reached; export or forget explicitly")
    store._atomic_write(path, text)


@contextmanager
def _locked(root, selection):
    selection = scope(selection)
    path = _location(root, digest(selection))
    with store._file_lock(path.with_suffix(".lock")):
        state = _load(path)
        if state.get("scope", selection) != selection:
            raise ValueError("Private feedback scope mismatch")
        state["scope"] = selection
        yield path, state


def _asset(root, relative):
    raw = handoff._read(root, relative, "wiki")
    meta = handoff._meta(raw)
    if not handoff._reviewed(meta):
        raise ValueError("Feedback asset must be active and human reviewed")
    return {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
            "skill_version": meta.get("skill_version")}


def record(root: Path, request: dict) -> dict:
    """Record a caller-reported explicit signal; never infer from silence."""
    selection = scope(request.get("scope"))
    event_id = _id(request.get("event_id"))
    action = request.get("action")
    if action not in ACTIONS:
        raise ValueError("Choose observed, adopted, revised or rejected")
    source = request.get("source", "user_reported")
    if source not in {"user_reported", "agent_proposed"}:
        raise ValueError("Source must be user_reported or agent_proposed")
    agreement = handoff.validate(request.get("agreement"))
    if handoff.check(root, agreement, selection["task"])["status"] != "current":
        raise ValueError("Agreement needs review")
    asset = _asset(root, request.get("asset_path"))
    payload = {"event_id": event_id, "action": action, "reason": _text(request.get("reason"), "reason"),
               "source": source, "agreement": agreement, "asset": asset,
               "replaces": request.get("replaces"), "run_id": request.get("run_id")}
    signature = digest(payload)
    with _locked(root, selection) as (path, state):
        previous = state["events"].get(event_id)
        if previous:
            if previous["digest"] != signature:
                raise ValueError("Event ID already has different content")
            return {"event_id": event_id, "duplicate": True, "status": previous["status"], "trace_status": previous.get("trace_status", "unknown")}
        if digest(event_id) in state["forgotten"]:
            raise ValueError("Event was forgotten; use a new explicit event ID")
        if payload["replaces"]:
            old = state["events"].get(_id(payload["replaces"]))
            if old is None or old["status"] != "active":
                raise ValueError("Replacement requires an active event in this exact scope")
            if old["payload"]["asset"]["path"] != asset["path"]:
                raise ValueError("Replacement must refer to the same asset")
            old["status"] = "corrected"
        state["events"][event_id] = {"payload": payload, "digest": signature, "status": "active",
                                      "at": datetime.now(UTC).isoformat(), "identity_verified": False,
                                      "trace_status": "pending" if payload["run_id"] else "not_requested"}
        _save(path, state)
    result = {"event_id": event_id, "duplicate": False, "status": "active", "identity_verified": False}
    # Optional shared Trace contains only an opaque reference, never private text.
    if payload["run_id"]:
        from .trace import append_event, load_manifest
        try:
            manifest = load_manifest(payload["run_id"])
            if manifest["goal_id"] != Path(agreement["goal"]["path"]).stem:
                raise ValueError("Trace Goal differs from agreement")
            append_event(payload["run_id"], "tool_observation", "tool",
                         {"schema_version": "feedback-reference/v1", "reference": digest([selection, event_id]), "status": "recorded"})
            result["trace_status"] = "recorded"
        except (OSError, ValueError) as exc:
            result.update(trace_status="partial", trace_error=type(exc).__name__)
        with _locked(root, selection) as (path, state):
            if event_id in state["events"]:
                state["events"][event_id]["trace_status"] = result["trace_status"]
                _save(path, state)
    return result


def _issues(root, state, candidate):
    issues = []
    for identifier in candidate["event_ids"]:
        event = state["events"].get(identifier)
        if not event or event["status"] != "active":
            issues.append({"event_id": identifier, "code": "feedback_inactive"})
            continue
        payload = event["payload"]
        try:
            if handoff.check(root, payload["agreement"], state["scope"]["task"])["status"] != "current":
                issues.append({"event_id": identifier, "code": "agreement_stale"})
            if _asset(root, payload["asset"]["path"]) != payload["asset"]:
                issues.append({"event_id": identifier, "code": "asset_changed"})
        except (OSError, ValueError, UnicodeError):
            issues.append({"event_id": identifier, "code": "source_unavailable"})
    return issues


def _view(root, state, candidate):
    issues = _issues(root, state, candidate)
    return {**candidate, "effective_status": "invalidated" if issues else candidate["status"],
            "issues": issues, "revision": digest(candidate), "executed": False}


def propose(root, request):
    identifier = _id(request.get("candidate_id"))
    ids = request.get("event_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 16 or len(set(ids)) != len(ids):
        raise ValueError("Choose 1-16 distinct feedback events")
    for value in ids:
        _id(value)
    with _locked(root, request.get("scope")) as (path, state):
        events = [state["events"].get(value) for value in ids]
        if any(not e or e["status"] != "active" for e in events):
            raise ValueError("Candidate sources must be active feedback in this scope")
        if all(e["payload"]["action"] == "observed" for e in events):
            raise ValueError("Exposure alone cannot establish a learning decision")
        candidate = {"candidate_id": identifier, "event_ids": ids,
                     "title": _text(request.get("title"), "title", 200),
                     "summary": _text(request.get("summary"), "summary"), "status": "pending",
                     "at": datetime.now(UTC).isoformat()}
        if identifier in state["candidates"]:
            raise ValueError("Candidate ID already exists")
        if _issues(root, state, candidate):
            raise ValueError("Candidate source versions need review")
        state["candidates"][identifier] = candidate
        _save(path, state)
        return _view(root, state, candidate)


def review(root, request):
    decision = request.get("decision")
    if decision not in {"approve", "reject"}:
        raise ValueError("Choose approve or reject")
    with _locked(root, request.get("scope")) as (path, state):
        candidate = state["candidates"][_id(request.get("candidate_id"))]
        if candidate["status"] != "pending" or request.get("expected_revision") != digest(candidate):
            raise ValueError("Candidate changed or already reviewed; inspect it again")
        if _issues(root, state, candidate):
            raise ValueError("Source inactive or stale; cannot review this candidate")
        candidate.update(status="approved" if decision == "approve" else "rejected",
                         review_comment=_text(request.get("comment"), "comment"), reviewed_at=datetime.now(UTC).isoformat())
        _save(path, state)
        return _view(root, state, candidate)


def withdraw(root, request):
    with _locked(root, request.get("scope")) as (path, state):
        event = state["events"][_id(request.get("event_id"))]
        event["status"] = "withdrawn"
        _save(path, state)
        affected = [c["candidate_id"] for c in state["candidates"].values() if request["event_id"] in c["event_ids"]]
        return {"status": "withdrawn", "invalidated_candidates": affected, "formal_wiki_changed": False,
                "exports_require_review": state["exports"]}


def inspect(root, selection=None):
    if selection is None:
        return {"status": "scope_required", "events": [], "candidates": []}
    with _locked(root, selection) as (_, state):
        events = [{"event_id": k, **v} for k, v in state["events"].items()]
        candidates = [_view(root, state, c) for c in state["candidates"].values()]
        # Keep opposite decisions visible, without inferring that later is truer.
        groups = {}
        for event in events:
            if event["status"] == "active" and event["payload"]["action"] != "observed":
                groups.setdefault(event["payload"]["asset"]["path"], set()).add(event["payload"]["action"])
        return {"status": "ok", "scope": scope(selection), "events": events, "candidates": candidates,
                "conflicts": [key for key, actions in groups.items() if len(actions) > 1],
                "exports": state["exports"], "identity_verified": False}


def select_context(root, selection, agreement):
    """One selection path for manual recall and Hook; details stay private."""
    if selection is None or agreement is None:
        return {"status": "not_requested", "candidates": [], "excluded_counts": {}}
    selection = scope(selection)
    if handoff.check(root, agreement, selection["task"])["status"] != "current":
        raise ValueError("Current task agreement needs review")
    view = inspect(root, selection)
    events = {e["event_id"]: e for e in view["events"]}
    selected, excluded = [], {}
    for candidate in view["candidates"]:
        reason = None
        if candidate["effective_status"] != "approved":
            reason = candidate["effective_status"]
        elif not all(events[e]["payload"]["agreement"]["sha256"] == agreement["sha256"] for e in candidate["event_ids"]):
            reason = "different_agreement"
        elif any(events[e]["payload"]["asset"]["path"] in view["conflicts"] for e in candidate["event_ids"]):
            reason = "conflicting_feedback"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
        else:
            selected.append({key: candidate[key] for key in ("candidate_id", "title", "summary", "revision")})
    return {"status": "selected" if selected else "empty", "candidates": selected, "excluded_counts": excluded}


def context(root, selection, agreement):
    return select_context(root, selection, agreement)["candidates"]


def export(root, request, *, confirm_share=False):
    if not confirm_share:
        raise ValueError("Export creates a shared Draft; --confirm-share is required")
    with _locked(root, request.get("scope")) as (path, state):
        candidate = state["candidates"][_id(request.get("candidate_id"))]
        if candidate["status"] != "approved" or _issues(root, state, candidate):
            raise ValueError("Only current approved candidates can be exported")
        if request.get("expected_revision") != digest(candidate):
            raise ValueError("Candidate changed; inspect before export")
        reference = {"scope_key": digest(state["scope"]), "candidate_id": candidate["candidate_id"], "revision": digest(candidate)}
        relative = f"drafts/feedback-{digest(reference)[:24]}.md"
        target = root / relative
        if not target.resolve().is_relative_to(root.resolve() / "drafts"):
            raise ValueError("Draft destination escapes knowledge root")
        metadata = {"title": candidate["title"], "draft_type": "strategy", "draft_area": "computing",
                    "status": "draft", "feedback_origin": reference, "human_approved": False}
        text = "---\n" + yaml.safe_dump(metadata, allow_unicode=True) + "---\n\n" + candidate["summary"] + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise ValueError("Exported Draft was edited; preserve it")
        if relative not in state["exports"]:
            state["exports"].append(relative)
        # Persist the export receipt before creating a shared copy. A failed
        # receipt write must never leave an untracked private-text export.
        _save(path, state)
        if not target.exists():
            store._atomic_write(target, text)
        return {"status": "draft_exported", "path": relative, "promoted": False}


@contextmanager
def export_guard(root, draft_path):
    """Hold the feedback lock through promotion, serializing withdrawal/export."""
    meta = store.parse_wiki_file(draft_path) or {}
    reference = meta.get("feedback_origin")
    if reference is None:
        if re.fullmatch(r"feedback-[0-9a-f]{24}", draft_path.stem):
            raise ValueError("Managed feedback Draft is missing its provenance")
        yield
        return
    if not isinstance(reference, dict):
        raise ValueError("Invalid feedback provenance")
    if set(reference) != {"scope_key", "candidate_id", "revision"} or draft_path.stem != "feedback-" + digest(reference)[:24]:
        raise ValueError("Feedback Draft provenance does not match its managed identity")
    path = _location(root, reference.get("scope_key", ""))
    with store._file_lock(path.with_suffix(".lock")):
        state = _load(path)
        candidate = state["candidates"].get(reference.get("candidate_id"))
        if not candidate or candidate["status"] != "approved" or digest(candidate) != reference.get("revision"):
            raise ValueError("Private feedback approval is absent or withdrawn")
        if _issues(root, state, candidate):
            raise ValueError("Feedback source inactive or stale")
        yield


def forget(root, selection):
    with _locked(root, selection) as (path, state):
        forgotten = sorted(set(state["forgotten"]) | {digest(key) for key in state["events"]})
        exports = state["exports"]
        _save(path, {"schema_version": SCHEMA, "scope": state["scope"], "events": {}, "candidates": {},
                     "forgotten": forgotten, "exports": exports})
        return {"status": "partial" if exports else "deleted_local", "private_content_removed": True,
                "consumer_disabled": True, "retained_event_tombstones": len(forgotten),
                "external_copies": exports, "backup_removal_verified": False, "formal_wiki_changed": False}
