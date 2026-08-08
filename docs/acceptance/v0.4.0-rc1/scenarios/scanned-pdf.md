# Scenario C — Scan PDF + OCR

**Status**: FULL PASS (auto-degraded)
**Date**: 2026-08-05 (OCR chain), 2026-08-06 (E2E re-verified)

## Command

```powershell
ols raw-commit tmp/cli-scenario-c/manifest --output tmp/cli-scenario-c --overwrite
# E2E natural language:
# /ingest skill: "收录这个扫描 PDF"
oks raw-commit .oks/runs/run-e2e-scanpdf-{id}/manifest --overwrite
```

## Input

- **File**: `tmp/pdfs/controlled-chinese-scan.pdf`
- **Size**: 333,717 bytes
- **Pages**: 3
- **Text layer**: empty (scanned Chinese document)
- **Ground truth**: `tmp/pdfs/controlled-chinese-scan-ground-truth.md`

## Providers

1. `pdf-lite` (pymupdf4llm 0.0.27) — auto-detected scan → internal OCR fallback → 3 page records, 696 chars
2. `rapidocr` (rapidocr-onnxruntime 1.2.3) — explicit OCR → 43 bbox records, 432 chars, 8,816ms

## Bundle

- **OCR chain ID**: `bundle:2789f4ffa11d` (from cli-scenario-c/)
- **E2E ID**: `bundle:6700cc16652530c0`

## Evidence

- **Count**: 46 total (3 page-level + 43 bbox-level)
- **Locators**: `kind: page` (pdf-lite) + `kind: bbox` (rapidocr)
- **Degradation chain**: pdf-lite (text layer empty) → internal OCR → explicit RapidOCR

## Completeness

- **Status**: complete (dual OCR evidence complementary, not conflicting)
- **Missing**: none (with RapidOCR installed)
- **E2E without RapidOCR**: partial — needs `oks capability install watch --yes`
- **Known Limits**: Two OCR passes on same pages; bbox coordinates in 200 DPI rendered space

## Commit

`8b28b4c` fix(release): close 6 RC readiness gaps
