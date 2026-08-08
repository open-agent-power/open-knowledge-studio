---
description: Extract Q&A from conversation, AI summarize, write to drafts/
---

# /archive — Conversation Q&A Archival

## Purpose

Extract valuable Q&A from the current conversation, AI summarize into wiki pages, write to `drafts/`.

## Steps

1. **Scan conversation** — Identify Q&A pairs with reusable knowledge.
2. **AI summarize** — Determine type + area, write concise body.
3. **Write draft** — `drafts/{slug}.md` with draft frontmatter.
4. **Report** — Summary of archived items.

## Rules

- Only archive high-value, reusable knowledge.
- Never write directly to `wiki/` — always through `drafts/`.
