#!/usr/bin/env python3
"""PostToolUse hook — detect file edit conflicts across agents.

Reads JSON payload on stdin (Claude Code / Qoder PostToolUse):
{ tool_name, tool_input: {file_path}, session_id, cwd }.

For Edit/Write/MultiEdit tools:
1. Append to records/file-edits.jsonl (agent_id + file + ts) — git-shared
2. Check if another agent edited the same file within CONFLICT_WINDOW (5 min)
3. If conflict, write mail to inbox/ for current agent (type=conflict)

Fails open: any error exits 0, never blocks a tool.

Tunables via env:
  OKS_CONFLICT_WINDOW  seconds to consider a conflict (default 300 = 5 min)
  OKS_AGENT_ID         agent identity (default: cwd basename)
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from _persistence import append_jsonl, file_lock

CONFLICT_WINDOW = int(os.environ.get("OKS_CONFLICT_WINDOW", "300"))

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "edit", "write", "multiedit"}


def _load_payload() -> dict:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _kb_root() -> Path | None:
    env = os.environ.get("OKS_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    try:
        from knowledge_studio.config import get_kb_root
        r = get_kb_root()
        return r if r and Path(r).is_dir() else None
    except Exception:
        pass
    cwd = Path.cwd()
    return cwd if (cwd / "wiki").is_dir() else None


def _agent_id(payload: dict, cwd: str) -> str:
    aid = os.environ.get("OKS_AGENT_ID", "").strip()
    if aid:
        return aid
    aid = str(payload.get("agent_id", "") or "").strip()
    if aid:
        return aid
    if cwd:
        name = Path(cwd).name
        if name:
            return name
    return "unknown"


def _file_edits_path(kb_root: Path) -> Path:
    d = kb_root / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d / "file-edits.jsonl"


def _append_file_edit(kb_root: Path, agent_id: str, file_path: str) -> None:
    path = _file_edits_path(kb_root)
    rec = {
        "agent_id": agent_id,
        "file_path": file_path,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        append_jsonl(
            path,
            rec,
            lock_path=kb_root / ".oks" / "locks" / "file-edits.lock",
        )
    except Exception:
        pass


def _check_conflict(kb_root: Path, agent_id: str, file_path: str) -> dict | None:
    """Check if another agent edited this file within CONFLICT_WINDOW."""
    path = _file_edits_path(kb_root)
    if not path.is_file():
        return None
    now = datetime.now(timezone.utc)
    window = timedelta(seconds=CONFLICT_WINDOW)
    try:
        lock = kb_root / ".oks" / "locks" / "file-edits.lock"
        with file_lock(lock):
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("file_path") != file_path:
                        continue
                    if rec.get("agent_id") == agent_id:
                        continue
                    ts = datetime.fromisoformat(rec.get("ts", ""))
                    if now - ts < window:
                        return rec
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _write_conflict_mail(kb_root: Path, agent_id: str, file_path: str, other: dict) -> None:
    inbox = kb_root / "mail" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ts = now.strftime("%Y%m%dT%H%M%S")
    slug = f"{ts}-conflict-{agent_id}"
    other_id = other.get("agent_id", "unknown")
    other_ts = str(other.get("ts", "?"))[:19]
    content = (
        "---\n"
        f"from: system\n"
        f"to: @{agent_id}\n"
        f"timestamp: {now.isoformat()}\n"
        "read: false\n"
        "type: conflict\n"
        "priority: urgent\n"
        "action: review\n"
        "---\n\n"
        f"# 文件冲突: {Path(file_path).name}\n\n"
        f"你刚编辑了 `{file_path}`，但 `{other_id}` 在 {other_ts} 也编辑了该文件。\n"
        f"可能冲突——建议 review 对方的改动后再继续。\n"
    )
    try:
        (inbox / f"{slug}.md").write_text(content, encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    payload = _load_payload()
    tool_name = str(payload.get("tool_name", "") or "")
    if tool_name not in EDIT_TOOLS:
        return 0  # only watch edits, not reads/searches
    tool_input = payload.get("tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        return 0
    file_path = str(tool_input.get("file_path", "") or "")
    if not file_path:
        return 0
    kb_root = _kb_root()
    if kb_root is None:
        return 0
    cwd = str(payload.get("cwd", "") or "") or str(os.getcwd())
    agent_id = _agent_id(payload, cwd)
    _append_file_edit(kb_root, agent_id, file_path)
    other = _check_conflict(kb_root, agent_id, file_path)
    if other:
        _write_conflict_mail(kb_root, agent_id, file_path, other)
    return 0


if __name__ == "__main__":
    sys.exit(main())
