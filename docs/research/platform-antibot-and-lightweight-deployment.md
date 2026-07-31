# 平台反爬与轻量化部署研究

日期：2026-07-30
状态：`active`

目的：记录 OKS 的现实采集路径、竞品功能对照、依赖精简方案。OKS 保留证据和失败状态，不突破平台访问控制。

---

## 一、竞品能力对照：什么不该做

2026 年主流 AI 编程/智能体工具的知识管理能力对比：

| 能力 | Claude Code | Codex | WorkBuddy | Qwen Code | Amazon Q |
|---|---|---|---|---|---|
| 自动跨会话记忆 | 有 | 有 | 有 | 有 | 有 |
| 团队共享记忆 | 有（项目级） | 无 | 有（IMA） | 有（git） | 有 |
| LLM Wiki（raw/wiki） | 第三方 | 第三方 | 内置 | 无 | 无 |
| raw→draft→wiki 闭环 | **无** | **无** | **无** | **无** | **无** |
| 人工审核门控 | **无** | **无** | **无** | **无** | **无** |
| 知识衰减系统 | **无** | **无** | **无** | **无** | **无** |

**结论：OKS 不能再做"又一个 AI 记忆系统"。** 自动记忆、跨会话上下文、文件级 wiki 已是标配。OKS 的差异化在于：审核门控、衰减引擎、证据溯源、跨来源合成。

Claude Code 和 OpenClaw 生态中已有成熟的采集 Skill（Firecrawl、Playwright、Agent Browser、bilibili-to-doc 等），OKS 不应重写自己的提取器来和它们竞争——OKS 是它们的下游，把输出纳入 Raw→draft→wiki 闭环。

---

## 二、分平台能力边界

### 2.1 YouTube

| 维度 | 结论 |
|---|---|
| 官方 API | YouTube Data API v3，10,000 units/天免费配额，可获取元数据、字幕。适合小规模结构化数据 |
| yt-dlp | 支持元数据、字幕提取。2025 年起需 PO Token 插件 + Cookie。成熟方案，但需持续对抗反爬 |
| DRM | YouTube TV 已对部分视频启用 Widevine DRM，限制到 360p。DRM 内容不可下载 |
| 归类 | 元数据/字幕可解决；DRM 是硬边界 |

### 2.2 Bilibili

| 维度 | 结论 |
|---|---|
| 官方 API | 有公开 API，2025 年起强制 Wbi 签名 + buvid3 |
| yt-dlp | 内置 Bilibili 提取器，支持视频/音频/字幕/弹幕。1080P+ 需 Cookie |
| DRM | 付费课程/番剧部分有 Widevine DRM。普通 UGC 视频无 DRM |
| 归类 | 元数据/弹幕/字幕可解决；付费 DRM 是硬边界 |

### 2.3 普通 Web 页面

| 维度 | 结论 |
|---|---|
| 公开页面 | 静态 HTML：requests + BeautifulSoup；JS 渲染：Firecrawl API |
| 反爬 | 2025-2026 主流手段：浏览器指纹、行为分析、CAPTCHA 进化、ML 检测 |
| 工具链 | Firecrawl（Rust 引擎，自动 JS 渲染）、Scrapfly、Bright Data |
| 归类 | 公开页面直接提取 → API Key 可解决；登录页需 Cookie |

### 2.4 PDF 平台

| 维度 | 结论 |
|---|---|
| 数字 PDF | PyMuPDF4LLM（纯 Python，零模型下载，亚秒级）——最轻量首选 |
| 扫描 PDF | Marker-PDF（本地 OCR，需 GPU）或 Firecrawl Fire-PDF（远程，智能分页） |
| DRM | Adobe Adept、Locklizard 等商业 DRM；Calibre + DeDRM 可去除部分 |
| Kindle | 2025 年 Amazon 移除 USB 下载。旧书可用 Calibre + DeDRM；新书唯一方案：截图+OCR |
| 学术论文 | Sci-Hub、arXiv API、Unpaywall、OpenAlex（免费无 Key） |
| 归类 | 数字 PDF 本地轻量可解决；扫描 PDF 可远程化；DRM 不应绕过 |

### 2.5 需登录/付费平台

| 平台类型 | 推荐方案 | 红线 |
|---|---|---|
| 社交媒体 | 官方 API（OAuth/API Key）优先 | 大规模抓取违反 ToS |
| 新闻付费墙 | Archive.ph / Googlebot UA 可绕过软付费墙 | 硬付费墙不可绕过 |
| 企业 SaaS | OAuth 授权优先 | 屏幕抓取可能违法 |
| 电商平台 | 公开商品页可抓取 | 价格/库存 API 有商业方案 |

法律参考：hiQ Labs v. LinkedIn（公开数据抓取不违反 CFAA，但违反 ToS 可触发违约诉讼）；Meta v. Bright Data 2024.1（未绕过认证的公开数据抓取获简易判决支持）。

---

## 三、路由矩阵

| 来源类型 | 推荐路由 | 状态语义 |
|---|---|---|
| 公开文本/Markdown | 直接下载或本地文件 → document 摄入 | 哈希和 Raw 验证通过为 `passed` |
| 普通公开网页 | Firecrawl API → 本地摄入 | 取决于定位器质量 |
| 脚本渲染页面 | Firecrawl API（替代本地 Playwright+Chromium） | 保留稳定内容和来源 |
| YouTube 元数据/字幕 | yt-dlp + PO Token（仅需 Python 3.2MB） | 反爬失败为 `platform_limited` |
| Bilibili 元数据/弹幕 | yt-dlp + Cookie | 不声称可普遍采集 |
| PDF | PyMuPDF4LLM（本地）/ Firecrawl API（远程） | 提取器可用时为 `passed` |
| 需登录/付费/DRM | 用户提供的 OAuth/API/导出 | 无合法路径标记 `restricted` |
| 音频 ASR | Deepgram API（$0.0043/min，替代本地 Whisper 3GB） | API 失败为 `provider_error` |

---

## 四、依赖精简方案

### 4.1 远程 API 替代本地重依赖

| 本地重依赖 | 远程替代 | 成本 | 迁移难度 |
|---|---|---|---|
| 本地 Whisper（1.5-3GB） | Deepgram Nova-3（更便宜更快更准） | $0.0043/min | 低 |
| 本地 Tesseract/PaddleOCR（~500MB） | Firecrawl Fire-PDF / LlamaParse | 免费额度 | 低 |
| 本地 Chromium（~300MB） | Firecrawl API | 500 页/月免费 | 低 |
| 本地 ffmpeg（~80MB） | CloudConvert API | 按分钟 | 中 |
| 本地 PDF 版面（MinerU，重） | PyMuPDF4LLM（纯 Python，无模型） | 免费 | 低 |

Deepgram 比 OpenAI Whisper API 字错率更低（5.26% vs 10.6%），延迟 <300ms 流式，单价更低。PyMuPDF4LLM 仅 `pip install pymupdf4llm`，零模型下载，零外部依赖。

### 4.2 最小 POC 依赖清单

**核心本地（约 150MB Docker 镜像）：**
```
Python 3.12-slim    # 运行环境
yt-dlp              # 视频站点元数据+字幕（3.2MB）
pymupdf4llm         # PDF 文本提取（纯 Python）
```

**POC 阶段全部远程化：**
```
Firecrawl API   # 网页抓取+JS 渲染（500 页/月免费）
Tavily API      # 搜索+发现
Deepgram API    # 语音转文字
LLM API         # 蒸馏/推理能力
```

**仅保留本地（隐私/登录态必需）：**
```
Playwright + Chromium  # 仅需登录态网页时安装
```

最小本地依赖 <150MB，加 Playwright 约 450MB。完整多模态能力（含本地 ASR/OCR/GPU）可选安装。

### 4.3 依赖权重对照

| 能力 | 本地依赖成本 | 轻量替代 | 建议 |
|---|---:|:---:|---|
| 文本/Markdown/文档 | 低 | MarkItDown | POC 首选路径 |
| PDF 版面 | 中到高 | PyMuPDF4LLM（本地）/ Firecrawl API（远程） | 数字 PDF 本地，扫描 PDF 远程 |
| 公式 OCR | 高 | 远程 OCR/视觉模型 API | 可选；显式 CLI 暴露后再安装 |
| 视频/音频 ASR | 高 | Deepgram API / 官方字幕 API | 远程优先；如实记录失败 |
| 图片 OCR | 中 | 远程视觉模型 API | 视任务而定 |
| 飞书 | 本地低，管理配置高 | 运行时凭据 + 专用多维表格 | 仅可选控制面 |

### 4.4 容器化

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir yt-dlp pymupdf4llm
# 150MB 镜像，可处理：网页、YouTube 元数据/字幕、PDF、本地文件
```

n8n（150MB Docker 镜像）作为编排层——调度、错误处理、重试、执行历史。整个知识流水线可在 $5/月 VPS 上用两个容器跑起来。

---

## 五、飞书 CI 评估

飞书 CI 当前由 `scripts/feishu_base_worker.py`（2,384 行）驱动，被设计为完全可选扩展——核心引擎（`raw_bundle_adapter.py`、`store.py`、`recall.py`）对飞书零引用。

已知问题：
- 身份碎片化（user vs bot 模式字段不同，部分 API 只能 user 模式）
- 权限审批异步无反馈
- 不支持删除触发器
- 工作流定义在 Web UI 中，无法版本控制
- 供应商锁定，无社区生态

决策框架：闭环验证完成前不投入更多精力在飞书 CI 上。若闭环跑通且效率 OK，再评估飞书 CI 价值。

---

## 六、OKS 实现边界

OKS 应负责：
- 路由规划、能力安装提示
- Raw Bundle 证据、Candidate/Wiki/审核生命周期
- 召回和评估报告
- 证据溯源和衰减管理

OKS 不应负责：
- 平台反爬绕过、DRM 规避、付费墙穿透
- 自建下载器生态
- 每个重型模型的本地副本
- 与 Firecrawl/yt-dlp/Deepgram 等成熟工具竞争提取能力

---

## 参考文献

- YouTube Data API：https://developers.google.com/youtube/v3
- yt-dlp：https://github.com/yt-dlp/yt-dlp
- Bilibili 开放平台：https://openhome.bilibili.com/
- Firecrawl API：https://firecrawl.dev
- Deepgram Nova-3：https://deepgram.com
- PyMuPDF4LLM：https://pypi.org/project/pymupdf4llm/
- Moonshot/Kimi API：https://platform.moonshot.ai/docs
