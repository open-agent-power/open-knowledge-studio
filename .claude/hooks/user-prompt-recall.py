#!/usr/bin/env python3
"""UserPromptSubmit hook — auto-recall relevant memory and inject it as context.

Reads the editor's UserPromptSubmit JSON payload on stdin (Claude Code and Qoder
share the same `.prompt` contract), runs the OKS recall engine against the user's
prompt, and prints a compact <recalled-memory> block on stdout (which the editor
adds to the model's context). Fails open: any error or empty result prints nothing
and exits 0, so it never blocks a prompt.

Tunables via env:
  OKS_RECALL_FLOOR   min knowledge relevance to inject (default 0.7)
  OKS_RECALL_TOPN    max memories injected (default 3)
  OKS_RECALL_MINLEN  skip prompts shorter than this many chars (default 6)
"""
import json
import os
import re
import sys

_TRIVIAL = {
    "你好", "谢谢", "多谢", "ok", "okay", "好", "好的", "嗯", "行", "继续",
    "hi", "hello", "thanks", "thx", "yes", "no", "是", "对", "收到",
}


def _load_prompt() -> str:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("prompt", "") or "")
    return ""


def main() -> int:
    prompt = _load_prompt().strip()
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

    picked = [h for h in hits if float(h.get("relevance", 0)) >= floor][:topn]
    if not picked:
        return 0

    lines = [
        "<recalled-memory source=\"oks\">",
        "知识库中与本次输入相关的已沉淀记忆（按相关度排序）。回答时优先参考并按 slug 引用；"
        "若与当前事实冲突以最新为准；学到值得留存的新知识时用 oks 写入 drafts/wiki。",
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
