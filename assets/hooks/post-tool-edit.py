#!/usr/bin/env python3
"""PostToolUse hook — file conflict detection + recall supplement.

Reads JSON payload on stdin (Claude Code / Qoder PostToolUse):
{ tool_name, tool_input, session_id, cwd }.

Two jobs (both fail-open, never block a tool):

1. **File conflict detection** (Edit/Write/MultiEdit only):
   - Append to records/file-edits.jsonl (agent_id + file + ts) — git-shared
   - Check if another agent edited the same file within CONFLICT_WINDOW
   - If conflict, write mail to inbox/ for current agent (type=conflict)

2. **Recall supplement** (any tool — solves long-task blind spot):
   - UserPromptSubmit only fires when the user speaks; a long autonomous task
     (Read → Edit → Bash → Edit → ...) has no new user prompts, so recall
     never injects — the agent executes blind to relevant memory.
   - PostToolUse fires after every tool call: we extract a query from the
     tool operation (file basename / bash command / grep pattern) and run
     recall with a HIGHER floor (0.9) + lower topn (2) to avoid noise.
   - Shares recall-state-{session}.json + cooldown with UserPromptSubmit so
     the same slug isn't re-injected twice.

Tunables live in settings/recall.yaml (posttool.* / conflict.window /
search_backend) via load_recall_params. OKS_AGENT_ID env still names the agent
identity (default: cwd basename).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from _persistence import append_jsonl, atomic_write_text, file_lock

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


# ── File conflict detection (unchanged) ──

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
    """Check if another agent edited this file within the conflict window."""
    path = _file_edits_path(kb_root)
    if not path.is_file():
        return None
    now = datetime.now(timezone.utc)
    try:
        from knowledge_studio.recall import load_recall_params
        conflict_window = int(load_recall_params(kb_root).get("conflict_window", 300))
    except Exception:
        conflict_window = 300
    window = timedelta(seconds=conflict_window)
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


# ── Recall supplement (new — long-task blind spot) ──

def _state_path(session_id: str, kb_root: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80] or "default"
    d = kb_root / ".oks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"recall-state-{safe}.json"


def _load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return {"n": int(state.get("n", 0)), "seen": dict(state.get("seen", {}))}
    except Exception:
        pass
    return {"n": 0, "seen": {}}


def _save_state(path: Path, state: dict) -> None:
    try:
        atomic_write_text(path, json.dumps(state))
    except Exception:
        pass


def _inject_trace_path(kb_root: Path) -> Path:
    d = kb_root / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d / "inject.jsonl"


def _append_inject_trace(
    kb_root: Path, agent_id: str, session_id: str, query: str,
    picked: list, source: str = "posttool",
) -> None:
    """Append inject record (git-shared training signal, same format as UserPromptSubmit)."""
    path = _inject_trace_path(kb_root)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent_id": agent_id,
        "session_id": session_id,
        "source": source,
        "query": query,
        "injected": [
            {
                "slug": str(h.get("slug", "")),
                "title": str(h.get("title", "")),
                "relevance": float(h.get("relevance", 0)),
                "type": str(h.get("type", "")),
            }
            for h in picked
        ],
    }
    try:
        append_jsonl(path, rec, lock_path=kb_root / ".oks" / "locks" / "inject.lock")
    except Exception:
        pass


def _query_from_tool(tool_name: str, tool_input: dict) -> str:
    """Extract a recall query from the tool operation.

    Long-task agent has no user prompt — we derive a query from what the
    tool just touched:
      Edit/Write/Read/MultiEdit → file basename (stem, no ext)
      Bash                      → command first ~6 meaningful words
      Grep/Glob                 → pattern
    """
    for k in ("file_path", "path"):
        fp = str(tool_input.get(k, "") or "")
        if fp:
            stem = Path(fp).stem
            if stem:
                return stem
    cmd = str(tool_input.get("command", "") or "")
    if cmd:
        # Filter path tokens (~/, /) + stopwords to get meaningful query.
        words = [
            w for w in re.split(r"\s+", cmd)
            if w and not w.startswith("-")
            and not w.startswith("~")
            and "/" not in w
            and w not in ("&&", "||", "|", "sudo", "cd", ";", "python", "python3",
                         "bash", "sh", "echo", "cat", "ls", "grep", "head",
                         "tail", "wc", "find", "sed", "awk", "export")
        ]
        return " ".join(words[:6])
    pat = str(tool_input.get("pattern", "") or tool_input.get("query", "") or "")
    if pat:
        return pat
    return ""


def _should_signal(tool_name: str, query: str, hits: list) -> bool:
    """Smart selectivity: not every tool call deserves a signal.

    Only signal when ALL hold:
    1. Tool type is knowledge-relevant (Edit/Write/Grep/Glob, not Bash/Read)
    2. Query is domain-specific (not generic words like git/status/ls)
    3. Top hit has very high relevance (> 2.5)

    Rationale: PostToolUse fires after every tool. Bash ops (git/ls/cd) and
    Read (AI already reading) don't need signals — they generate 85% noise.
    Only Edit/Write code + Grep/Glob search + high-rel + domain query signal.
    """
    # 1. Tool type: only Edit/Write/MultiEdit/Grep/Glob
    signal_tools = {"Edit", "Write", "MultiEdit", "edit", "write", "multiedit",
                   "Grep", "Glob", "grep", "glob"}
    if tool_name not in signal_tools:
        return False
    # 2. Query quality: generic words don't signal
    generic = {"git", "status", "ls", "cd", "rm", "mkdir", "cat", "echo", "pwd",
              "find", "sed", "awk", "export", "pip", "npm", "node", "python",
              "bash", "sh", "test", "run", "build", "make", "tail", "head", "wc"}
    ql = (query or "").lower().strip()
    words = ql.split()
    if len(ql) < 4 or (words and words[0] in generic):
        return False
    # 3. Relevance: top1 rel > 2.5 (very high, not token-overlap noise)
    if not hits or float(hits[0].get("relevance", 0)) < 2.5:
        return False
    return True


def _recall_supplement(
    kb_root: Path, session_id: str, query: str, agent_id: str,
    tool_name: str = "",
) -> str:
    """PostToolUse recall — inject relevant memory after tool calls.

    Higher floor (0.9) + lower topn (2) than UserPromptSubmit (0.7 / 3) —
    PostToolUse fires often, we only surface high-confidence hits to avoid
    drowning the agent's execution flow.
    """
    if not query or len(query) < 3:
        return ""
    try:
        from knowledge_studio.recall import recall
    except Exception:
        return ""

    from knowledge_studio.recall import load_recall_params
    p = load_recall_params(kb_root)
    floor = p["posttool_floor"]
    topn = p["posttool_topn"]
    cooldown = p["recall_cooldown"]
    search_backend = p["search_backend"]

    state_path = _state_path(session_id, kb_root)
    state = _load_state(state_path)
    state["n"] += 1
    turn = state["n"]

    try:
        hits = recall(
            query=query, limit=max(topn * 3, 6),
            knowledge_only=True, search_backend=search_backend,
        ).get("knowledge", [])
    except Exception:
        hits = []

    # Smart selectivity: not every tool call deserves a signal.
    # Skip Bash/Read ops + generic queries + low-rel — they're 85% noise.
    if not _should_signal(tool_name, query, hits):
        _save_state(state_path, state)  # still advance turn counter
        return ""

    picked = []
    for h in hits:
        if float(h.get("relevance", 0)) < floor:
            continue
        slug = str(h.get("slug", "")).strip()
        last = state["seen"].get(slug)
        if slug and last is not None and turn - int(last) < cooldown:
            continue
        picked.append(h)
        if len(picked) >= topn:
            break

    if not picked:
        _save_state(state_path, state)
        return ""

    for h in picked:
        slug = str(h.get("slug", "")).strip()
        if slug:
            state["seen"][slug] = turn
    _save_state(state_path, state)

    _append_inject_trace(kb_root, agent_id, session_id, query, picked, source="posttool")

    # 提示模式（exposure-based）：只告知“有记忆可用”，不注入内容。
    # AI 看到信号后自主决定是否调 oks recall 取详情——token 省 90%，
    # 沉默期仍有信号（避免长任务盲区），AI 不被强制注入无关内容。
    # posttool.mode=full 恢复旧行为（注入完整 body）。
    mode = str(p.get("posttool_mode", "signal"))
    if mode == "full":
        out = ['<recalled-memory source="oks-posttool">']
        out.append(f'<!-- query="{query}" floor={floor} (PostToolUse supplement) -->')
        for h in picked:
            body = str(h.get("body_preview", ""))[:280]
            out.append(
                f"- [{h.get('type', '')}] {h.get('title', '')} "
                f"(slug: {h.get('slug', '')}, rel: {h.get('relevance', 0)})"
            )
            out.append(f"  {body}")
        out.append("</recalled-memory>")
    else:  # signal mode（默认）——只 slug + rel + 引导，不注入 body
        out = ['<oks-memory-signal source="oks-posttool">']
        out.append(f'<!-- query="{query}" floor={floor} (signal: slugs only, no body) -->')
        for h in picked:
            out.append(
                f"- [{h.get('type', '')}] {h.get('title', '')} "
                f"(slug: {h.get('slug', '')}, rel: {h.get('relevance', 0)})"
            )
        out.append(f'  需要详情: oks recall "{query}" --explain')
        out.append("</oks-memory-signal>")
    return "\n".join(out)


def main() -> int:
    payload = _load_payload()
    tool_name = str(payload.get("tool_name", "") or "")
    tool_input = payload.get("tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        return 0
    kb_root = _kb_root()
    if kb_root is None:
        return 0
    cwd = str(payload.get("cwd", "") or "") or str(os.getcwd())
    agent_id = _agent_id(payload, cwd)
    session_id = str(payload.get("session_id", "") or "") or cwd

    output_parts = []

    # 1. File conflict detection (Edit/Write/MultiEdit only)
    if tool_name in EDIT_TOOLS:
        file_path = str(tool_input.get("file_path", "") or "")
        if file_path:
            _append_file_edit(kb_root, agent_id, file_path)
            other = _check_conflict(kb_root, agent_id, file_path)
            if other:
                _write_conflict_mail(kb_root, agent_id, file_path, other)
                output_parts.append(
                    f"[oks] 文件冲突: {Path(file_path).name} 也被 "
                    f"{other.get('agent_id')} 编辑"
                )

    # 2. Recall supplement (any tool — long-task blind spot)
    # posttool.recall=0 disables recall supplement (keeps conflict detection).
    try:
        from knowledge_studio.recall import load_recall_params
        recall_on = bool(load_recall_params(kb_root).get("posttool_recall", 1))
    except Exception:
        recall_on = True
    if recall_on:
        query = _query_from_tool(tool_name, tool_input)
        if query:
            block = _recall_supplement(kb_root, session_id, query, agent_id, tool_name)
            if block:
                output_parts.append(block)

    if output_parts:
        sys.stdout.write("\n".join(output_parts) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
