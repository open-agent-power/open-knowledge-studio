# AgentKey Provider

平台专用远程 API。知乎 full / 微信 partial / B站 metadata_only。

## 调用方式

通过 AgentKey MCP: `find_tools → describe_tool → execute_tool`

## 平台能力

- 知乎: TikHub/fetch_column_article_detail (0.2 credits, ~807ms)
- 微信: TikHub/fetch_article_detail (2 credits, ~3.3s)
- Bilibili: TikHub/fetch_one_video (0.2 credits, metadata only)

## 诚实报告

- full → 正文+锚点通过
- partial → 正文可取但锚点未过
- metadata_only → 只有标题/标识，无正文
- failed → 拒绝 access 或全部空

绝不因 HTTP 200 或 metadata 返回而声称正文成功。
