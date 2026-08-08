# Scenario F3 — XLSX

**Status**: FULL PASS (partial by design)
**Date**: 2026-08-06

## Command

```powershell
python tests/acceptance/scenario_f2_f3_office.py
```

## Input

- **File**: `tests/acceptance/fixtures/office/acceptance.xlsx`
- **Size**: 6,116 bytes
- **Sheets**: 3 (Metrics, Formulas, Empty)
- **Content**: metrics table with merged cells, formula cells (=B2*C2, =SUM), empty sheet

## Provider

- `openpyxl` — document.text.extract (via direct Python API)

## Evidence

- **Count**: 2 records (one per non-empty sheet)
- **Locator**: `kind: custom, scheme: xlsx-range, sheet: SheetName, range: A1:XX`
- **Formulas**: 3 formula cells preserved as raw expressions; NOT evaluated

## Completeness

- **Status**: partial
- **Missing**: `formula_evaluated: false` — formulas preserved but not computed
- **Impact**: Cell values readable; computed totals need spreadsheet engine
- **Known Limits**: Merged cell ranges preserved; empty sheets correctly skipped

## Commit

`0894a8c` test(acceptance): add JS web, PPTX and XLSX real scenarios
