# Recipe: Web

source_type: web
description: Public web pages, articles, documentation. Chinese platforms treated separately.

required_capabilities:
  - web.fetch
  - web.extract

optional_capabilities:
  - web.screenshot
  - metadata.fetch
  - image.observe
  - evidence.cross_check

complete_when:
  - main_article_text_extracted
  - title_and_metadata_available
  - challenge_or_paywall_status_recorded

remote_processing:
  policy_required: true

degradation:
  - priority: 1
    capability: web.fetch
    condition: default
    note: "HTTP fetch with SSRF protection."
  - priority: 2
    capability: web.extract
    condition: html_content_available
    note: "Extract main content from HTML. Trafilatura for static; Firecrawl for JS."
  - priority: 3
    capability: web.screenshot
    condition: js_rendering_required
    note: "Browser screenshot when JS execution needed. Requires browser capability."
  - priority: 4
    capability: human.supply
    condition: all_automated_failed
notes: |
  Public web pages: trafilatura for HTML article extraction (local, free).
  Firecrawl for JS-rendered pages and structured extraction (1 credit/call).
  Chinese platforms (zhihu, wechat, bilibili): agentkey is primary provider
  with platform-specific API access. Browser (Chrome CDP) for authenticated
  sessions. AgentKey maturity varies by platform — check provider.yaml.
  Firecrawl ineffective against Chinese anti-bot (CSDN, Juejin, Zhihu all fail).
