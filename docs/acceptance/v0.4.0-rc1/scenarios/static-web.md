# Scenario D1 — Static Web

**Status**: FULL PASS
**Date**: 2026-08-05

## Command

```powershell
oks raw-commit tmp/scenario-d/manifest --output tmp/scenario-d --overwrite
# E2E:
# /ingest skill: "收录这个网页"
oks raw-commit .oks/runs/run-e2e-web-{id}/manifest --overwrite
```

## Input

- **URL**: `https://example.com`
- **Access**: public_url
- **HTTP**: 200 OK

## Providers

- `http-fetch` — web.fetch (HTTP GET with SSRF protection)
- `trafilatura` — web.extract (HTML → plain text)

## Bundle

- **E2E ID**: `bundle:ff67a9d764d6a236`

## Evidence

- **Count**: 1 record
- **Locator**: `kind: custom, custom_label: GET https://example.com`
- **Content**: HTML page body, 559 bytes

## Completeness

- **Status**: complete
- **Missing**: none
- **Known Limits**: example.com is minimal — real-world pages may need JS rendering (see D2)

## Commit

`8b28b4c` fix(release): close 6 RC readiness gaps
