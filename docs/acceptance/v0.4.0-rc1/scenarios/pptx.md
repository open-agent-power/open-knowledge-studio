# Scenario F2 — PPTX

**Status**: FULL PASS (partial by design)
**Date**: 2026-08-06

## Command

```powershell
python tests/acceptance/scenario_f2_f3_office.py
# /ingest skill: "收录这个 PPTX" → markitdown → oks raw-commit
```

## Input

- **File**: `tests/acceptance/fixtures/office/acceptance.pptx`
- **Size**: 31,443 bytes
- **Slides**: 4
- **Content**: title slide, capability matrix table, bullet list, chart placeholder

## Provider

- `markitdown` (0.1.6) — document.text.extract

## Bundle

- **ID**: `bundle:43e46e287929819e` (from /ingest skill E2E)

## Evidence

- **Count**: 4 records (one per slide)
- **Locator**: `kind: custom, scheme: pptx-slide, slide: 1-4`
- **Tables**: Capability Matrix table extracted correctly

## Completeness

- **Status**: partial
- **Missing**: `chart.interpret` — Slide 4 chart placeholder cannot be analyzed
- **Impact**: Text content fully available; chart data needs Agent vision or human review

## Commit

`0894a8c` test(acceptance): add JS web, PPTX and XLSX real scenarios
