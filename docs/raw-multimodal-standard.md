---
title: Raw 多模态标准
nav_order: 22
parent: 参考
---
# Raw 多模态录入核心标准

> 状态：第一阶段规范 v0.1
>
> 更新日期：2026-07-14
> 适用范围：现实世界数字内容进入 Open Knowledge Studio 的 `raw/` 之前和落盘时

## 1. 目标与边界

本标准只解决一个问题：

> 将网页、文档、图片、音频和视频等现实来源，转换为可追溯、可召回、可继续加工的 Raw 材料。

Raw 是提取层，不是知识层。Raw 可以包含机器错误和不确定结果，但不得把摘要、观点归纳、知识关系、术语润色或 Wiki 结论伪装成原始事实。

标准流程：

```text
Source
  → Acquire（取得可处理的数据）
  → Inspect（探测实际模态）
  → Route（生成解析计划）
  → Extract（成熟工具提取）
  → Validate（检查覆盖与损失）
  → Package（统一 Raw 包）
  → Recall Check（验证可召回）
  → 后续 /ingest → drafts → 人工 /promote → wiki
```

第一阶段不做：

- 自动总结、自动生成 Wiki 或知识图谱；
- 自动修正 ASR、OCR 和公式；
- 自研 OCR、ASR、文档解析或视觉模型；
- 为所有平台构建抓取器；
- 决定最终产品必须是浏览器扩展、飞书机器人、SaaS 或桌面客户端。

## 2. 不可破坏的原则

### 2.1 Raw 不是知识

Raw 保存来源、机器提取结果和证据定位。任何抽象、判断和融合都进入 Draft 或 Wiki 阶段。

### 2.2 不允许静默丢失

无法提取的内容必须写入质量报告。系统可以失败，但不得在未警告的情况下跳过页面、时间段、图片、表格、公式或附件。

### 2.3 所有内容必须可追溯

每个证据单元至少包含：

```text
内容 + 原始来源 + 定位信息 + 提取方法 + 质量状态
```

### 2.4 优先复用成熟项目

成熟工具负责下载、字幕、ASR、OCR、关键帧和文档解析。Agent 根据 `settings/handlers.json` 负责来源识别与模态路由；Raw Plugin 只负责执行明确指定的提取路线、格式映射、机械校验和 OKS 接入。

### 2.5 Markdown 不是唯一载体

Markdown 是人类入口和召回文本，不适合无损承载坐标、置信度、复杂布局和媒体证据。因此 Raw 是“Markdown + 结构化证据 + 必要资产”，不是强行把一切压进一个文件。

普通召回优先索引多模态Raw包的 `content.md`。`evidence.jsonl`、完整逐字稿、视觉副本和质量报告是按需回查的sidecar，不与人类可读内容竞争召回排序；当正文没有命中且结果名额未满时，召回层可用带坐标的OCR原子证据补位。

## 3. Raw 分类：目录轴与模态轴分离

继续保留上游的日期与来源目录，不按平台无限扩张：

```text
raw/
└── {YYYY}/{MM}/{DD}/
    ├── articles/   # 网页、公众号、图文内容
    ├── papers/     # 论文和研究文档
    ├── videos/     # 视频来源
    ├── audio/      # 音频来源
    ├── repos/      # 代码仓库材料
    └── misc/       # 图片、对话及其他来源
```

平台、文件格式和实际模态写入元数据，而不是继续增加 `bilibili/`、`douyin/`、`pdf/` 等顶层目录。

一个来源可以同时包含多种模态：

```yaml
source_type: video
platform: bilibili
modalities:
  - speech
  - slide
  - on_screen_text
route:
  - platform_caption
  - asr
  - keyframe
  - ocr
```

## 4. 统一 Raw 包

复杂来源以日期/来源目录下的一个 capture 目录保存：

```text
raw/{YYYY}/{MM}/{DD}/{source}/{capture-id}/
├── raw.md
├── content.md
├── metadata.json
├── evidence.jsonl
├── transcript.md
├── document.md
├── visual.md
├── quality-report.json
└── assets/
```

文件按实际提取结果存在，不要求每个包包含全部文件。

| 文件 | 职责 |
|---|---|
| `raw.md` | 人类可读入口、来源、提取物清单和已知限制 |
| `content.md` | 普通阅读与召回入口；只做合段、去重、排序和证据编排，不做总结或概念抽取 |
| `metadata.json` | 来源、哈希、平台、模态、路由、工具版本和处理状态 |
| `evidence.jsonl` | 机器可读的原子证据与定位 |
| `transcript.md` | 平台字幕或未经润色的 ASR |
| `document.md` | PDF、Word、PPT、网页等结构化正文 |
| `visual.md` | OCR、关键帧和视觉提取结果 |
| `quality-report.json` | 覆盖率、失败项、警告和人工回退要求 |
| `assets/` | 必要图片、关键帧、附件或原始证据片段 |

简单文本来源允许只保存一个带 frontmatter 的 Markdown 文件。

## 5. 最小元数据协议

```json
{
  "schema_version": "raw-multimodal/v0.1",
  "capture_id": "20260714-example-ab12cd34",
  "source": {
    "url": "https://example.com/source",
    "local_path": null,
    "platform": "bilibili",
    "title": "示例标题",
    "author": "示例作者",
    "collected_at": "2026-07-14T10:00:00+08:00",
    "source_url_sha256": "...",
    "content_sha256": "...",
    "content_hash_status": "verified"
  },
  "source_type": "video",
  "modalities": ["speech", "slide", "on_screen_text"],
  "route": ["platform_caption", "asr", "keyframe", "ocr"],
  "extractors": [
    {"name": "watch-skill", "version": "1.0.0"}
  ],
  "processing_status": "partial",
  "review_status": "pending"
}
```

`processing_status` 取值：`complete`、`partial`、`failed`。`partial` 不等于不可用，但必须在质量报告中说明缺失。

URL指纹和内容指纹不得混用：`source_url_sha256`只标识链接字符串；只有提取时实际取得媒体字节，才能填写`content_sha256`并将`content_hash_status`设为`verified`。无法取得媒体内容时，`content_sha256`为`null`，状态为`unavailable`。

## 6. 原子证据协议

视频或音频：

```json
{"kind":"speech","text":"多元函数的一阶偏导数","locator":{"start":755.2,"end":759.8},"method":"faster-whisper","confidence":0.81}
```

PDF或文档：

```json
{"kind":"text_block","text":"正文内容","locator":{"page":12,"bbox":[82,140,510,186]},"method":"pdf-text-layer"}
```

图片或关键帧：

```json
{"kind":"ocr","text":"整体代换 + 洛必达","locator":{"asset":"assets/frame-0031.jpg","bbox":[120,80,650,210]},"method":"rapidocr"}
```

最低定位要求：

| 来源 | 定位信息 |
|---|---|
| 视频、音频 | `start`、`end` |
| PDF | 页码；可用时增加 `bbox` |
| Word | 标题路径、段落序号 |
| PPT | 幻灯片页码、元素区域 |
| 网页 | URL、标题；可用时增加 DOM/段落定位 |
| 图片 | 资产路径；OCR增加 `bbox` |
| 代码 | 仓库、文件路径、提交或行号 |

## 7. 模态探测与路由

路由依据内容实际承载的信息，不只看扩展名或平台。

### 7.1 文本与网页

```text
静态正文/DOM → 正文提取 → Markdown
动态或登录页面 → 浏览器登录态/页面适配器 → 正文与资产
```

保留标题、作者、发布时间、原始 URL、引用和图片位置。提取失败时保留页面快照或失败原因。

### 7.2 PDF、Word、PPT

```text
原生文本层 → 结构解析
扫描页/图片元素 → OCR
表格/公式/图示 → 专用解析或保留页面图片
```

原生文本层优先于 OCR。PPT 动画、修订记录、批注、复杂公式等无法可靠还原时必须明确报告。

### 7.3 图片

```text
OCR → 文字证据
版面/图表/示意图 → 视觉理解（可选）
原图 → 必要证据资产
```

### 7.4 音频

```text
已有逐字稿 → 直接解析
无逐字稿 → ASR
多人内容 → 可选说话人分离
```

保留分段时间戳。方言、噪声、重叠语音和专业词错误写入质量报告。

### 7.5 视频

按信息密度选择路线：

| 视频类型 | 默认路线 |
|---|---|
| 口播 | 字幕优先；无字幕则音频 ASR |
| PPT/教学 | 字幕或 ASR + 关键帧 + OCR |
| 编程录屏 | ASR + 屏幕变化帧 + OCR/代码证据 |
| 操作演示 | 关键帧/片段 + 视觉理解 + 可选 ASR |
| 混合视频 | 多路线并行，不允许只保留单一路径 |

平台链接获取顺序：

```text
字幕/文本接口
  → 公开媒体 URL
  → 用户授权的浏览器登录态或 Cookie
  → 临时音频/视频流
  → 本地文件回退
```

存在字幕时不下载视频；只需要语音时只获取音频；需要画面证据时才获取低清视频流或必要片段。临时媒体完成提取后可删除，Raw长期保留Markdown和必要证据资产。

## 8. 信息损失控制

1. **保留独立结果**：平台字幕、ASR、OCR和视觉描述不互相覆盖。
2. **原始优先**：原生文本层优先于OCR，人工字幕优先于自动字幕，自动字幕优先于ASR。
3. **多路交叉**：高风险内容允许字幕+ASR、文本层+OCR、ASR+关键帧并行。
4. **不可变提取**：Raw阶段不自动润色机器结果；修正必须生成独立记录并注明依据。
5. **证据回链**：每段文本能回到页码、时间戳、坐标、原文件或原URL。
6. **失败可见**：任何未处理页面、时间段、附件和模态都进入质量报告。
7. **保留难以文本化的资产**：公式、图表、代码变化、动作和布局不能可靠转写时保留截图或片段引用。

## 9. 质量报告与评价指标

每次处理至少报告：

- 来源是否完整、是否需要登录；
- 文件或媒体时长、页数、尺寸和哈希；
- 实际检测到的模态和执行的路由；
- 字幕、ASR、OCR、文档解析的执行状态；
- 文本、时间、页面和资产覆盖情况；
- 定位信息覆盖情况；
- 不支持或低可信的内容类型；
- 提取耗时、失败原因、重试和人工回退建议。

第一阶段先建立基线，不用未经测试的固定准确率包装能力。重点指标：

| 指标 | 含义 |
|---|---|
| source completeness | 来源、作者、时间、哈希是否齐全 |
| content coverage | 页数、时长、正文块是否被覆盖 |
| locator coverage | 证据是否具有页码、时间戳或坐标 |
| extraction fidelity | 抽样人工核对后的字符、术语、表格、公式质量 |
| coverage checks | 提取器声明的实际输出数量与Raw实际打包数量逐项比对 |
| route correctness | 模态探测是否选择了合理解析路线 |
| runtime and cost | 每分钟媒体、每页文档的耗时和资源成本 |

## 10. 能力声明边界

本项目不声称“无损解析现实世界的一切”。目标是：

> 对主流数字内容进行可追溯的多模态提取；无法可靠文本化的部分保留原始证据，并明确报告信息损失。

当前真实基线已覆盖本地视频、公开B站URL、数字PDF、扫描PDF、PPT和独立截图：

- 视频可产出时间戳ASR、去重证据帧和逐帧OCR；
- 公开B站URL可由成熟工具直接获取元数据和低清画面，无需用户手工下载；
- PDF可保留页级结构、公式识别结果和图片资产；
- PPT的文本和页边界可轻量提取；
- 独立截图由RapidOCR直接生成文字、坐标和原图证据；复杂图表语义仍未覆盖。

这些样本同时证明了限制：专业术语和数学公式存在识别错误；公开平台未登录时可能拿不到字幕；视觉重复内容可能只保留一帧；PPT图片资产仍需单独打包；Word、多人音频、登录态平台和动态网页尚未完成真实样本验证。

## 11. 第一阶段样本矩阵

用户和开发者共同提供具有合法访问权限的真实素材；不要求一次提交全部样本。

| 类别 | 最少样本 | 重点验证 |
|---|---:|---|
| 网页/公众号 | 3 | 正文、图片、动态/登录态 |
| PDF | 3 | 数字版、扫描版、公式/表格 |
| Word/PPT | 3 | 层级、表格、图片、页面定位 |
| 图片 | 3 | 截图、手写、图表 |
| 音频 | 3 | 口播、多人、噪声 |
| 视频 | 3 | 口播、教学、编程/操作 |
| 平台链接 | 3 | 公开、登录态、无字幕 |

生产录入时，每个样本由提供者补充：保存原因、希望保留的关键信息、是否允许临时下载或云端处理。纯技术基准样本允许省略这些语义信息，但元数据必须显式写入 `benchmark: true`、`human_context: omitted` 和 `purpose: multimodal_pipeline_evaluation`，不得把缺失误认为已经确认。

开发侧记录预期信息是否被提取、是否可定位、是否有静默丢失、是否能被OKS召回。

## 12. 第一阶段完成条件

第一阶段完成不等于所有输入100%准确，而是：

1. 输入本地文件或受支持URL后，可自动探测模态并生成路由计划；
2. 成熟提取器的结果可以统一落成Raw包；
3. 成功提取的证据全部可定位；
4. 未成功提取的内容全部可解释，无静默丢失；
5. 临时媒体与长期Raw资产边界清楚；
6. Raw Markdown能被现有OKS召回；
7. 同一解析核心以后可被CLI、Skill、浏览器扩展、飞书机器人或云服务调用。

## 13. 工具选型规则

新增工具必须同时满足：

- 有明确真实样本缺口；
- 开源成熟或有稳定服务接口；
- 能输出中间结果和来源定位；
- 失败时仍能保留部分提取物和原因；
- 能映射到本标准的Raw包；
- 不要求修改上游 `raw → drafts → wiki → recall` 主流程。

候选工具只作为可替换实现，不写入标准本身的强依赖：视频可使用Watch Skill、BiliNote、yt-dlp等组合；文档可评估MinerU、Marker、MarkItDown等；OCR和ASR优先复用成熟引擎。

## 14. 与上游知识生命周期的关系

本标准终止于Raw可用和召回验证。后续严格遵循Open Knowledge Studio原流程：

```text
Raw提取包
  → /ingest：Agent做A/B/C分级
  → A级进入drafts/
  → 人工审查
  → /promote进入wiki/
  → 6因子召回、衰减、enriches/confirms/challenges/supersedes
```

多模态录入不改变Wiki的概念、策略和反模式设计，也不绕过人工审批门。

## 15. 当前可运行入口

Level-1 能力由**独立安装的** `oks-connector` 包提供，入口为其 `oks-raw-bundle`
命令行（见该包 README）。它**不在** OKS 主仓库的 `cli/` 或 `scripts/` 内 —— 按
A1/P5，L1 工具是独立版本化、独立安装的能力，而非主仓库脚本。Agent 必须先读取
`settings/handlers.json`、明确选择模态和子命令，再调用该 Adapter。插件不承担自动
模态探测、跨工具调度、摘要、纠错、评级或知识提升。

各模态的隔离解释器路径写入未跟踪的 `settings/raw-tools.json`，格式参考
`settings/raw-tools.example.json`。示例：

```powershell
# 仅用于开发诊断；正式 /ingest 路由由 Agent 完成
oks-raw-bundle route "D:\sample\lesson.mp4"

# 使用Watch Skill环境执行视频提取并直接生成Raw包
oks-raw-bundle watch "D:\sample\lesson.mp4" `
  --source-file "D:\sample\lesson.mp4" `
  --output "raw\2026\07\16\videos\lesson" `
  --max-frames 12

# 运行MarkItDown并生成Office Raw包；也可用--markdown打包已有结果
oks-raw-bundle markitdown "D:\sample\slides.pptx" `
  --output "raw\2026\07\16\papers\slides"

# 打包已有MinerU结果
oks-raw-bundle mineru "D:\mineru-output" `
  --source "D:\sample\paper.pdf" `
  --output "raw\2026\07\16\papers\paper"

# 使用RapidOCR环境提取独立图片
oks-raw-bundle image "D:\sample\screenshot.png" `
  --output "raw\2026\07\16\misc\screenshot"

# 所有包进入raw/前必须通过结构和证据校验
oks-raw-bundle validate "raw\2026\07\16\videos\lesson"
```

每次成功提取都会向标准输出返回 `raw-multimodal/v0.1` JSON envelope，其中包含 Bundle 路径、`content.md`、元数据和校验结果。`watch` 命令应使用已安装 Watch Skill 的 Python 环境执行；`markitdown` 命令应使用已安装 MarkItDown 的环境执行。提取器缺失时命令返回机器可读错误，不会自动安装或切换到未声明实现。
