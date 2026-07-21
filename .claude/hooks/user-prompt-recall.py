#!/usr/bin/env python3
"""UserPromptSubmit hook — auto-recall relevant memory and inject it as context.

Reads the editor's UserPromptSubmit JSON payload on stdin (Claude Code and Qoder
share the same `.prompt` contract), runs the OKS recall engine against the user's
prompt, and prints a compact <recalled-memory> block on stdout (which the editor
adds to the model's context). Fails open: any error or empty result prints nothing
and exits 0, so it never blocks a prompt.

Tunables via env:
  OKS_RECALL_FLOOR     min knowledge relevance to inject (default 0.7)
  OKS_RECALL_TOPN      max memories injected (default 3)
  OKS_RECALL_MINLEN    skip prompts shorter than this many chars (default 6)
  OKS_RECALL_COOLDOWN  turns before the same slug may be re-injected (default 10)
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

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


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80] or "default"
    return Path(tempfile.gettempdir()) / f"oks-recall-{safe}.json"


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
        path.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass  # state is best-effort; dedup degrades gracefully


def main() -> int:
    payload = _load_payload()
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        return 0

    minlen = int(os.environ.get("OKS_RECALL_MINLEN", "6"))
    if len(prompt) < minlen or prompt.lower() in _TRIVIAL:
        return 0

    try:
        from knowledge_studio.recall import recall
    except Exception:
        return 0  # engine unavailable — fail open

    floor = float(os.environ.get("OKS_RECALL_FLOOR", "0.7"))
    topn = int(os.environ.get("OKS_RECALL_TOPN", "3"))

    try:
        hits = recall(query=prompt, limit=max(topn, 5)).get("knowledge", [])
    except Exception:
        return 0

    cooldown = int(os.environ.get("OKS_RECALL_COOLDOWN", "10"))
    session_id = str(payload.get("session_id", "") or "")
    state_file = _state_path(session_id)
    state = _load_state(state_file)
    state["n"] += 1
    turn = state["n"]

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
        _save_state(state_file, state)
        return 0

    for h in picked:
        slug = str(h.get("slug", "")).strip()
        if slug:
            state["seen"][slug] = turn
    _save_state(state_file, state)

    lines = [
        "<recalled-memory source=\"oks\">",
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
    lines.append("</recalled-memory>")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
