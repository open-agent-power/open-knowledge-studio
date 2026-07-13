---
description: Health check — scan wiki/ for frontmatter issues, orphans, broken links
---

# /lint — Knowledge Health Check

## Purpose

Run health checks on the knowledge base and report issues.

## Steps

1. **Run lint** — Execute `oks lint`
2. **Review results** — Check for: missing frontmatter fields, orphan pages, dropped pages, digest parseability
3. **Fix issues** — Missing field: add to frontmatter. Orphan: add tags/traces. Dropped: pin, archive, or restore.
4. **Re-run** — Verify all issues resolved

## Rules

- Active coverage target: >90%
- All wiki pages must have: title, type, area in frontmatter
