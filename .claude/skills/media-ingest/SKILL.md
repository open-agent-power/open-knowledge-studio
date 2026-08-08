---
description: Experimental video intake adapter — currently unavailable
---

# /media-ingest — Human-Gated Video Intake

**Status**: experimental
**Availability**: unavailable — required scripts are not yet packaged

## Purpose

Convert a user-provided local video into a reviewable evidence bundle.

## Required Scripts

| Script | Status |
|--------|--------|
| `scripts/media_ingest_requirements.txt` | not yet packaged |
| `scripts/media_ingest.py` | not yet packaged |

## Current State

This skill is an experimental adapter, not the canonical multimodal pipeline.
The required scripts (`media_ingest.py`, `media_ingest_requirements.txt`) are
not included in the current wheel.  This skill is published as a placeholder;
it will become available when the scripts are packaged.

## When Available

The workflow will be:

1. Confirm the local video path, source URL, title, save reason.
2. Install optional dependencies from the packaged requirements file.
3. Run the packaged `media_ingest.py prepare ...`.
4. Review the generated candidate and quality report.
5. After explicit approval, run `media_ingest.py approve ...`.
6. Hand the resulting `raw/misc/*.md` to the `/ingest` skill.

The canonical multimodal contract lives under `schemas/` in the installed package.
