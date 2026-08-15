#!/usr/bin/env python3
"""UserPromptSubmit hook — auto-recall memory + goals + mail, inject as context.

Reads the editor's JSON payload on stdin (Claude Code / Qoder / pi extension pass
{ prompt, session_id, cwd? }). Runs the OKS recall engine, reads active goals +
unread mail, prints a structured <recalled-memory> block on stdout.

Agent identity: env OKS_AGENT_ID > payload agent_id > cwd basename > "unknown".
Terminal registry (profiles/agents/registry.jsonl, git-shared): binds agent+cwd
to profile/goal. New terminal with no registry entry + no active goals → inject
first-run guide prompting AI to ask the user (→ /assess builds profile/goal,
writes registry). Subsequent prompts use active goals or registry goals.

Inject trace (records/inject.jsonl, git-shared): appends what was injected
(session/turn/agent/cwd/slugs/rels) as a training signal. sqlite (local, fast)
added in Phase 2b.

Fails open: any error or empty result prints nothing and exits 0.

Tunables via env:
  OKS_AGENT_ID         agent identity (default: cwd basename)
  OKS_RECALL_FLOOR     min knowledge relevance to inject (default 0.7)
  OKS_RECALL_TOPN      max knowledge memories injected (default 3)
  OKS_RECALL_MINLEN    skip prompts shorter than this many chars (default 6)
  OKS_RECALL_COOLDOWN  turns before the same slug may be re-injected (default 10)
  OKS_MAIL_TOPN        max unread mail injected (default 3)
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _persistence import append_jsonl, atomic_write_text, file_lock

_TRIVIAL = {
    "你好", "谢谢", "多谢", "ok", "okay", "好", "好的", "嗯", "行", "继续",
    "hi", "hello", "thanks", "thx", "yes", "no", "是", "对", "收到",
}


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


def _state_path(session_id: str, kb_root: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80] or "default"
    state_dir = kb_root / ".oks"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"recall-state-{safe}.json"


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


def _load_active_goals(kb_root: Path) -> list:
    """Read profiles/goals/*.md with status: active. Returns title/slug/keywords."""
    goals_dir = kb_root / "profiles" / "goals"
    if not goals_dir.is_dir():
        return []
    goals = []
    for f in sorted(goals_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            parts = text.split("---")
            if len(parts) >= 2 and "status: active" in parts[1]:
                title = f.stem
                keywords = []
                in_kw = False
                for line in parts[1].split("\n"):
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip("\"'")
                    elif line.startswith("keywords:"):
                        in_kw = True
                    elif in_kw:
                        s = line.strip()
                        if s.startswith("- "):
                            keywords.append(s[2:].strip())
                        elif s and not line.startswith(" "):
                            in_kw = False
                goals.append({"title": title, "slug": f.stem, "keywords": keywords})
        except Exception:
            continue
    return goals


# ── Terminal registry (profiles/agents/registry.jsonl, git-shared) ──

def _agent_id(payload: dict, cwd: str) -> str:
    """Agent identity: env OKS_AGENT_ID > payload agent_id > cwd basename."""
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


def _registry_path(kb_root: Path) -> Path:
    d = kb_root / "profiles" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d / "registry.jsonl"


def _find_registry_entry(kb_root: Path, agent_id: str, cwd: str) -> dict | None:
    """Find registry entry matching agent_id + cwd (terminal identity)."""
    path = _registry_path(kb_root)
    if not path.is_file():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                    return rec
            except Exception:
                continue
    except Exception:
        pass
    return None


def _touch_registry_last_active(kb_root: Path, agent_id: str, cwd: str) -> None:
    """Update last_active timestamp for existing entry (best-effort, no create)."""
    path = _registry_path(kb_root)
    if not path.is_file():
        return
    try:
        lock = kb_root / ".oks" / "locks" / "registry.lock"
        with file_lock(lock):
            lines = path.read_text(encoding="utf-8").splitlines()
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            out = []
            changed = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                        rec["last_active"] = ts
                        changed = True
                        out.append(json.dumps(rec, ensure_ascii=False))
                    else:
                        out.append(line)
                except Exception:
                    out.append(line)
            if changed:
                atomic_write_text(path, "\n".join(out) + "\n")
    except Exception:
        pass


# ── Mail ──

def _load_unread_mail(kb_root: Path, limit: int = 3) -> list:
    inbox = kb_root / "mail" / "inbox"
    if not inbox.is_dir():
        return []
    mails = []
    for f in sorted(inbox.glob("*.md"), reverse=True):
        try:
            text = f.read_text(encoding="utf-8")
            parts = text.split("---")
            if len(parts) >= 3 and "read: false" in parts[1]:
                from_id = "unknown"
                title = ""
                for line in parts[1].split("\n"):
                    if line.startswith("from:"):
                        from_id = line.split(":", 1)[1].strip()
                for line in parts[2].split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                preview = re.sub(r"\s+", " ", parts[2].split("\n", 1)[-1]).strip()[:100]
                mails.append({
                    "slug": f.stem, "from": from_id, "title": title,
                    "preview": preview, "path": f,
                })
                if len(mails) >= limit:
                    break
        except Exception:
            continue
    return mails


def _mark_mail_read(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
        text = text.replace("read: false", "read: true", 1)
        path.write_text(text, encoding="utf-8")
    except Exception:
        pass


# ── Inject trace (records/inject.jsonl, git-shared training signal) ──

def _inject_trace_path(kb_root: Path) -> Path:
    d = kb_root / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d / "inject.jsonl"


def _write_inject_trace(kb_root: Path, session_id: str, turn: int,
                        agent_id: str, cwd: str, prompt: str,
                        slugs: list, rels: list) -> None:
    path = _inject_trace_path(kb_root)
    rec = {
        "session_id": session_id,
        "turn": turn,
        "agent_id": agent_id,
        "cwd": cwd,
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:12],
        "slugs": slugs,
        "rels": rels,
        "injected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        append_jsonl(
            path,
            rec,
            lock_path=kb_root / ".oks" / "locks" / "inject.lock",
        )
    except Exception:
        pass


def main() -> int:
    payload = _load_payload()
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        return 0

    minlen = int(os.environ.get("OKS_RECALL_MINLEN", "6"))
    if len(prompt) < minlen or prompt.lower() in _TRIVIAL:
        return 0

    kb_root = _kb_root()
    if kb_root is None:
        return 0

    session_id = str(payload.get("session_id", "") or "")
    cwd = str(payload.get("cwd", "") or "") or str(os.getcwd())
    agent_id = _agent_id(payload, cwd)

    state_file = _state_path(session_id, kb_root)
    state = _load_state(state_file)
    is_first_turn = state.get("n", 0) == 0

    # ── Terminal registry lookup (agent_id + cwd) ──
    reg_entry = _find_registry_entry(kb_root, agent_id, cwd)
    reg_goals = reg_entry.get("goal_slugs", []) if reg_entry else []
    goals_all = _load_active_goals(kb_root)
    has_goals = len(goals_all) > 0

    # ── Knowledge section (6+1 recall + cooldown) ──
    try:
        from knowledge_studio.recall import recall
    except Exception:
        recall = None

    picked: list = []
    goal_relevant = False

    if recall is not None:
        floor = float(os.environ.get("OKS_RECALL_FLOOR", "0.7"))
        topn = int(os.environ.get("OKS_RECALL_TOPN", "3"))
        cooldown = int(os.environ.get("OKS_RECALL_COOLDOWN", "10"))

        state["n"] += 1
        turn = state["n"]

        # registry 精准 boost + scope 过滤
        goal_param = ",".join(reg_goals) if reg_goals else None
        reg_scope = reg_entry.get("scope", []) if reg_entry else []
        scope_param = ",".join(reg_scope) if reg_scope else None
        try:
            hits = recall(query=prompt, limit=max(topn * 3, 10), goal=goal_param, scope=scope_param).get("knowledge", [])
        except Exception:
            hits = []

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

        if picked:
            for h in picked:
                slug = str(h.get("slug", "")).strip()
                if slug:
                    state["seen"][slug] = turn
            for h in picked:
                c = h.get("score_components", {})
                if c.get("goal_area", 0) > 0 or c.get("goal_keyword", 0) > 0:
                    goal_relevant = True
                    break
        _save_state(state_file, state)

    # goal 相关性双重判断：query 和 goal keywords 直接匹配（不依赖 picked，
    # 避免 cooldown 补位到非 goal 域页时漏判）
    if not goal_relevant:
        prompt_lower = prompt.lower()
        for g in goals_all:
            for kw in g.get("keywords", []):
                if kw.lower() in prompt_lower:
                    goal_relevant = True
                    break
            if goal_relevant:
                break

    # ── Build sections ──
    sections = []

    # 首次引导：新 session + 没绑 goal → 询问（一次性，AI 反问人类建档）
    show_first_run = is_first_turn and not reg_goals
    if show_first_run:
        sections.append(
            "## 首次使用（新终端）\n"
            "注册表无此终端的 goal 绑定。\n"
            "建议反问用户确认：当前目标 / 技术栈 / 项目。\n"
            "确认后调 /assess 建档 + `oks registry bind` 绑定 goal，后续 hook 显示 goal。"
        )

    # Goal section: 只在 registry 绑了 goal 时显示（没绑 = 永远不显示）
    if reg_goals and not show_first_run:
        display = [g for g in goals_all if g["slug"] in reg_goals]
        if display:
            lines = ["## 当前目标"]
            for g in display:
                lines.append(f"[goal] {g['title']} ({g['slug']})")
            sections.append("\n".join(lines))

    # Knowledge section（总是，不管是否引导）
    if picked:
        lines = [
            "## 相关记忆",
            "相关已沉淀记忆（引用时用 slug；与当前事实冲突以最新为准）：",
        ]
        for h in picked:
            title = str(h.get("title", h.get("slug", ""))).strip()
            slug = str(h.get("slug", "")).strip()
            htype = str(h.get("type", "")).strip()
            rel = float(h.get("relevance", 0))
            preview = re.sub(r"\s+", " ", str(h.get("body_preview", ""))).strip()[:160]
            lines.append(f"- [{htype}] {title} ({slug}) rel={rel:.2f}")
            if preview:
                lines.append(f"    {preview}")
        sections.append("\n".join(lines))

    # Mail section
    mail_topn = int(os.environ.get("OKS_MAIL_TOPN", "3"))
    mails = _load_unread_mail(kb_root, limit=mail_topn)
    if mails:
        lines = [f"## 通信（{len(mails)} 未读）"]
        for m in mails:
            lines.append(f"[mail] [@{m['from']}] {m['title']} — {m['slug']}")
            if m["preview"]:
                lines.append(f"    {m['preview']}")
        sections.append("\n".join(lines))
        for m in mails:
            _mark_mail_read(m["path"])

    # 更新 registry last_active（best-effort）
    if reg_entry:
        _touch_registry_last_active(kb_root, agent_id, cwd)

    # 写 inject 埋点 jsonl（git 共享训练信号）
    if picked:
        _write_inject_trace(
            kb_root, session_id, state.get("n", 0), agent_id, cwd, prompt,
            [str(h.get("slug", "")).strip() for h in picked],
            [round(float(h.get("relevance", 0)), 2) for h in picked],
        )

    if not sections:
        return 0

    out = ['<recalled-memory source="oks">']
    out.extend(sections)
    # 自评闭环：AI 用完后自评，对实际引用的记忆调 oks wiki use，无需人类手动
    if picked:
        out.append("")
        out.append(
            "[自评闭环] 埋点由你（AI）代填（人类懒惰不手动）：\n"
            "1. 你实际引用了的记忆 → 调 `oks wiki use <slug>`（标 used + access_count++）\n"
            "2. 观察用户后续回复——用户接受/引用了某条 → 代调 `oks wiki use <slug>`；"
            "用户明确拒绝（\"不要\"/\"错了\"）→ 不调（默认未采纳）\n"
            "无用忽略——下次 cooldown 换别的。信号都在对话里，你代人类完成。"
        )
    out.append("</recalled-memory>")
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
