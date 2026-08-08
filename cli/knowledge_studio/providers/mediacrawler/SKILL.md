# MediaCrawler Provider

社交平台公开内容采集。需要用户自行安装。

## 前提

MediaCrawler 是外部可选工具，不捆绑进 OKS。

用户需自行安装：
```bash
git clone https://github.com/NanmiCoder/MediaCrawler
cd MediaCrawler
pip install -r requirements.txt
```

## 可用性检测

Agent 应在真正需要时检查 MediaCrawler 是否可用，不得在每次 ingest 开头无意义探测。

检查方式：
- 环境变量 `MEDIACRAWLER_HOME` 指向安装目录
- 或检查已知路径下是否存在 `MediaCrawler/` 目录

## 支持的平台

列在 provider.yaml 的 `platforms` 字段中：小红书、抖音、B站、快手、微博、贴吧、知乎。

各平台成熟度不同：
- 所有平台当前均为 experimental — OKS 集成尚未经过独立验证
- 小红书、抖音：社区报告验证
- B站、知乎：部分功能可用
- 其他平台：experimental

## 用法

Agent 在 `capability_status()` 中看到 mediacrawler 为 `unavailable` 时：
1. 如果当前 Source 来自这些平台且公开 → 使用 Agent Runtime 或 Firecrawl 尝试获取
2. 如果需要评论、搜索、创作者信息 → 向用户说明需要安装 MediaCrawler
3. 只涉及正文 → 优先使用轻量路径，不要求用户安装重依赖

## 限制

- 仅支持公开内容，无法绕过登录墙
- 非 OKS Core dependency，不参与自动化 CI
- 搜索和批量采集功能可能导致平台限流
- OKS 集成尚未经过独立验证 — 所有能力标记为 experimental
