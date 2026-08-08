# Scenario B — Text PDF

**Status**: FULL PASS
**Date**: 2026-08-05

## Command

```powershell
oks raw-commit tmp/cli-scenario-b/manifest --output tmp/scenario-b --overwrite
```

## Input

- **File**: `tmp/pdfs/w3c-prov-sem-direct.pdf`
- **Size**: 749,984 bytes
- **Pages**: 33
- **Text layer**: present

## Provider

- `pdf-lite` (pymupdf4llm 0.0.27) — document.text.extract

## Bundle

- **ID**: `bundle:244b7db5` (from cli-scenario-b/)
- **Path**: `tmp/scenario-b/`

## Evidence

- **Count**: 33 records (one per page)
- **Locator**: `kind: page`
- **Content**: 126,880 chars extracted from text layer

## Completeness

- **Status**: complete
- **Missing**: none
- **Known Limits**: none (text-layer PDF, no OCR needed)

## Commit

`5cc358b` fix: build vendoring timing, Rich date rendering, test API adaptation
