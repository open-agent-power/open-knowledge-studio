# Raw Plugin 多模态能力集成说明

> 文档状态：Draft for Review
>
> 集成分支：`codex/raw-plugin-integration`
>
> 对比基线：`open-agent-power/open-knowledge-studio@b457899`
>
> Raw 协议：`raw-multimodal/v0.1`
>
> 更新日期：2026-07-16

---

## 1. 文档目的

本文用于帮助代码评审者和自动化分析工具理解本分支相对上游 `main` 的变化，重点回答：

1. 为什么需要多模态 Raw Plugin；
2. 哪些代码被新增或修改；
3. 如何遵守 P5“OKS 提供能力，不包装运行时”；
4. 当前已经验证哪些模态；
5. 哪些结论仍然不能宣称；
6. 合并前需要重点审查哪些接口。

本文不是产品宣传，也不把实验结果描述为生产能力。

---

## 2. 变更摘要

```yaml
change_type: capability_integration
base_commit: b457899c3b681cb9c681289ccc69ce54997d3921
branch: codex/raw-plugin-integration
primary_goal: 将现实世界多模态素材提取为可追溯 Raw Markdown Bundle
orchestrator: agent
capability_registry: settings/handlers.json
adapter_entry: scripts/raw_bundle_adapter.py
raw_contract: raw-multimodal/v0.1
knowledge_generation: false
automatic_correction: false
automatic_grading: false
wiki_write: false
```

本分支增加一套证据丰富的 Level-1 Raw 能力，用于处理：

- 视频；
- 音频；
- 图片；
- PDF；
- PPTX；
- DOCX。

主要产物不是单一 Markdown，而是：

```text
Raw Markdown + metadata + evidence + quality report + source assets
```

该能力只负责提取和打包，不负责：

- 判断内容价值；
- 生成 Wiki；
- 生成知识图谱；
- 自动纠正 ASR/OCR/公式；
- 决定模态；
- 决定调用哪个工具；
- 将 Raw 提升为 Draft。

---

## 3. 与上游 P5 架构的关系

### 3.1 上游约束

上游当前明确：

> Agent is the orchestrator — OKS does not wrap tool calls.

因此，正确调用关系是：

```text
Agent
  ↓ 识别输入模态
settings/handlers.json
  ↓ 选择 Level 0 / Level 1 / Level 2 能力
外部工具或 Raw Adapter
  ↓
raw/
```

### 3.2 本分支的调整

早期实验中曾存在 `scripts/raw_ingest.py`，它同时承担：

- 输入探测；
- 自动选择工具；
- 环境体检；
- 执行提取；
- Bundle 校验。

该入口没有迁移到本集成分支，因为自动输入探测和工具调度与 P5 中 Agent 的职责重叠。

本分支保留并规范化的是：

```text
scripts/raw_bundle_adapter.py
```

Agent 必须显式选择子命令：

```text
watch
watch-result
image
markitdown
mineru
validate
```

`route` 仅保留为开发诊断能力，不是 `/ingest` 的正式编排入口。

### 3.3 当前职责边界

| 层 | 职责 | 不负责 |
|---|---|---|
| Agent / Skill | 模态识别、工具选择、降级顺序、输出目录 | ASR/OCR/PDF 算法实现 |
| `handlers.json` | 能力注册、检查命令、调用模板、输出契约 | 运行时调度 |
| Raw Adapter | 执行指定提取器、格式映射、证据打包、机械校验 | 总结、纠错、评级、知识提升 |
| OKS Recall | 召回 `content.md`，必要时返回 OCR locator | 修改 Raw 证据 |
| Draft / Wiki | 知识筛选、抽象、关系和演化 | 覆盖原始提取记录 |

---

## 4. 文件级变化

### 4.1 上游文件修改

#### `.claude/skills/ingest/SKILL.md`

新增：

- DOCX、PPTX、图片和 evidence-rich PDF 路由；
- `raw-multimodal/v0.1` Bundle JSON envelope 说明；
- Agent 为 Bundle 分配输出目录的规则；
- 显式禁止 Raw Adapter 自行判断模态；
- 明确 Bundle sidecar 不能被丢弃。

保持不变：

- Agent 仍是编排器；
- Raw 后的 A/B/C Triage 仍属于 `/ingest`；
- Draft/Wiki 边界不变；
- 核心 CLI 不增加运行时包装。

#### `settings/handlers.json`

完善现有：

- `oks-video`
- `oks-audio`

新增：

- `oks-image`
- `oks-document`
- `oks-pdf`

每个 evidence-rich handler 声明：

```json
{
  "level": 1,
  "json_protocol": true,
  "output_contract": "raw-multimodal/v0.1",
  "tool_config": "settings/raw-tools.json"
}
```

依赖检查使用参数数组 `check_argv`，执行使用 `command_argv` 或
`command_argv_sequence`，避免把用户路径拼接为 shell 命令字符串。

#### `cli/knowledge_studio/recall.py`

增加 Raw Bundle 感知：

1. 同一 Bundle 的多个 Markdown sidecar 不重复参与普通召回；
2. 优先召回 `content.md`；
3. 查询片段围绕命中词截取，而不是固定只取文件开头；
4. 当正文未命中且名额未满时，可从 OCR evidence 中补充结果；
5. OCR 结果返回 `evidence_id` 和 `locator`。

保持不变：

- 普通 Markdown Raw 的召回行为；
- Wiki 六因子召回；
- Goals、关系和置信度逻辑。

#### `.gitignore`

新增忽略：

- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `.cache/`
- `.agents/`
- `.codex/`
- `settings/raw-tools.json`
- 真实 `raw/**` 生成内容

保留各 Raw 来源目录的 `.gitkeep`。

目的：防止本地模型配置、依赖缓存、Agent 私有状态和真实用户素材进入提交。

### 4.2 新增核心代码

#### `scripts/raw_bundle_adapter.py`

主要能力：

- Raw Bundle v0.1 打包；
- MinerU 结果适配；
- MarkItDown 结果适配；
- Watch 视频/音频结果适配；
- RapidOCR 图片适配；
- PPTX/DOCX 媒体映射；
- 时间戳、页码、bbox 和资产定位；
- `validate` 结构校验；
- Level-1 JSON envelope；
- 机器可读错误输出。

#### `scripts/formula_candidates.py`

主要能力：

- 读取 MinerU 独立公式区域；
- 使用 PP-FormulaNet 生成第二候选；
- 保存页面、bbox、原候选和第二候选；
- `selection_policy` 固定为 `none`；
- 单个公式失败不终止整批处理。

该脚本不会自动选择“正确公式”。

#### `scripts/multimodal_feedback.py`

主要能力：

- 记录真实样本反馈；
- 汇总不同模态的失败类型；
- 维护可复现的反馈日志；
- 不直接修改提取结果。

### 4.3 新增测试

```text
scripts/tests/test_raw_bundle_adapter.py
scripts/tests/test_formula_candidates.py
scripts/tests/test_multimodal_feedback.py
```

同时扩展：

```text
cli/tests/test_recall.py
```

### 4.4 新增配置与依赖清单

```text
settings/raw-tools.example.json
scripts/raw_extract_requirements.txt
scripts/watch_extract_requirements.txt
scripts/mineru_extract_requirements.txt
scripts/formula_extract_requirements.txt
```

大型提取器使用独立 Python 环境，不强制进入 OKS 核心环境。

### 4.5 集成分支验证

在上游最新基线创建的独立工作树中执行：

```text
python -m pytest scripts/tests cli/tests -q
```

结果：

```text
38 passed in 1.01s
```

同时通过：

- `scripts/raw_bundle_adapter.py`、`formula_candidates.py`、`multimodal_feedback.py` 语法编译；
- `settings/handlers.json` 与 `settings/raw-tools.example.json` JSON 解析；
- `python scripts/raw_bundle_adapter.py --version`；
- `git diff --check`；
- 本地路径、GitHub Token 和明文 API Key 扫描；
- `.venv`、测试缓存、Agent 配置、私有工具配置和真实 Raw 产物忽略规则检查。

早期实验分支曾有 54 项测试。本分支未迁移 `raw_ingest` 自动编排和旧 `media_ingest` 人工审批入口，因此相关旧测试也没有迁移；同时新增了 Handler 协议和 JSON 错误边界测试。当前 38 项是本集成边界内的测试集合，不是测试失败后的数量。

---

## 5. Raw Bundle v0.1

### 5.1 目录结构

```text
raw/{YYYY}/{MM}/{DD}/{source}/{capture-id}/
├── raw.md
├── content.md
├── metadata.json
├── evidence.jsonl
├── quality-report.json
├── transcript.md        # 可选
├── document.md          # 可选
├── visual.md            # 可选
└── assets/              # 可选
```

### 5.2 文件职责

| 文件 | 用途 |
|---|---|
| `raw.md` | 人类入口、来源、文件清单和已知限制 |
| `content.md` | 普通阅读和 Recall 的主要正文 |
| `metadata.json` | 来源、哈希、模态、工具版本和状态 |
| `evidence.jsonl` | 带定位信息的原子证据 |
| `quality-report.json` | 覆盖信息、失败项和警告 |
| `transcript.md` | 未经知识加工的字幕或 ASR |
| `document.md` | 文档提取器的结构化结果 |
| `visual.md` | OCR、帧和视觉证据 |
| `assets/` | 原文件、页面图、截图或关键帧 |

### 5.3 Level-1 JSON envelope

成功时：

```json
{
  "status": "ok",
  "contract": "raw-multimodal/v0.1",
  "plugin_version": "0.1.0",
  "bundle": "<absolute-path>",
  "markdown": "<content.md text>",
  "markdown_path": "<absolute-path>/content.md",
  "title": "...",
  "source": "...",
  "modality": "video",
  "metadata": {},
  "validation": {
    "valid": true,
    "evidence_count": 221,
    "errors": [],
    "warnings": []
  }
}
```

失败时：

```json
{
  "status": "error",
  "contract": "raw-multimodal/v0.1",
  "plugin_version": "0.1.0",
  "error_type": "...",
  "error": "..."
}
```

---

## 6. 已实现的模态能力

| 模态 | 提取路线 | 主要证据 | 当前状态 |
|---|---|---|---|
| 视频 | Watch / faster-whisper / frame OCR | 时间戳、帧、OCR bbox | 原型可用 |
| 音频 | faster-whisper | 时间戳、原音频 | 原型可用 |
| 图片 | RapidOCR | bbox、confidence、原图 | 原型可用 |
| PDF | MinerU | 页码、bbox、图片、公式区域 | 普通文本可用，公式需核对 |
| PPTX | MarkItDown + OOXML media mapping | 幻灯片文本、图片资产 | 原型可用 |
| DOCX | MarkItDown + OOXML media mapping | 正文、图片资产 | 原型可用 |

网页和飞书入口已经完成独立端到端实验，但相关 Adapter 仍处于实验状态，本分支暂不将其注册为稳定 Level-1 handler。

---

## 7. 真实样本验证摘要

### 7.1 视频

真实 Java 学习视频：

- 时长约 142 秒；
- 生成带时间戳 ASR；
- 保存视觉证据；
- 形成 221 条 evidence；
- OKS Recall 可命中。

### 7.2 音频

真实 60 秒音频：

- 带时间戳转写；
- 56 条 evidence；
- 原始音频保留；
- 可校验、可召回。

### 7.3 图片

真实图片：

- OCR 文本；
- bounding box；
- confidence；
- 原图资产；
- 154 条 evidence。

### 7.4 PDF

真实 7 页公式 PDF：

- 299 条 evidence；
- 页面与正文 Markdown；
- 页面图片与公式区域；
- MinerU 原候选；
- PP-FormulaNet 第二候选。

### 7.5 Office

- PPTX 图片映射 17/17；
- DOCX 图片映射 6/6；
- Markdown 资产引用可返回对应图片。

### 7.6 网页实验

同一真实网页的对照：

| 路线 | 标题 | 图片 | evidence | 主要问题 |
|---|---:|---:|---:|---|
| HTTP 静态抓取 | 2 | 0 | 68 | 混入页面噪声、结构不足 |
| 浏览器渲染捕获 | 19 | 8 个远程引用 | 91 | 远程图片尚未本地化 |

### 7.7 飞书 Raw Inbox 实验

已经验证：

- 表单提交；
- Base 记录读取；
- 视频和图片附件下载；
- SHA256 往返一致；
- 附件进入 Raw Bundle；
- `validate` 与 `recall` 通过。

未完成：

- Base 状态与摘要回写，当前受资源权限错误 `91403` 阻塞。

---

## 8. 准确度恢复能力

### 8.1 ASR 技术词候选

- 主 ASR：56 个细粒度时间段，但“键盘录入”被识别为“键盘录录”；
- 热词候选：恢复目标词，但时间粒度下降为 3 个大段；
- 策略：保留两个候选，不自动覆盖主时间轴。

### 8.2 OCR 正文区域

- 整屏 OCR：85 个文字块；
- 用户指定 ROI：22 个文字块；
- 噪声块减少约 74.1%；
- OCR 时间约从 5.03 秒降至 3.41 秒；
- 原始整图仍保留，bbox 回映射原图坐标。

### 8.3 屏幕录制关键帧

- 均匀路线：10 帧；
- 屏幕变化路线：检测 26 个区段，保留 11 帧；
- 已证明路线可运行；
- 尚无人工变化点真值，不能宣称召回率提升。

### 8.4 公式第二候选

- 对 MinerU 独立 equation 区域调用 PP-FormulaNet；
- 部分错误公式得到更合理候选；
- 行内公式覆盖仍不足；
- 不进行自动投票或替换。

---

## 9. 已知限制

### 9.1 内容准确性

- ASR 仍有同音词和技术词错误；
- OCR 仍有阅读顺序和 UI 噪声；
- 数学公式不能直接信任；
- 复杂表格、手写内容和多栏论文尚未系统验证；
- 关键帧收益缺少多样本证明。

### 9.2 平台链接

- 已测试的三个 B 站样本没有公开字幕；
- `yt-dlp` 在线请求出现 HTTP 412；
- 本地视频 ASR 回退已验证；
- “B 站字幕直接入 Raw”仍为 blocked；
- 本分支不包含绕过平台访问控制的实现。

### 9.3 部署

- 当前依赖多个隔离 Python 环境；
- 本机开发环境可运行；
- 新机器 bootstrap 尚未完成；
- 不应将本阶段描述为轻量客户端或生产服务。

### 9.4 Raw 边界

Raw 可以粗糙，但必须诚实。当前允许：

- 识别错误；
- 提取不完整；
- 候选之间冲突；
- 处理状态为 partial 或 failed。

当前不允许：

- 静默丢失；
- 伪装成功；
- 自动修改原始候选；
- 将摘要冒充原文；
- 无证据进入 Wiki。

---

## 10. 为什么没有迁移旧的一键入口

本分支有意不包含：

```text
scripts/raw_ingest.py
scripts/tests/test_raw_ingest.py
```

原因不是这些实验代码不可运行，而是其自动探测和调度职责已经由上游 Agent-direct 架构覆盖。

保留一键入口会形成两套编排：

```text
Agent 选择工具
       +
raw_ingest 再次选择工具
```

这会产生：

- 路由规则重复；
- 降级策略不一致；
- `handlers.json` 失去单一事实源地位；
- 核心边界重新向运行时包装扩张。

因此本分支选择：

```text
Agent 只选择一次
Raw Adapter 只执行一次
```

---

## 11. 合并前建议重点审查

### 协议

- `raw-multimodal/v0.1` 是否适合作为官方多模态 Raw 单元；
- JSON envelope 是否需要完整 `markdown`，还是只返回路径；
- `processing_status` 与 CLI `status` 的语义是否足够清晰；
- `evidence.jsonl` locator 是否满足 Draft/Wiki 引用需要。

### 架构

- `handlers.json` 的 `command_argv/command_argv_sequence` 是否符合长期方向；
- 本地解释器路径是否应继续放在 `settings/raw-tools.json`；
- `route` 诊断子命令是否应保留；
- PDF 两阶段命令是否应封装为独立外部 CLI，而不是写在 handler sequence。

### Recall

- Bundle 只索引 `content.md` 是否符合预期；
- OCR fallback 是否应该默认启用；
- locator 是否应出现在统一 Recall Schema；
- evidence 命中是否需要独立权重。

### Repository Hygiene

- 真实 Raw 内容是否全部被忽略；
- 本地路径和 API Key 是否可能进入提交；
- 大模型权重、缓存和生成资产是否被排除；
- 测试 fixture 是否全部为小型合成数据。

---

## 12. 下一步建议

### P0：完成协议评审

优先确定：

1. Raw Bundle 是否进入官方规范；
2. Level-1 JSON envelope；
3. Handler command template；
4. Draft/Wiki 到 evidence 的引用方式。

### P1：完成可复现安装

- 增加跨平台 bootstrap 文档；
- 检查 Python 和 ffmpeg 版本；
- 将独立环境配置模板化；
- 在干净机器执行最小样本；
- 增加 CI 中可运行的无模型单元测试。

### P2：连续真实试用

最小闭环：

```text
真实素材
→ Agent 选择 handler
→ Raw Bundle
→ validate
→ recall
→ 人类确认是否进入 Draft
```

连续使用一段时间后，再根据真实失败频率决定扩展顺序。

### P3：补充真实入口

建议顺序：

1. 网页浏览器主动捕获；
2. 飞书 Raw Inbox 状态闭环；
3. 平台登录态下的用户主动保存；
4. 复杂公式与表格；
5. 更多视频类型的关键帧验证。

### P4：连接知识演化

Raw 稳定后再讨论：

- Draft 如何引用 evidence；
- 多个 Raw 如何形成概念、策略和反模式；
- `confirms/challenges/enriches/supersedes` 如何使用；
- Goals 如何影响召回与进化；
- 人类修正如何保留审计链。

---

## 13. 当前完成度

最准确的状态描述：

> 已完成一套可运行、可追溯的多模态 Raw 原型，并将其按 Agent-direct 原则重组为 Level-1 能力集成；尚未达到生产级全模态解析，也尚未完成跨机器部署和长期真实使用验证。

已经具备：

- 多类本地素材生成 Raw Markdown；
- 结构化 evidence；
- 来源和定位；
- Bundle 校验；
- OKS Recall 联调；
- 真实样本对照；
- 已知失败暴露。

仍需完成：

- 架构接口确认；
- 新环境复现；
- 网页/飞书 Adapter 稳定化；
- 平台入口设计；
- 长期使用验证；
- Raw 到 Wiki 的证据引用闭环。
