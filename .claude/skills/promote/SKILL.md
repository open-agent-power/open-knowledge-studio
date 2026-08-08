---
description: Review drafts — list, promote to wiki/, or reject
---

# /promote — Draft Review & Promotion

## Purpose

List drafts in `drafts/`, let user review, promote accepted ones to `wiki/` or reject.

## Steps

1. **List drafts** — `oks drafts list`
2. **For each draft** — Show content/summary, then prompt once:
   "回复：批准 / 拒绝 / 修改：<内容>"
3. **Promote on explicit approval** — `oks drafts promote <slug>`
4. **Reject** — `oks drafts reject <slug>` (confirm first — irreversible)
5. **Edit** — User gives revised content, Agent updates draft, then promote or reject

## Rules

- Promoted pages get `status: provisional`, `importance: 0.7`
- If a draft carries a `source_note` (human intake comment), promote copies it
  verbatim onto the wiki page as `human_note` — the human's judgement survives.
- Rejected drafts are deleted permanently
- Always confirm before rejecting
