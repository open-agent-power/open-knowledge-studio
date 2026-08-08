# Scenario D2 — JavaScript Web

**Status**: FULL PASS (partial by design)
**Date**: 2026-08-06

## Command

```powershell
python tests/acceptance/scenario_d2_js_web.py
```

## Input

- **File**: `tests/acceptance/fixtures/js-web/index.html`
- **Type**: JS-rendered page — content appears only after `document.getElementById('content').innerHTML = ...` executes
- **Served via**: local `http.server` on random port

## Providers

1. `http-fetch` — static HTTP GET → raw HTML with empty `<div id="content">`
2. (Recommended fallback): `firecrawl` scrape / `browser` screenshot / `agentkey` web.extract

## Evidence

- **Count**: 1 record (static fetch)
- **Locator**: `kind: dom, xpath_fragment: //div[@id='content']`
- **DOM verification**: Python `html.parser` confirms `<div id="content">` is empty in static response

## Completeness

- **Status**: partial
- **Missing**: `web.extract` — JS rendering required
- **Recommended**: firecrawl scrape, browser screenshot, agentkey web.extract
- **Known Limits**: Static fetch sees script source but not rendered DOM

## Commit

`0894a8c` test(acceptance): add JS web, PPTX and XLSX real scenarios
