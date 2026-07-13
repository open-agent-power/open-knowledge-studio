---
description: Re-compile a concept page — read source/traces, AI regenerate, write to drafts/
---

# /compile — Concept Page Recompilation

## Purpose

Re-read a wiki page's sources and traces, use AI to regenerate an improved version, write to `drafts/`.

## Steps

1. **Select page** — Ask user for slug, or `oks wiki list` to show candidates.
2. **Read page** — `oks wiki get <slug>` to load content + frontmatter.
3. **Gather sources** — Read referenced sources, traces, linked pages.
4. **AI regenerate** — Rewrite body with improved structure, updated content, better cross-refs.
5. **Write draft** — Write to `drafts/{slug}-recompiled.md` with draft frontmatter.
6. **Report** — Show diff summary.

## Rules

- Never overwrite wiki page directly — always through drafts/.
- Preserve original frontmatter (tags, traces, review).
