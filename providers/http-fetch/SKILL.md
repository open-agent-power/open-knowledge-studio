# HTTP Fetch Provider

安全公网 HTTP GET。SSRF 保护，redirect 跟踪。用于获取原始资源（HTML、PDF、Office 文件等）。

## 调用

Agent 使用当前 Agent Runtime 提供的安全 HTTP GET 工具执行此 Provider；OKS
不提供 `network.py`、`fetch_url()` 或独立 Python API。

- URL 来源：用户提供的 HTTP/HTTPS 地址
- 能力标识：网页采集使用 `web.fetch`，来源落盘使用 `source.fetch`
- 执行前：遵守运行时的 SSRF / 重定向安全边界，不发送凭据、Cookie 或令牌
- 执行后：先把原始响应和 fetch receipt（仅做必要的安全脱敏）保存到当前
  run 的 `.oks/runs/{run_id}/work/http-fetch/`，再交给正文提取 Provider

## 输出

原始 bytes + fetch receipt（final_url, content_type, content_sha256, status_code）。

## 限制

不执行 JS，不处理登录态，中文平台可能被反爬。获取的 HTML 需 trafilatura 或 firecrawl 进一步提取正文。
