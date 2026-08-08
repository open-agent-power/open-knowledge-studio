# Scenario G — AgentKey Live API Call

**Status**: FULL PASS (partial by design)
**Date**: 2026-08-06

## Command

```powershell
oks raw-commit tmp/cli-scenario-g/manifest --output tmp/cli-scenario-g --overwrite
```

## Input

- **URL**: `https://mp.weixin.qq.com/s/TzspFuGyorXlaDQhtiZsqQ`
- **Platform**: WeChat MP article
- **Access**: authenticated_remote (via AgentKey → TikHub/wechat_mp_v2)

## Provider

- `agentkey` (TikHub/wechat_mp_v2) — web.extract
  - **Cached experiment** (scenario_g.py): HTTP 200, 3,289ms, 2 credits ($0.01), 2,326 chars readable
  - **Live call** (scenario_g_live.py): 2026-08-06T02:08:07Z, HTTP 200, 1,458ms, 2 credits ($0.01), content encrypted/empty

## Bundle

- **ID**: `bundle:37c59b5a` (live call evidence)

## Evidence

- **Count**: 1 record (API-level metadata)
- **Locator**: `kind: custom`
- **Content**: API response metadata proving reachability

## Completeness

- **Status**: partial
- **Missing**: WeChat MP content encrypted — anti-scraping active on real-time calls
- **Impact**: Cached data shows the API path works; real-time calls face WeChat anti-scraping
- **Failure_disposition**: `needs_user_action`
- **Recommended**: Human copy-paste or browser-based access as fallback

## Known Limits

- WeChat MP actively encrypts content on some API calls
- AgentKey maturity for WeChat: `validated_partial`
- Title anchor verification can fail due to hidden punctuation normalization

## Commit

`8b28b4c` fix(release): close 6 RC readiness gaps
