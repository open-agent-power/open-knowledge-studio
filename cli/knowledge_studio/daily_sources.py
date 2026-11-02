"""Scoped adapters for explicitly connected local conversation sources."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from . import daily_capture, store, tasks

CONFIG = "settings/daily-capture.json"
SCHEMA = "daily-capture/v1"
MAX_BATCH = 256
MAX_LINE = 4 * 1024 * 1024


def _inside(root: Path, rel: str) -> Path:
    return tasks._inside(Path(root), rel)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_config(root: Path) -> dict:
    path = _inside(root, CONFIG)
    if not path.exists():
        return {"schema": SCHEMA, "enabled": True, "sources": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("sources"), list):
        raise ValueError("Invalid daily capture config")
    return data


def _write_config(root: Path, config: dict) -> None:
    store._atomic_write(_inside(root, CONFIG), (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode())


def load_config(root) -> dict:
    return _read_config(Path(root))


def _source(source_id: str, config: dict) -> dict:
    for src in config["sources"]:
        if src.get("id") == source_id:
            return src
    raise ValueError("Unknown daily capture source")


def _source_status(root: Path, source_id: str, *, status: str, error=None, captured_at=None) -> None:
    config = _read_config(root)
    for src in config["sources"]:
        if src.get("id") == source_id:
            src["last_checked"] = _now()
            src["last_status"] = status
            src["error"] = error
            if captured_at:
                src["last_captured"] = captured_at
            break
    _write_config(root, config)


def connect_source(root, source: dict) -> dict:
    root = Path(root).resolve()
    if not isinstance(source, dict) or set(source) - {"id", "kind", "host", "workspace", "label", "path", "start_offset", "read_roots"}:
        raise ValueError("Invalid source configuration")
    if not all(isinstance(source.get(k), str) and source[k].strip() for k in ("id", "kind", "host", "workspace", "label")):
        raise ValueError("Source id, kind, host, workspace and label are required")
    if source["kind"] not in {"codex-transcript", "claude-workspace"}:
        raise ValueError("Unsupported source kind")
    config = _read_config(root)
    src = dict(source)
    if src["kind"] == "codex-transcript":
        p = Path(src.get("path", ""))
        if p.suffix.lower() != ".jsonl" or p.is_symlink() or not p.is_file():
            raise ValueError("Codex transcript must be an existing non-symlink JSONL file")
        # The default is opt-in from the current end, never historical backfill.
        if "start_offset" not in src:
            src["start_offset"] = p.stat().st_size
        if type(src["start_offset"]) is not int or src["start_offset"] < 0 or src["start_offset"] > p.stat().st_size:
            raise ValueError("Invalid transcript start_offset")
    else:
        ws = Path(src["workspace"]).resolve()
        if ws == root or root in ws.parents or ws in root.parents:
            raise ValueError("Claude workspace and knowledge base must not overlap")
        if src.get("read_roots", []) and not isinstance(src["read_roots"], list):
            raise ValueError("read_roots must be a list")
        roots = []
        for item in src.get("read_roots", []):
            rp = Path(item).resolve()
            if not rp.is_relative_to(ws) or any(part.startswith(".") for part in rp.relative_to(ws).parts):
                raise ValueError("read_roots must be visible paths inside workspace")
            roots.append(str(rp))
        src["workspace"] = str(ws)
        src["read_roots"] = roots
    old = [x for x in config["sources"] if x.get("id") != src["id"]]
    old.append(src)
    config["sources"] = old
    _write_config(root, config)
    return {k: v for k, v in src.items() if k != "path"} | {"connected": True}


def _cursor_path(root: Path, source_id: str) -> Path:
    key = _hash(source_id)
    return _inside(root, f".oks/daily-capture/cursors/{key}.json")


def _epoch_timestamp(root: Path, source_id: str, session: str) -> str:
    path = _inside(root, f".oks/daily-capture/epochs/{_hash(source_id + chr(0) + session)}.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["timestamp"]
    value = _now()
    store._atomic_write(path, json.dumps({"timestamp": value}).encode())
    return value


def _event_id(source_id: str, session: str, offset: int, text: str) -> str:
    return _hash(f"{source_id}\0{session}\0{offset}\0{_hash(text)}")


def _stable_timestamp(value, fallback):
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except ValueError:
            pass
    return fallback


def _blocks(content, allowed: set[str]) -> str:
    if not isinstance(content, list):
        return ""
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in allowed and isinstance(block.get("text"), str):
            out.append(block["text"])
    return "\n".join(x for x in out if x.strip())


def _codex_event(row: dict, source: dict, offset: int):
    if row.get("type") != "response_item" or not isinstance(row.get("payload"), dict):
        return None
    p = row["payload"]
    if p.get("type") != "message":
        return None
    role = p.get("role")
    phase = p.get("phase")
    if role == "user":
        text = _blocks(p.get("content"), {"input_text"})
        text = re.sub(r'<in-app-browser-context\b[^>]*>[\s\S]*?</in-app-browser-context>', '', text).strip()
        if text.startswith('## My request:'):
            text = text[len('## My request:'):].strip()
        if text.startswith(('<external_codex_apps_open_page>', '<environment_context>')):
            return None
        kind, phase = "discussion", None
    elif role == "assistant" and phase in {"commentary", "final"}:
        text = _blocks(p.get("content"), {"output_text"})
        kind = "discussion"
    else:
        return None
    if not text:
        return None
    meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
    passthrough = p.get("internal_chat_message_metadata_passthrough") or meta.get("internal_chat_message_metadata_passthrough", {})
    session = str(passthrough.get("turn_id") or row.get("thread_id") or "codex") if isinstance(passthrough, dict) else "codex"
    ts = _stable_timestamp(row.get("timestamp"), _epoch_timestamp(Path(source["_root"]), source["id"], session))
    return {"id": _event_id(source["id"], session, offset, text), "kind": kind,
            "role": role, "text": text, "timestamp": str(ts), "session_id": session,
            "locator": {"byte_offset": offset, "format": "codex-public-message"},
            **({"phase": phase, "final": phase == "final"} if role == "assistant" else {})}


def sync(root, source_id=None) -> dict:
    root = Path(root)
    config = _read_config(root)
    if config.get("enabled", True) is False:
        return {"sources": [], "captured": [], "count": 0, "status": "disabled"}
    sources = [s for s in config["sources"] if s.get("kind") == "codex-transcript" and (source_id is None or s.get("id") == source_id)]
    if source_id and not sources:
        raise ValueError("Unknown Codex transcript source")
    result = {"sources": [], "captured": [], "count": 0}
    for src in sources:
        path = Path(src["path"])
        cp = _cursor_path(root, src["id"])
        base = src["start_offset"]
        state = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {"offset": base, "size": path.stat().st_size}
        size = path.stat().st_size
        if size < state["offset"] or state.get("size", 0) > size:
            raise ValueError("Transcript changed or truncated; refusing replay")
        offset = state["offset"]
        events = []
        with path.open("rb") as f:
            f.seek(offset)
            while len(events) < MAX_BATCH:
                start = f.tell()
                line = f.readline(MAX_LINE + 1)
                if len(line) > MAX_LINE:
                    _source_status(root, src["id"], status="partial", error="transcript_line_too_large")
                    raise ValueError("Codex transcript line exceeds limit; cursor retained")
                if not line or not line.endswith(b"\n"):
                    break
                end = f.tell()
                try:
                    row = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    _source_status(root, src["id"], status="partial", error="malformed_jsonl_line")
                    raise ValueError("Malformed complete Codex transcript line; cursor retained") from None
                event = _codex_event(row, {**src, "_root": str(root)}, start)
                if event:
                    events.append(event)
                offset = end
        captured = daily_capture.append_events(root, src["id"], events, source={k: src[k] for k in ("id", "host", "workspace", "label", "path") if k in src}) if events else []
        store._atomic_write(cp, json.dumps({"offset": offset, "size": path.stat().st_size}).encode())
        _source_status(root, src["id"], status="captured" if captured else "checked", error=None,
                       captured_at=captured[-1].get("captured_at") if captured else None)
        result["captured"].extend(captured)
        result["count"] += len(captured)
        result["sources"].append({"id": src["id"], "offset": offset})
    return result


def observe_claude(root, payload) -> dict:
    root = Path(root).resolve()
    if not isinstance(payload, dict):
        raise ValueError("Hook payload must be an object")
    event_name = payload.get("hook_event_name")
    config = _read_config(root)
    if config.get("enabled", True) is False:
        return {"status": "disabled", "captured": [], "count": 0}
    cwd = payload.get("cwd")
    ws = Path(cwd).resolve() if isinstance(cwd, str) else None
    src = next((s for s in config["sources"] if s.get("kind") == "claude-workspace" and ws and s["workspace"] == str(ws)), None)
    if not src:
        return {"status": "unconnected", "captured": [], "count": 0}
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        return {"status": "partial", "captured": [], "count": 0, "error": "missing_session_id"}
    captures = []
    timestamp = _now()
    text = None; role = None; kind = "discussion"; phase = None; source_path = None; locator = None
    if event_name == "SessionStart":
        tp = payload.get("transcript_path")
        if isinstance(tp, str) and Path(tp).is_file():
            cp = _cursor_path(root, src["id"] + ":stop:" + session)
            store._atomic_write(cp, json.dumps({"offset": Path(tp).stat().st_size, "path": str(Path(tp).resolve())}).encode())
        _source_status(root, src["id"], status="checked")
        return {"status": "observed", "captured": [], "count": 0}
    if event_name == "UserPromptSubmit" and isinstance(payload.get("prompt"), str):
        text, role = payload["prompt"], "user"
    elif event_name == "PostToolUse" and payload.get("tool_name") == "Read":
        if isinstance(payload.get("tool_response"), dict) and payload["tool_response"].get("is_error"):
            return {"status": "ignored", "captured": [], "count": 0}
        raw = payload.get("tool_response")
        text = raw.get("file", {}).get("content") if isinstance(raw, dict) and isinstance(raw.get("file"), dict) else None
        if text is None and isinstance(raw, dict): text = raw.get("text")
        if not isinstance(text, str): return {"status": "partial", "captured": [], "count": 0, "error": "unrecognized_read_response"}
        tool_input = payload.get("tool_input", {})
        pathval = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        p = Path(pathval).resolve() if isinstance(pathval, str) else None
        roots = [Path(x) for x in src.get("read_roots", [])]
        if not p or p.is_symlink() or any(part.startswith(".") for part in p.parts) or not any(p.is_relative_to(r) for r in roots):
            return {"status": "ignored", "captured": [], "count": 0}
        role, kind, source_path = "source", "reading", str(p)
        locator = {"line_start": tool_input.get("offset", 1), "line_count": tool_input.get("limit")}
    elif event_name == "Stop" and isinstance(payload.get("last_assistant_message"), str):
        # Claude writes transcripts asynchronously. Stop's public final text is
        # authoritative even while the last transcript line is still missing.
        text, role, phase = payload["last_assistant_message"], "assistant", "final"
    elif event_name == "Stop":
        tp = payload.get("transcript_path")
        if not isinstance(tp, str): return {"status": "partial", "captured": [], "count": 0, "error": "missing_transcript_path"}
        p = Path(tp).resolve()
        home = Path.home().resolve()
        proj = home / ".claude" / "projects"
        if not p.is_relative_to(proj) or p.suffix != ".jsonl" or session != p.stem:
            return {"status": "rejected", "captured": [], "count": 0, "error": "transcript_path_out_of_scope"}
        cp = _cursor_path(root, src["id"] + ":stop:" + session)
        if not cp.exists():
            # Without a SessionStart baseline, do not replay resumed history.
            store._atomic_write(cp, json.dumps({"offset": p.stat().st_size, "path": str(p)}).encode())
            return {"status": "partial", "captured": [], "count": 0, "error": "transcript_baseline_missing"}
        state = json.loads(cp.read_text())
        size = p.stat().st_size
        if state.get("path") != str(p) or size < state["offset"]:
            return {"status": "partial", "captured": [], "count": 0, "error": "transcript_changed"}
        events = []; off = state["offset"]
        with p.open("rb") as f:
            f.seek(off)
            while len(events) < MAX_BATCH:
                start = f.tell(); line = f.readline(MAX_LINE + 1)
                if len(line) > MAX_LINE:
                    return {"status": "partial", "captured": [], "count": 0, "error": "transcript_line_too_large"}
                if not line or not line.endswith(b"\n"): break
                try:
                    row = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return {"status": "partial", "captured": [], "count": 0, "error": "malformed_transcript_line"}
                msg = row.get("message") if isinstance(row.get("message"), dict) else {}
                if row.get("type") != "assistant" or msg.get("type") != "message" or msg.get("role") != "assistant":
                    off = f.tell(); continue
                body = msg.get("content")
                text = _blocks(body, {"text"})
                if text:
                    ph = "final" if row.get("stop_reason") or msg.get("stop_reason") else "commentary"
                    ts = _stable_timestamp(row.get("timestamp"), _epoch_timestamp(root, src["id"], session))
                    events.append({"id": _event_id(src["id"], session, start, text), "kind": "discussion", "role": "assistant", "text": text, "timestamp": ts, "session_id": session, "phase": ph, "final": ph == "final"})
                off = f.tell()
        captured = daily_capture.append_events(root, src["id"], events, source={k: src[k] for k in ("id", "host", "workspace", "label")}) if events else []
        store._atomic_write(cp, json.dumps({"offset": off, "size": size, "path": str(p)}).encode())
        _source_status(root, src["id"], status="captured" if captured else "checked", error=None,
                       captured_at=captured[-1].get("captured_at") if captured else None)
        return {"status": "observed", "captured": captured, "count": len(captured)}
    if not isinstance(text, str) or not text.strip(): return {"status": "ignored", "captured": [], "count": 0}
    identity = payload.get("transcript_offset")
    if identity is None:
        identity = payload.get("prompt_id") or payload.get("tool_use_id") or payload.get("event_id") or payload.get("uuid") or _hash(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    eid = _event_id(src["id"], session, int(identity) if isinstance(identity, int) else int(_hash(str(identity))[:12], 16), text)
    item = {"id": eid, "kind": kind, "role": role, "text": text, "timestamp": _epoch_timestamp(root, src["id"], session), "session_id": session}
    if phase: item.update(phase=phase, final=phase == "final")
    if source_path: item.update(source_path=source_path, locator=locator)
    captured = daily_capture.append_events(root, src["id"], [item], source={k: src[k] for k in ("id", "host", "workspace", "label")})
    _source_status(root, src["id"], status="captured" if captured else "checked", error=None,
                   captured_at=captured[-1].get("captured_at") if captured else None)
    return {"status": "observed", "captured": captured, "count": len(captured)}


def overview(root) -> dict:
    config = _read_config(Path(root))
    return {"enabled": bool(config.get("enabled", True)), "sources": [dict(s, status=s.get("last_status", "connected"), last_checked=s.get("last_checked"), last_captured=s.get("last_captured"), error=s.get("error")) for s in config["sources"]]}
