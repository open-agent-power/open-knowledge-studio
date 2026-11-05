"""Canonical instance layout; legacy paths are read aliases, never duplicate stores."""

from __future__ import annotations
from pathlib import Path
import hashlib
import json
import re
from datetime import datetime, UTC
from . import store, tasks

GOALS = "profiles/goals"
DISCUSS = "profiles/discuss"
SKILLS = "skills"
ALIASES = {"goal": GOALS, "discuss": DISCUSS, "skill": SKILLS}


def canonical(root, relative):
    tasks._inside(root, relative)  # Reject traversal/symlinks before alias resolution.
    mapping = tasks._inside(root, "records/layout/migration.json")
    if not (root / relative).exists() and mapping.is_file():
        destination = json.loads(mapping.read_text()).get("aliases", {}).get(relative)
        if destination:
            tasks._inside(root, destination)
            return destination
    head, sep, rest = relative.partition("/")
    if head in ALIASES and not (root / relative).exists():
        return ALIASES[head] + (sep + rest if sep else "")
    return relative


def migrate(root):
    """Move only legacy buckets, with a resumable audit and preflight conflicts."""
    target = tasks._inside(root, "records/layout/migration.json")
    with store._file_lock(tasks._inside(root, ".oks/locks/layout.lock")):
        moves = []
        today = datetime.now().astimezone().strftime("%Y/%m/%d")
        for old, new in [*ALIASES.items(), (GOALS, GOALS), (DISCUSS, DISCUSS)]:
            base = tasks._inside(root, old)
            paths = base.glob("*.md") if old in {GOALS, DISCUSS} else base.rglob("*")
            for path in sorted(paths) if base.is_dir() else []:
                if path.is_symlink():
                    raise ValueError("Migration refuses symbolic links: " + str(path))
                if not path.is_file():
                    continue
                src = path.relative_to(root).as_posix()
                suffix = path.relative_to(base).as_posix()
                if new in {GOALS, DISCUSS} and not re.match(
                    r"^\d{4}/\d{2}/\d{2}/", suffix
                ):
                    suffix = today + "/" + suffix
                dst = new + "/" + suffix
                dest = tasks._inside(root, dst)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if dest.exists() and (
                    not dest.is_file()
                    or hashlib.sha256(dest.read_bytes()).hexdigest() != digest
                ):
                    raise ValueError("Conflicting destination; no files moved: " + dst)
                moves.append(
                    {"from": src, "to": dst, "sha256": digest, "status": "pending"}
                )
        old_registry = tasks._inside(root, "profiles/agents/registry.jsonl")
        registry = tasks._inside(root, "records/registry/terminals.jsonl")
        if old_registry.is_file():
            digest = hashlib.sha256(old_registry.read_bytes()).hexdigest()
            if (
                registry.exists()
                and hashlib.sha256(registry.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Conflicting registry; no files moved")
            moves.append(
                {
                    "from": "profiles/agents/registry.jsonl",
                    "to": "records/registry/terminals.jsonl",
                    "sha256": digest,
                    "status": "pending",
                }
            )
        if not moves:
            return {"status": "unchanged", "moves": []}
        aliases = (
            json.loads(target.read_text()).get("aliases", {})
            if target.is_file()
            else {}
        )
        aliases.update({m["from"]: m["to"] for m in moves})
        audit = {
            "schema_version": "knowledge-layout/v1",
            "at": datetime.now(UTC).isoformat(),
            "status": "in_progress",
            "moves": moves,
            "aliases": aliases,
        }

        def persist():
            store._atomic_write(
                target, json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
            )

        if target.is_file():
            previous = tasks._inside(
                root,
                "records/layout/history/"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                + ".json",
            )
            store._atomic_write(previous, target.read_text())
        persist()
        for item in moves:
            src = tasks._inside(root, item["from"])
            dst = tasks._inside(root, item["to"])
            if hashlib.sha256(src.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Source changed during migration")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                src.unlink()
            else:
                src.replace(dst)
            item["status"] = "moved"
            persist()
        for old in ALIASES:
            base = root / old
            if base.is_dir():
                for p in sorted(
                    base.rglob("*"), key=lambda p: len(p.parts), reverse=True
                ):
                    if p.is_dir():
                        p.rmdir()
                base.rmdir()
        audit["status"] = "completed"
        persist()
        return audit


def registry_path(root):
    canonical = tasks._inside(root, "records/registry/terminals.jsonl")
    legacy = tasks._inside(root, "profiles/agents/registry.jsonl")
    return legacy if not canonical.exists() and legacy.exists() else canonical
