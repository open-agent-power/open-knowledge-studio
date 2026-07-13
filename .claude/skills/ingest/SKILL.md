---
description: Triage raw/ files — AI assess quality, A-grade writes to drafts/
---

# /ingest — Raw Material Triage

## Purpose

Scan `raw/` for unprocessed materials, AI-assess quality, and write high-value items as draft proposals to `drafts/`.

## Pipeline

1. **Scan raw/** — List files in raw/articles/, raw/papers/, raw/repos/, raw/misc/.
2. **For each file, AI-assess:**
   - **Relevance** — Does this relate to active domains?
   - **Quality** — Is the content substantial (≥50 chars)?
   - **Novelty** — Run `oks search <keywords>` to check duplicates.
   - **Grade**: A (→ drafts/), B (→ digest), C (skip)
3. **For A-grade items** — Extract concepts, determine type + area, write to `drafts/{slug}.md`.
4. **Report** — Summary: X scanned, Y drafted, Z digested, W skipped.

## Rules

- Never write directly to `wiki/` — always through `drafts/` for human review.
- Include source reference in the draft body.
