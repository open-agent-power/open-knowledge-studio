"""Append-only execution traces for agent, judge, tool, and human events."""
from __future__ import annotations

import contextlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowledge_studio.store import _atomic_write, _file_lock, raw_dir, repo_root

TRACE_SCHEMA = "trace-event/v1"
MANIFEST_SCHEMA = "run-manifest/v1"
EVENT_TYPES = {
    "goal", "retrieval", "ai_action", "tool_observation", "ai_comment",
    "judge_comment", "human_action", "human_comment", "checkpoint",
    "blocker", "proposal", "final_result",
}
ACTORS = {"agent", "judge", "human", "tool", "system"}
# An agent must not unblock itself by appending another comment.
UNBLOCKING_EVENT_TYPES = {"human_action", "human_comment", "checkpoint"}
SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "cookie", "password",
    "secret", "token", "access_token", "refresh_token",
}
# Best-effort value scan: catches well-known credential shapes only.
SENSITIVE_VALUE_PATTERNS = (
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}", re.IGNORECASE)),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
)
_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_dir(run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id may contain only letters, digits, dot, underscore, and hyphen")
    return raw_dir() / "executions" / run_id


def _paths(run_id: str) -> tuple[Path, Path]:
    directory = _run_dir(run_id)
    return directory / "events.jsonl", directory / "run.json"


def _check_sensitive(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            credential_like = (
                normalized in SENSITIVE_KEYS
                or normalized.endswith("_token")
                or normalized.endswith("_secret")
                or normalized.endswith("_password")
                or normalized.endswith("_cookie")
                or normalized.endswith("_api_key")
            )
            if credential_like:
                raise ValueError(f"Sensitive field is not allowed in trace: {path}.{key}")
            _check_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_sensitive(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for label, pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"Credential-like value ({label}) is not allowed in trace: {path}")


@contextlib.contextmanager
def _append_lock(run_id: str):
    """Serialize the read-sequence-then-append critical section across processes."""
    with _file_lock(_run_dir(run_id) / ".append.lock"):
        yield


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at events.jsonl line {number}: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Trace event at line {number} must be an object")
        events.append(event)
    return events


def start_trace(goal_id: str, run_id: str | None = None, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    events_path, manifest_path = _paths(run_id)
    if events_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Trace already exists: {run_id}")
    events_path.parent.mkdir(parents=True, exist_ok=False)
    created = _now()
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "run_id": run_id,
        "goal_id": goal_id, "status": "running", "created_at": created,
        "updated_at": created, "event_count": 0,
        "trace_path": str(events_path.relative_to(repo_root()).as_posix()),
        "result": None,
    }
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    event = append_event(run_id, "goal", "system", {"goal_id": goal_id, **(payload or {})})
    return {"manifest": load_manifest(run_id), "event": event}


def load_manifest(run_id: str) -> dict[str, Any]:
    _, path = _paths(run_id)
    if not path.exists():
        raise FileNotFoundError(f"Trace not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def append_event(
    run_id: str, event_type: str, actor: str, payload: dict[str, Any],
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")
    if actor not in ACTORS:
        raise ValueError(f"Unsupported actor: {actor}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _check_sensitive(payload)
    refs = evidence_refs or []
    if not all(isinstance(ref, str) for ref in refs):
        raise ValueError("evidence_refs must contain strings")
    _check_sensitive(refs, "evidence_refs")

    events_path, manifest_path = _paths(run_id)
    with _append_lock(run_id):
        manifest = load_manifest(run_id)
        if manifest["status"] == "completed":
            raise ValueError(f"Trace is already completed: {run_id}")
        events = _read_events(events_path)
        sequence = len(events) + 1
        event = {
            "schema_version": TRACE_SCHEMA,
            "event_id": f"{run_id}:{sequence}", "run_id": run_id,
            "sequence": sequence, "timestamp": _now(),
            "event_type": event_type, "actor": actor,
            "payload": payload, "evidence_refs": refs,
        }
        with events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        manifest["event_count"] = sequence
        manifest["updated_at"] = event["timestamp"]
        if event_type == "blocker":
            manifest["status"] = "blocked"
        elif manifest["status"] == "blocked" and event_type in UNBLOCKING_EVENT_TYPES:
            manifest["status"] = "running"
        _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return event


def finish_trace(run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    outcome = result.get("outcome")
    if outcome not in {"success", "partial", "failure", "invalid"}:
        raise ValueError("result.outcome must be one of: success, partial, failure, invalid")
    event = append_event(run_id, "final_result", "agent", result)
    _, manifest_path = _paths(run_id)
    with _append_lock(run_id):
        manifest = load_manifest(run_id)
        manifest["status"] = "completed"
        manifest["result"] = result
        manifest["updated_at"] = event["timestamp"]
        _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def validate_trace(run_id: str, *, require_completed: bool = False) -> dict[str, Any]:
    events_path, _ = _paths(run_id)
    manifest = load_manifest(run_id)
    events = _read_events(events_path)
    errors: list[str] = []
    ids: set[str] = set()
    for expected, event in enumerate(events, start=1):
        if event.get("schema_version") != TRACE_SCHEMA:
            errors.append(f"event {expected}: invalid schema_version")
        if event.get("run_id") != run_id:
            errors.append(f"event {expected}: run_id mismatch")
        if event.get("sequence") != expected:
            errors.append(f"event {expected}: sequence mismatch")
        if event.get("event_id") in ids:
            errors.append(f"event {expected}: duplicate event_id")
        ids.add(str(event.get("event_id")))
        if event.get("event_type") not in EVENT_TYPES:
            errors.append(f"event {expected}: unsupported event_type")
        if event.get("actor") not in ACTORS:
            errors.append(f"event {expected}: unsupported actor")
        try:
            _check_sensitive(event.get("payload", {}))
        except ValueError as exc:
            errors.append(f"event {expected}: {exc}")
    if not events or events[0].get("event_type") != "goal":
        errors.append("first event must be goal")
    if manifest.get("event_count") != len(events):
        errors.append("manifest event_count mismatch")
    finals = [event for event in events if event.get("event_type") == "final_result"]
    if len(finals) > 1:
        errors.append("trace has more than one final_result")
    if manifest.get("status") == "completed" and len(finals) != 1:
        errors.append("completed trace must have one final_result")
    if require_completed and manifest.get("status") != "completed":
        errors.append("trace is not completed")
    return {"run_id": run_id, "valid": not errors, "errors": errors, "event_count": len(events), "status": manifest.get("status")}


def show_trace(run_id: str) -> dict[str, Any]:
    events_path, _ = _paths(run_id)
    return {"manifest": load_manifest(run_id), "events": _read_events(events_path)}
