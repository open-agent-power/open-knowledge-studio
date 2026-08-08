# Scenario A — Markdown

**Status**: FULL PASS
**Date**: 2026-08-06

## Command

```powershell
# Via /ingest skill: "收录这个 Markdown"
# Equivalent CLI:
oks raw-commit .oks/runs/run-e2e-md-{id}/manifest --overwrite
```

## Input

- **File**: `README.md` (repository root)
- **SHA256**: varies by commit
- **Size**: 5,159 bytes (post-rewrite); original ~5K

## Provider

- `text-read` (agent_native) — direct file read via Agent

## Bundle

- **ID**: `bundle:81a563e3ec24fc6a`
- **Path**: `raw/2026/08/06/agent-capture/bundle-81a563e3ec24fc6a`

## Evidence

- **Count**: 1 record
- **Locator**: `kind: custom, custom_label: README.md full text`
- **Content**: complete Markdown text

## Completeness

- **Status**: complete
- **Missing**: none
- **Known Limits**: none

## Commit

`8b28b4c` fix(release): close 6 RC readiness gaps
