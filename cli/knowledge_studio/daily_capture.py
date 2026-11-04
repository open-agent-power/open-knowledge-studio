"""Mechanical, source-linked capture of individual daily discussion/read events.

This module stores bounded excerpts in Raw Bundle v0.2 and indexes them for
later reading/distillation. It never calls an AI or writes Wiki knowledge.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from . import raw_commit, store, tasks
from .security.redaction import redact_text

MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 2 * MAX_EVENT_BYTES + MAX_INDEX_BYTES
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SOURCE_KEYS = {"id", "host", "workspace", "label", "path"}
_EVENT_KEYS = {"id", "kind", "role", "text", "timestamp", "session_id", "phase", "source_path", "locator", "final"}
_UPDATABLE = {"learning_status", "draft_path", "learning_error", "learning_attempts",
              "learning_updated_at", "learning_source_ids", "error"}
_LEARNING = {"pending", "processing", "drafted", "skipped", "failed"}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _read_json(path: Path, maximum: int = MAX_INDEX_BYTES) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Daily capture record exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid daily capture record")
    return value


def _capture_id(source_id: str, event_id: str) -> str:
    digest = hashlib.sha256((source_id + "\0" + event_id).encode("utf-8")).hexdigest()
    return "capture-" + digest[:32]


def _display_title(event: dict[str, Any], text: str) -> str:
    """Derive a compact title without exposing the complete source path."""
    source_path = event.get("source_path")
    if event.get("kind") == "reading" and isinstance(source_path, str) and source_path.strip():
        name = Path(source_path.split("?", 1)[0].split("#", 1)[0]).name.strip()
        if name:
            return name[:90]
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        if line:
            return line if len(line) <= 90 else line[:89].rstrip() + "…"
    return "Reading excerpt" if event.get("kind") == "reading" else "Discussion excerpt"


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("Event timestamp must be ISO-8601") from None


def _safe_text(value: Any) -> tuple[str, bool]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Event text must be a non-empty string")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError("Event text exceeds size limit")
    redacted = redact_text(value)
    return redacted, redacted != value


def _entry_path(root: Path, capture_id: str) -> Path:
    return tasks._inside(root, f".oks/daily-capture/entries/{capture_id}.json")


def _lock_path(root: Path) -> Path:
    return tasks._inside(root, ".oks/daily-capture/.lock")


def _raw_path(root: Path, relative: str) -> Path:
    return tasks._inside(root, relative)


def _validate_source(source_id: str, source: dict[str, Any]) -> None:
    if not isinstance(source_id, str) or not _ID_RE.fullmatch(source_id):
        raise ValueError("Invalid source_id")
    if not isinstance(source, dict) or set(source) - _SOURCE_KEYS:
        raise ValueError("Invalid source metadata")
    if source.get("id") != source_id:
        raise ValueError("Source id mismatch")
    for key in ("host", "workspace", "label"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f"Source {key} must be a non-empty string")
    if "path" in source and source["path"] is not None and not isinstance(source["path"], str):
        raise ValueError("Source path must be a string")


def _validate_event(event: dict[str, Any]) -> tuple[dict[str, Any], str, bool, datetime]:
    if not isinstance(event, dict) or set(event) - _EVENT_KEYS:
        raise ValueError("Invalid event shape")
    if not isinstance(event.get("id"), str) or not _ID_RE.fullmatch(event["id"]):
        raise ValueError("Invalid event id")
    if event.get("kind") not in {"discussion", "reading"}:
        raise ValueError("Invalid event kind")
    if event.get("role") not in {"user", "assistant", "source"}:
        raise ValueError("Unsupported event role")
    if event["role"] == "assistant" and event.get("phase") not in {"commentary", "final"}:
        raise ValueError("Assistant events must be commentary or final")
    if event["role"] == "source" and event["kind"] != "reading":
        raise ValueError("Source events must be reading events")
    for key in ("timestamp", "session_id"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise ValueError(f"Event {key} is required")
    if event.get("source_path") is not None and not isinstance(event["source_path"], str):
        raise ValueError("source_path must be a string")
    if event.get("locator") is not None and not isinstance(event["locator"], (str, dict)):
        raise ValueError("locator must be a string or object")
    if event.get("final") is not None and type(event["final"]) is not bool:
        raise ValueError("final must be boolean")
    clean, was_redacted = _safe_text(event.get("text"))
    safe_event = dict(event)
    safe_event["text"] = clean
    if safe_event.get("source_path"):
        safe_path = redact_text(safe_event["source_path"])
        was_redacted = was_redacted or safe_path != safe_event["source_path"]
        safe_event["source_path"] = safe_path
    return safe_event, clean, was_redacted, _timestamp(event["timestamp"])


def _make_manifest(capture_id: str, source_id: str, event: dict[str, Any], clean: str,
                   was_redacted: bool, source: dict[str, Any], captured_at: str,
                   event_sha256: str, manifest_dir: Path) -> tuple[str, str]:
    artifact = "excerpt.txt"
    artifact_bytes = clean.encode("utf-8")
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    (manifest_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (manifest_dir / "fragments").mkdir(parents=True, exist_ok=True)
    (manifest_dir / "work").mkdir(parents=True, exist_ok=True)
    (manifest_dir / "artifacts" / artifact).write_bytes(artifact_bytes)
    # agent-runtime denotes mechanical capture: no provider output is claimed.
    artifact_id = "artifact-" + capture_id[-16:]
    fragment_id = "fragment-" + capture_id[-16:]
    evidence_id = "evidence-" + capture_id[-16:]
    position = {"kind": "custom", "custom_label": "excerpt byte range [0,%d) in %s" % (len(artifact_bytes), artifact)}
    evidence = {"evidence_id": evidence_id, "artifact_id": artifact_id, "kind": "text_content",
                "method": "daily-capture", "locator": position, "text": clean,
                "confidence": 1.0, "agent_judgment": "mechanical"}
    modality = {"text": {"modality": "text", "status": "succeeded", "evidence_count": 1, "error_code": None}}
    fragment = {"schema_version": "oks-evidence-fragment/v0.1", "fragment_id": fragment_id,
                "source_id": source_id, "producer": {"runtime": "oks", "provider": "agent-runtime", "tool": "daily-capture"},
                "status": "succeeded", "artifacts": [{"artifact_id": artifact_id, "kind": "primary_text",
                "path": artifact, "sha256": digest}], "evidence": [evidence], "modalities": modality,
                "agent_notes": "Mechanical excerpt; not a full transcript or full source."}
    (manifest_dir / "fragments" / f"{fragment_id}.json").write_bytes(_json_bytes(fragment))
    manifest_id = "manifest-" + capture_id[-16:]
    manifest = {"schema_version": "oks-evidence-manifest/v0.1", "manifest_id": manifest_id,
                "source_id": source_id, "status": "complete", "fragment_refs": [fragment_id],
                "primary_artifact": {"artifact_id": artifact_id, "kind": "primary_text", "path": artifact,
                                     "media_type": "text/plain", "sha256": digest, "locator_kind": "custom"},
                "evidence_records": [evidence], "modalities": modality,
                "provenance": {"agent": {"runtime": source["host"], "model": None, "skill": "daily-capture"}, "latency_ms": None},
                "steps": [{"capability": "source.capture", "provider": "agent-runtime", "status": "succeeded", "reason": None}],
                "notes": {"excerpt": True, "redacted": was_redacted, "role": event["role"],
                          "phase": event.get("phase"), "session_id": event["session_id"],
                          "event_id": event["id"], "source_at": event["timestamp"],
                          "event_sha256": event_sha256,
                          "byte_range": [0, len(artifact_bytes)], "source_path": event.get("source_path"),
                          "locator": event.get("locator"), "final": event.get("final")}}
    envelope = {"schema_version": "oks-source-envelope/v0.1", "source_id": source_id,
                "source_uri": event.get("source_path") or f"daily://{source_id}/{event['id']}",
                "source_modality": "text", "access_mode": "manual", "captured_at": captured_at,
                "captured_by": {"runtime": source["host"], "model": None, "skill": "daily-capture"},
                "content_hash": digest, "evidence_manifest_ref": manifest_id,
                "title": f"{event['kind'].title()} excerpt ({event['role']})", "user_note": "Mechanical excerpt; not the full source.",
                "policy": {"remote_processing": "allow", "sensitivity": "internal"}}
    (manifest_dir / "source-envelope.json").write_bytes(_json_bytes(envelope))
    (manifest_dir / "evidence-manifest.json").write_bytes(_json_bytes(manifest))
    return digest, clean


def _existing_record(root: Path, capture_id: str, expected_sha: str) -> dict[str, Any] | None:
    path = _entry_path(root, capture_id)
    if not path.exists():
        return None
    record = _read_json(path)
    if record.get("event_sha256") != expected_sha:
        raise ValueError("Capture ID already exists with different content")
    return record


def append_events(root: Path, source_id: str, events: list[dict], *, source: dict) -> list[dict]:
    """Persist each allowed event once and return its index record (no full text)."""
    root = Path(root)
    _validate_source(source_id, source)
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    lock = _lock_path(root)
    results: list[dict[str, Any]] = []
    with store._file_lock(lock):
        for raw_event in events:
            event, clean, was_redacted, happened = _validate_event(raw_event)
            capture_id = _capture_id(source_id, event["id"])
            text_hash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
            # Fingerprint the submitted event bytes without retaining them. This
            # keeps redacted-secret changes from looking like an identical retry.
            event_sha = hashlib.sha256(_json_bytes({"source": source, "event": raw_event})).hexdigest()
            existing = _existing_record(root, capture_id, event_sha)
            if existing is not None:
                results.append({k: v for k, v in existing.items() if k != "excerpt_sha256"})
                continue
            captured_at = datetime.now(timezone.utc).isoformat()
            staging_relative = f".oks/daily-capture/staging/{capture_id}"
            staging = _raw_path(root, staging_relative)
            staging.parent.mkdir(parents=True, exist_ok=True)
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir()
            try:
                digest, clean = _make_manifest(capture_id, source_id, event, clean,
                                               was_redacted, source, captured_at, event_sha, staging)
                day = happened.strftime("%Y/%m/%d")
                raw_relative = f"raw/{day}/daily/{capture_id}"
                raw_target = _raw_path(root, raw_relative)
                # Crash after raw commit but before indexing is recovered only
                # when the committed artifact exactly matches this event.
                if raw_target.exists():
                    bundle = _read_json(_raw_path(root, raw_relative + "/bundle.json"))
                    manifest = _read_json(_raw_path(root, raw_relative + "/evidence-manifest.json"), MAX_MANIFEST_BYTES)
                    if (bundle.get("capture_id") != source_id or bundle.get("content_hash") != digest
                            or manifest.get("notes", {}).get("event_sha256") != event_sha):
                        raise ValueError("Existing Raw bundle does not match this event")
                else:
                    raw_commit.raw_commit(staging, output=raw_target)
                content_path = raw_relative + "/source/excerpt.txt"
                content_file = _raw_path(root, content_path)
                if not content_file.is_file() or content_file.stat().st_size > MAX_EVENT_BYTES:
                    raise ValueError("Committed excerpt is missing or too large")
                persisted = content_file.read_bytes()
                if hashlib.sha256(persisted).hexdigest() != digest:
                    raise ValueError("Committed excerpt integrity check failed")
                preview = clean[:240]
                record = {"id": capture_id, "source_id": source_id, "host": source["host"],
                          "workspace": source["workspace"], "session_id": event["session_id"],
                          "kind": event["kind"], "role": event["role"], "phase": event.get("phase"),
                          "title": _display_title(event, clean), "preview": preview,
                          "captured_at": captured_at, "source_at": event["timestamp"],
                          "raw_path": raw_relative, "raw_sha256": hashlib.sha256(_raw_path(root, raw_relative + "/bundle.json").read_bytes()).hexdigest(),
                          "content_path": content_path, "learning_status": "pending", "excerpt_sha256": digest,
                          "event_sha256": event_sha,
                          "redacted": was_redacted, "excerpt": True,
                          "byte_range": [0, len(persisted)],
                          "locator": event.get("locator"), "final": event.get("final")}
                store._atomic_write(_entry_path(root, capture_id), _json_bytes(record))
                results.append({k: v for k, v in record.items() if k != "excerpt_sha256"})
            finally:
                shutil.rmtree(staging, ignore_errors=True)
    return results


def list_entries(root: Path, limit: int = 50) -> list[dict]:
    if type(limit) is not int or not 0 <= limit <= 5000:
        raise ValueError("limit must be between 0 and 5000")
    root = Path(root)
    directory = _raw_path(root, ".oks/daily-capture/entries")
    if not directory.exists() or limit == 0:
        return []
    results = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.name, reverse=True):
        checked = _raw_path(root, f".oks/daily-capture/entries/{path.name}")
        record = _read_json(checked)
        results.append({k: v for k, v in record.items() if k not in {"excerpt_sha256", "text"}})
        if len(results) >= limit:
            break
    return sorted(results, key=lambda item: item.get('captured_at', ''), reverse=True)


def entry(root: Path, entry_id: str) -> dict:
    if not isinstance(entry_id, str) or not re.fullmatch(r"capture-[a-f0-9]{32}", entry_id):
        raise ValueError("Invalid capture id")
    root = Path(root)
    with store._file_lock(_lock_path(root)):
        record = _read_json(_entry_path(root, entry_id))
        raw_bundle = _raw_path(root, f"{record['raw_path']}/bundle.json")
        with raw_bundle.open("rb") as stream:
            bundle_bytes = stream.read(MAX_INDEX_BYTES + 1)
        if len(bundle_bytes) > MAX_INDEX_BYTES:
            raise ValueError("Raw bundle manifest exceeds size limit")
        if hashlib.sha256(bundle_bytes).hexdigest() != record.get("raw_sha256"):
            raise ValueError("Raw bundle integrity check failed")
        content = _raw_path(root, record["content_path"])
        with content.open("rb") as stream:
            raw = stream.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise ValueError("Captured excerpt exceeds size limit")
        if hashlib.sha256(raw).hexdigest() != record.get("excerpt_sha256"):
            raise ValueError("Captured excerpt integrity check failed")
        record["text"] = raw.decode("utf-8")
        return record


def update_entry(root: Path, id: str, updates: dict) -> dict:
    if not isinstance(updates, dict) or not updates or set(updates) - _UPDATABLE:
        raise ValueError("Only learning_status and error may be updated")
    if "learning_status" in updates and updates["learning_status"] not in _LEARNING:
        raise ValueError("Invalid learning_status")
    if "error" in updates and (updates["error"] is not None and not isinstance(updates["error"], str)):
        raise ValueError("error must be a string or null")
    if "learning_error" in updates and (updates["learning_error"] is not None and not isinstance(updates["learning_error"], str)):
        raise ValueError("learning_error must be a string or null")
    if "draft_path" in updates and (updates["draft_path"] is not None and not isinstance(updates["draft_path"], str)):
        raise ValueError("draft_path must be a string or null")
    if "learning_attempts" in updates and (type(updates["learning_attempts"]) is not int or updates["learning_attempts"] < 0):
        raise ValueError("learning_attempts must be a non-negative integer")
    if "learning_updated_at" in updates and (updates["learning_updated_at"] is not None and not isinstance(updates["learning_updated_at"], str)):
        raise ValueError("learning_updated_at must be a string or null")
    if "learning_source_ids" in updates and (not isinstance(updates["learning_source_ids"], list)
            or not all(isinstance(item, str) for item in updates["learning_source_ids"])):
        raise ValueError("learning_source_ids must be a list of strings")
    root = Path(root)
    if not isinstance(id, str) or not re.fullmatch(r"capture-[a-f0-9]{32}", id):
        raise ValueError("Invalid capture id")
    with store._file_lock(_lock_path(root)):
        path = _entry_path(root, id)
        record = _read_json(path)
        record.update(updates)
        store._atomic_write(path, _json_bytes(record))
        return {k: v for k, v in record.items() if k != "excerpt_sha256"}
