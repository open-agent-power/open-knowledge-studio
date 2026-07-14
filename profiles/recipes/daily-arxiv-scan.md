---
title: Daily arXiv Paper Scan
type: recipe
trigger: scheduled
schedule: "0 9 * * *"
tools:
  - curl
  - pdftotext
domains:
  - computing
  - AI
keywords:
  - agent
  - self-evolving
  - knowledge management
status: active
---

# Daily arXiv Paper Scan

Scan arXiv for new papers matching team keywords, ingest to raw/,
and triage for drafting.

## Steps

1. Query arXiv API for `cs.AI` and `cs.CL` categories with team keywords
2. Download PDFs via `curl`
3. Extract text via `pdftotext`
4. Write to `raw/{YYYY}/{MM}/{DD}/papers/{slug}.md`
5. Run A/B/C triage — A-grade to `drafts/`, B/C skip
6. Report summary: X scanned, Y drafted, Z skipped
