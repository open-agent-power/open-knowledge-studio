# Firecrawl Provider

远程网页与文档解析。Office + 英文网页已验证。

## 调用方式

通过 MCP: `firecrawl/scrape` 或 HTTP API `https://api.firecrawl.dev/v2/scrape`

## 输出解析

响应 JSON → `data.markdown` → primary artifact。
`data.metadata.statusCode` → 判断成功/失败。

## 失败处理

- HTTP 4xx → `status: failed`
- 正文 < 100 字符 → `status: partial`，warning "内容可能为反爬页面"
- 超时 → `status: failed`

## 降级

Firecrawl challenge → agentkey (中文平台) → browser → manual
