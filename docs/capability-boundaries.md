---
title: 能力边界与选型指南
nav_order: 12
---

# 能力边界与选型指南

这不是一张”功能愿望清单”，而是给使用者的选型说明：**现在应装什么、每类来源该走谁、哪些路径已经做过实验、哪些只能按 partial 或 experimental 对待。**

本页以包内的 `knowledge_studio/providers/*/provider.yaml`、`oks capability status --json`、`oks capability status --json`（含 `user_impact` 字段）和已完成的摄入实验为事实源。运行前先执行：

```bash
oks capability status --json
```

它会按你的实际机器、环境变量和 MCP 配置报告哪些能力已经可用；本页的“推荐”不应覆盖该诊断结果。

## 先给结论：推荐给谁、先装什么

### 推荐的 Agent Host

优先使用 **Codex 或 Claude Code**。两者都能读取项目规则、执行 `oks` CLI、读取 Recipe，并在 `/ingest` 路径中完成 Provider 选择、证据填写和 Candidate 编写。

- **只处理本地 Markdown、文本、普通文档**：任一 Agent Host 均可，优先保持本地路径。
- **需要看图、看表、理解复杂版式**：仍使用 Codex 或 Claude Code 的多模态理解，但把其结论标为 `agent_observed`；它不是字符级 OCR 的替代品。
- **不要把 Kimi K3 当作默认必装 Agent 或默认 Provider。** 当前仓库中 K3 是一份已完成的知识案例，尚未以 `provider.yaml` 注册为可自动选择的生产 Provider。见 [Kimi K3 深度分析](cases/kimi-k3-deep-analysis.md)。

### 策略偏好（v0.4 Beta 新增）

首次遇到需要安装新能力时，Agent 会询问你的处理策略，之后自动遵循：

```bash
oks config set strategy lightweight     # 轻量优先：尽量用已有能力，不主动装大型组件
oks config set strategy quality         # 效果优先：优先保证提取完整度
oks config set strategy privacy         # 本地隐私优先：优先本地处理，尽量不上传
oks config set strategy ask_each_time   # 每次询问：没有固定倾向
```

策略保存在 `~/.oks/config.json`，Agent 通过 `oks config show` 读取。每个 Provider 的 `user_impact`（安装量、磁盘、运行时、隐私、费用、跳过后果）通过 `oks capability status --json` 暴露给 Agent，用于向用户解释"为什么推荐这个、资源影响多大"。

### 本地默认组合：隐私优先的用户从这里开始

这是文档、PDF 和公开网页的低成本、可解释组合；不需要 API Key，也不会把源文件上传给远程服务。

```bash
pipx install open-knowledge-studio
oks init my-knowledge-base
cd my-knowledge-base
oks init . --upgrade

# 推荐的两项按需能力
oks capability install pdf-lite --yes   # 文本型 PDF
oks capability install document --yes   # DOCX / PPTX / XLSX / HTML

oks capability status --json
```

开发仓库内安装时，将第一行替换为 `pipx install ./cli --force`。`oks capability install` 会把重依赖放进独立能力环境；不要为了“也许会用”一次性安装所有能力。

### 高成功率推荐组合：允许远程处理时优先启用

如果来源本来就是公开网页或用户明确允许上传到远程服务，**Firecrawl + AgentKey 是当前最值得推荐的两个远程 Provider**：

- **Firecrawl**：公开网页、JavaScript 渲染页面、英文技术资料和远程 PDF 的主力路径。已验证英文博客和 arXiv PDF 的完整抓取，省掉本地浏览器和重型解析依赖。
- **AgentKey**：知乎、微信公众号、B 站等中文平台的专用路径。适合平台 API 能覆盖的来源，调用成本低；遇到实时加密或平台策略变化时仍要保留 partial 并回退人工。

推荐组合不是“所有来源都远程上传”：含隐私、内部资料或禁止远程处理的来源仍走本地 Provider。使用前确认 `policy.remote_processing`，并配置对应 MCP / API 凭据。

### 按来源增配，而不是全装

| 你的来源 | 首选路径 | 需要额外安装或配置 | 何时升级 |
|---|---|---|---|
| `.md` / `.txt` / `.csv` | `text-read`，快速路径 | 无 | 文件很大时分段或人工挑选 |
| 可公开访问的静态网页 | `http-fetch` + `trafilatura` | 通常随核心环境可用 | 页面依赖 JavaScript 或需要高成功率时优先改走 Firecrawl |
| 普通文本型 PDF | `pdf-lite` | `oks capability install pdf-lite --yes` | 需要版面、图片或公式时用 MinerU |
| DOCX / PPTX / XLSX / HTML | `markitdown` | `oks capability install document --yes` | 图表、嵌入媒体和复杂排版需 Agent / 人工复核 |
| 扫描 PDF / 截图 | `rapidocr` + Agent 复核 | `oks capability install watch --yes`；单独管理环境时以 `doctor` 的提示为准 | 中文复杂版面或公式再考虑 MinerU |
| 复杂 PDF、公式、版面还原 | `mineru` | `oks capability install pdf --yes` | 仅在 `pdf-lite` 不够时安装；依赖大、可能耗时很长 |
| 视频、音频、字幕 | `yt-dlp` + `ffmpeg`，必要时 `watch` | `oks capability install watch --yes`；`ffmpeg` 需系统可执行文件 | 需要语音正文时启用本地 ASR |
| 需登录或 JavaScript 网页 | **Firecrawl**；登录态才考虑用户浏览器 | Firecrawl API Key / MCP；或用户 Chrome profile | 不绕过 CAPTCHA、付费墙和 DRM |
| 知乎、微信、B 站等平台 | **AgentKey**；失败时人工补证 | AgentKey MCP / OAuth | 平台反爬、加密或登录要求出现时回退人工 |

## Provider 清单：以运行时状态为准

Provider 会随版本变化。下面是当前版本的能力类型说明，不把条目数量作为产品承诺；
请始终用 `oks capability status --json` 获取本机实际清单和可用性。

`执行方式`说明谁运行它：`agent_native` 是 Agent 自身能力，`managed` 是本机受管理工具，`external` 是远程服务或外部系统，`human` 是人工补证。`状态`来自每个 Provider 的 action maturity，不表示所有输入都能成功。

### 无需额外安装的核心路径

| Provider | 执行方式 / 状态 | 用途 | 推荐与边界 |
|---|---|---|---|
| `text-read` | agent_native / stable | 读取本地 Markdown、纯文本和 CSV | **默认首选。** 直接走 `text_ready=true` 快速路径；不处理二进制格式，大文件可能超出 Agent 上下文。 |
| `agent-runtime` | agent_native / 图片、版式、图表已验证 | Codex / Claude Code 的多模态观察与交叉检查 | 用于语义理解和复核；输出必须标为 `agent_observed`，不能冒充 OCR 或 Provider 原文。 |
| `human` | human / stable | 粘贴正文、上传截图、人工确认 | **合法且推荐的兜底。** 遇到登录墙、反爬、争议来源时优先用它，而不是尝试规避限制。 |
| `http-fetch` | managed / stable | 公开 URL 的安全 HTTP 获取 | 静态网页、PDF、Office 文件的入口；不执行 JavaScript、不处理登录态，且受 SSRF 保护。 |
| `trafilatura` | managed / stable | 从原始 HTML 提取正文、标题、作者和日期 | 与 `http-fetch` 配对处理静态网页；中文平台反爬页可能为空或为垃圾内容。 |

### 文档、PDF 与图片

| Provider | 执行方式 / 状态 | 安装与使用 | 硬边界 |
|---|---|---|---|
| `pdf-lite` | managed / 文本与元数据 stable，结构 validated | `oks capability install pdf-lite --yes` | **PDF 默认首选。** 纯扫描件会降级为 partial；复杂双栏、表格和图片可能丢失。 |
| `markitdown` | managed / 文本 stable，结构 validated_partial | `oks capability install document --yes` | **Office 默认首选。** DOCX、PPTX、XLSX、HTML 转 Markdown；公式、嵌入媒体、复杂版式有损。 |
| `rapidocr` | managed / validated | `oks capability install watch --yes`；独立环境以 `doctor` 提示为准 | 返回文本块与 bbox；手写、复杂版面和阅读顺序不稳定，需 Agent / 人工复核。 |
| `mineru` | managed / 文本、结构、渲染 validated | `oks capability install pdf --yes` | 约 300 MB 以上依赖，可能需要 GPU 或较长时间；只在版面、公式、图片资产确有价值时启用。 |

### 网页与平台内容

| Provider | 执行方式 / 状态 | 安装与使用 | 硬边界 |
|---|---|---|---|
| `firecrawl` | external / 网页获取、正文提取 validated；文档 partial | 配置 `FIRECRAWL_API_KEY` 与 Firecrawl MCP / API | **推荐的动态公开网页主力。** 中文平台可能被反爬；不处理登录态，也不保证 Office 公式或嵌入媒体。 |
| `agentkey` | external / 知乎验证；微信 validated_partial；B 站仅元数据 | 配置 AgentKey MCP 并完成 OAuth | **推荐的中文平台专用 Provider。** 实时微信正文曾返回加密/空内容；必须保留 partial 并回退人工。 |
| `browser` | managed / experimental，当前未独立验收 | 用户已登录的 Chrome Default profile | 可复用用户 Cookie 与页面状态，但**不绕过** CAPTCHA、付费墙或 DRM；当前 Chrome Web Store 扩展路径受阻。 |
| `mediacrawler` | external / experimental，未独立验证 | 用户自行安装 MediaCrawler | 仅公开内容，不能绕过登录墙；小红书、抖音等采集还涉及平台规则与合规风险，**不作为默认推荐**。 |

### 音视频

| Provider | 执行方式 / 状态 | 安装与使用 | 硬边界 |
|---|---|---|---|
| `yt-dlp` | managed / 下载、字幕 validated；元数据 stable | 安装 `yt-dlp`；字幕常还需要浏览器 Cookie；建议同时安装 `ffmpeg` | B 站字幕历史上受 Cookie 限制，YouTube 在部分网络环境不可达；长视频有时间与存储成本。 |
| `ffmpeg` | managed / 探测 stable，音频提取与转码 validated | 系统安装并确保 `ffmpeg` 在 `PATH` | 关键帧提取仍是 experimental；特定编解码器可能另需系统组件。 |
| `local-asr` | managed / validated（12 秒短音频） | `oks capability install watch --yes`，首次运行会下载约 1–3 GB 模型 | 数据不出本机；长音频与中文准确率仍依赖模型和硬件，不能把短样本结论外推。 |
| `remote-asr` | external / experimental | 配置 `OPENAI_API_KEY` 和 OpenAI MCP | 适合没有本地算力的长音频，但会上传数据、产生费用；当前网络受限环境没有完成长音频验证。 |

## 安装分层与推荐组合

### P0：个人知识库默认组合（推荐）

适合研究资料、会议笔记、普通网页、PDF、Office 文档。安装 **Agent Host + `pdf-lite` + `document`** 即可；使用 `text-read`、`http-fetch`、`trafilatura` 处理文本与静态网页。优点是成本低、可离线处理大部分文件、证据边界最清楚。

如果用户允许远程处理，建议在这个本地基线上再配置 **Firecrawl + AgentKey**；它们不是 experimental 的“试试看”，而是当前公开网页和中文平台的推荐增强路径。不要默认安装的仍是 `mineru`、`watch`、`formula`、MediaCrawler、远程 ASR、飞书，因为它们分别有重量、媒体依赖、公式专用、未独立验证、远程成本或协作配置边界。

### P1：多媒体或扫描件用户

在 P0 上增加：

```bash
oks capability install watch --yes
```

再确认系统已安装 `ffmpeg`。扫描件优先用 RapidOCR；需要高保真布局、公式或图片资产时再增加：

```bash
oks capability install pdf --yes
```

### P2：动态网页与登录态用户

- 公开且 JavaScript 渲染的网页：**优先 Firecrawl**，并保存其原始响应到 `work/firecrawl/`。
- 已登录但不含受限内容的页面：用户自己的浏览器会话可以作为实验路径；不要导出或分享 Cookie。
- 微信、知乎、B 站等：先确认用户有权访问；**优先 AgentKey**。遇到加密、登录墙或反爬，要求用户提供正文、截图或手动导出，而不是绕过。

### P3：团队协作与飞书

飞书不是 Capability 安装项，也不再是 `oks` CLI 命令组。需要团队采集和消息审核时，参考
[`examples/feishu-loop/`](https://github.com/open-agent-power/open-knowledge-studio/tree/main/examples/feishu-loop)
的独立脚本，并自行管理 `lark-cli` 与授权。该参考实现不影响本地
`raw → Candidate → 人工审核 → Wiki → recall` 闭环；其本地 lease lock 也**不**提供多机互斥。

## 已完成实验：结果应如何影响选型

下表把历史实验的可复用结论汇总到这里；`complete` / `partial` 描述内容捕获量，不等于事实正确性或生产 SLA。

| 场景 | 组合 | 结果 | 选型结论 |
|---|---|---|---|
| Markdown | `text-read` | complete；全文作为 1 条 evidence | 本地文本就是默认最快路径。 |
| 文本型 PDF | `pdf-lite` | complete；33 页、约 126K 字符 | `pdf-lite` 是学术论文、可复制 PDF 的 P0 首选。 |
| 扫描 PDF | `pdf-lite` 降级 → `rapidocr` | complete；3 页级 + 43 bbox evidence | OCR 可补齐扫描件；未安装 OCR 的同一 E2E 只能 honest partial。 |
| 静态网页 | `http-fetch` + `trafilatura` | complete | 公开静态页面先走本地轻量路径。 |
| JavaScript 网页 | 静态获取；浏览器渲染对照 | 静态路径 partial；浏览器路径能看到完整 DOM | 检测到空 DOM 后升级 Firecrawl / 浏览器，不要把脚本源码当正文。 |
| 动态公开网页 / 英文资料 | `firecrawl` | 英文博客实测约 50K 字符完整；arXiv PDF 实测约 37K 字符完整 | **推荐 Firecrawl。** 中文平台反爬是来源限制，不代表 Firecrawl 的公开英文网页路径不可用。 |
| 视频 | `yt-dlp` + 关键帧 / 弹幕 | partial | 元数据、公开字幕、帧可以入料；B 站常规字幕需要登录，不能声称完整转写。 |
| DOCX | `markitdown` | complete；正文与表格保留 | Office 的默认选项；复杂格式仍需复核。 |
| PPTX / XLSX | `markitdown` / `openpyxl` | partial by design | 文本和表格可用；图表数据、公式计算与视觉排版不是自动保证。 |
| 微信文章 | AgentKey 实时调用 | partial；接口可达但正文可被加密 | 推荐用户手动复制或在自己浏览器中确认内容，保留失败证据。 |
| Kimi K3 报告 | `markitdown` 摄入 6 份官方资料 → Raw → Candidate → Review → Wiki | 已跑通可追溯知识制品闭环 | 证明的是 OKS 的证据到 Wiki 路径，不是对 Kimi API 的独立性能评测。见 [完整报告](cases/kimi-k3-deep-analysis.md)。 |

## 不能模糊的边界

1. **Raw 不是知识。** Provider 原始输出、Agent 观察和人工提供材料都只能先成为可追溯证据；只有人工 accept 才能晋升 Wiki。
2. **可安装不等于可用。** `doctor` 必须通过，Provider 也必须与输入来源、网络、账户权限和合规边界匹配。
3. **外部 Provider 不直接写 Raw。** Agent 必须保存原始响应到 `work/<provider>/`，填写 evidence，并由 `oks raw-commit` 做 provenance 检查。
4. **`partial` 是正确结果。** 缺字幕、空 DOM、加密正文、缺图表或公式时必须如实保留 `partial`、`failed`、`skipped` 或 `environment_limited`，不能把降级路径写成完整成功。
5. **不绕过访问限制。** CAPTCHA、DRM、付费墙、登录墙、平台反爬和个人数据保护是硬边界；优先用户提供材料或获得明确授权的浏览器访问。

## 相关文档

- [核心架构](architecture/oks-core-architecture.md)
- [Agent-Native Ingest 操作手册](ingest/agent-native-ingest-walkthrough.md)
- [Kimi K3 深度分析](cases/kimi-k3-deep-analysis.md)
- [平台反爬、轻量化部署与用户交互研究](https://github.com/open-agent-power/open-knowledge-studio/blob/main/records/research/platform-antibot-and-lightweight-deployment.md)（仓库内研究笔记，未收入本站）
- [远程脱敏治理](security/remote-governance.md)

---

{% include comments.html %}
