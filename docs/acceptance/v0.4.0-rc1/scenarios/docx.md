# Scenario F1 — DOCX

**Status**: FULL PASS
**Date**: 2026-08-05

## Command

```powershell
oks raw-commit tmp/scenario-f/manifest --output tmp/scenario-f --overwrite
```

## Input

- **File**: `tmp/02-converter-fixtures/test.docx`
- **Size**: 38,348 bytes

## Provider

- `markitdown` (0.1.6) — document.text.extract

## Bundle

- **ID**: from scenario F run
- **Path**: `tmp/scenario-f/`

## Evidence

- **Count**: 1 record (document-level)
- **Locator**: `kind: document`
- **Content**: full DOCX text extracted, tables preserved

## Completeness

- **Status**: complete
- **Missing**: none
- **Known Limits**: Complex formatting may be lost; embedded images not extracted

## Commit

`5cc358b` fix: build vendoring timing, Rich date rendering, test API adaptation
