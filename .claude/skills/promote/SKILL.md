---
description: Review drafts — list, promote to wiki/, or reject
---

# /promote — Draft Review & Promotion

## Purpose

List drafts in `drafts/`, let user review, promote accepted ones to `wiki/` or reject.

## Steps

1. **List drafts** — `oks drafts list`
2. **For each draft** — Show content, ask: `promote`, `reject`, or `edit`
3. **Promote** — `oks drafts promote <slug>` (optionally with --title, --type, --area)
4. **Reject** — `oks drafts reject <slug>` (confirm first — irreversible)
5. **Edit** — Open for editing, then promote or reject

## Rules

- Promoted pages get `status: provisional`, `importance: 0.7`
- If a draft carries a `source_note` (human intake comment), promote copies it
  verbatim onto the wiki page as `human_note` — the human's judgement survives.
- Rejected drafts are deleted permanently
- Always confirm before rejecting
