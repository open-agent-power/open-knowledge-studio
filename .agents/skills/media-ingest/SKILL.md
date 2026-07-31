---
description: Prepare local oral or screen-recording videos as review bundles, then add human-approved Markdown to raw/misc/
---

# /media-ingest — Human-Gated Video Intake

## Purpose

Convert a user-provided local video into a reviewable evidence bundle without changing the existing Raw → Draft → Wiki pipeline.

## Rules

- Support only local oral and screen-recording videos in this stage.
- Never summarize or invent missing content during preparation.
- Never write directly to `drafts/` or `wiki/`.
- `prepare` writes only to `.oks/intake/`.
- Before `approve`, ask the user to review `candidate.md` and `quality-report.md`.
- Only run `approve --confirm-human-review` after explicit user approval.
- Preserve the source URL, save reason, original ASR, warnings, and content hash.

## Workflow

1. Confirm the local video path, source URL, title, save reason, and whether the content is oral or screen-based.
2. Install optional dependencies from `scripts/media_ingest_requirements.txt` when needed.
3. Run `python scripts/media_ingest.py prepare ...`.
4. Show the user the generated candidate and quality report paths.
5. Wait for explicit review approval.
6. Run `python scripts/media_ingest.py approve <capture-id> --confirm-human-review --review-note "..."`.
7. Hand the resulting `raw/misc/*.md` file to the existing `/ingest` skill.

This local-video command is an experimental adapter, not the canonical multimodal pipeline. The canonical contract lives in this repository under `schemas/`.
