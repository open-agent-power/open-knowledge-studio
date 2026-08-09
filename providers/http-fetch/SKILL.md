# HTTP Fetch Provider

安全公网 HTTP GET。SSRF 保护，redirect 跟踪。用于获取原始资源（HTML、PDF、Office 文件等）。

## 调用

```text
provider: http-fetch
action: source.fetch
url: https://example.com/article
```

The Agent selects an installed HTTP provider for this action. This Skill does
not import the removed legacy `network` module or provide a standalone Python
API.

## 输出

原始 bytes + fetch receipt（final_url, content_type, content_sha256, status_code）。

## 限制

不执行 JS，不处理登录态，中文平台可能被反爬。获取的 HTML 需 trafilatura 或 firecrawl 进一步提取正文。
