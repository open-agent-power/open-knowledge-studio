# Kimi K3 深度分析

日期：2026-07-30
状态：`active`
OKS 摄入运行：`.codex-tmp/kimi-k3-poc/`

## 速查卡

| 项目 | 值 |
|---|---|
| **模型** | `kimi-k3` |
| **厂商** | Moonshot（月之暗面）/ Kimi |
| **规模** | 2.8T 参数 MoE，单 token 激活 104B |
| **架构** | Kimi Delta Attention、Attention Residuals、Stable LatentMoE（16/896 专家） |
| **上下文** | 1M tokens |
| **模态** | 文本、图片、视频（原生视觉） |
| **API** | OpenAI SDK 兼容；`base_url=https://api.moonshot.ai/v1` |
| **推理** | 思考模式始终开启；`reasoning_effort`：`low` / `high` / `max`（默认） |
| **定价** | $0.30（缓存命中）/ $3.00（缓存未命中）/ $15.00（输出）每百万 token |
| **访问** | 最低充值 $1；按账户等级限流 |
| **开源权重** | 2026 年 7 月 27 日已发布 |
| **arXiv** | `2607.24653` — Kimi K3: Open Frontier Intelligence |

Kimi K3 是月之暗面的旗舰模型，也是首个开源 3T 级模型。目标场景为长程编程、智能体知识工作、推理和多模态任务。在基准测试中，整体落后于 Claude Fable 5 和 GPT 5.6 Sol，但优于其他所有受测模型。其最强的已验证能力是长程软件工程，已公开的案例涵盖 GPU 内核优化、编译器构建和芯片设计。

---

## 1. Kimi K3 是什么

### 1.1 架构与规模

[verified] Kimi K3 是一个 2.8 万亿参数的混合专家模型，单 token 激活约 104B 参数。其三个核心架构组件：

- **Kimi Delta Attention (KDA)** — 混合线性注意力机制，为超长序列上的注意力扩展提供高效基础。[blog:124]
- **Attention Residuals (AttnRes)** — 选择性检索跨深度的表示，而非均匀累积。[blog:124]
- **Stable LatentMoE** — 从 896 个专家中激活 16 个。使用 Quantile Balancing（路由器分位数替代启发式更新）和 Per-Head Muon（注意力头独立优化）来保持此规模的训练稳定性。[blog:126]

[verified] 月之暗面声称这些改进相比 Kimi K2 实现了"整体扩展效率约 2.5 倍的提升"。[blog:46]

[verified] K3 具备原生视觉能力——图片和视频在同一模型内处理，无需独立视觉编码器。上下文窗口为 100 万 token。[blog:30]

[verified] K3 始终运行思考模式（思维链不可关闭）。推理力度可配置——`low`、`high` 或 `max`（默认）——通过顶层 `reasoning_effort` 参数设置。[quickstart:187-189, quickstart:480]

[verified] 模型权重已于 2026 年 7 月 27 日开源发布。[blog:40]

### 1.2 市场定位

[verified] 月之暗面将 K3 描述为"全球首个开源 3T 级模型，专为长程编程、知识工作和推理等前沿智能场景设计"。[blog:30]

[verified] 月之暗面明确表示 K3 "整体性能仍落后于最强大的闭源模型 Claude Fable 5 和 GPT 5.6 Sol"，同时在自身评估套件中"持续优于其他受测模型"。[blog:32]

[verified] K3 取代 K2 系列（2026 年 5 月 25 日停用）成为旗舰。当前模型线为：`kimi-k3`（旗舰）、`kimi-k2.7-code`（专用编程，256K 上下文）、`kimi-k2.6`（上一代，256K 上下文）。[models:103-109]

---

## 2. 能力与证据

### 2.1 编程

编程是 K3 最强的已验证能力。月之暗面在多个公开基准上使用不同 harness（Kimi Code、Claude Code、Codex）进行了评估。[blog:144]

**基准结果**（全部 `reasoning_effort=max`）：[blog:144-165]

| 基准 | K3 成绩 | 竞争背景 |
|---|---|---|
| DeepSWE v1.1 | 67.3（mini-SWE-agent harness） | 排行榜领先开源模型 |
| Terminal-Bench 2.1 | Kimi Code harness 报告 | 可用 harness 中最佳成绩 |
| SWE Marathon | H20 校准分支 | 与 Fable 5、Opus 4.8、Sol 并列评估 |
| KCB 2.0 | Kimi Code + Claude Code 报告 | 内部基准；10% 任务触发 Sol 内容护栏 |

**GPU 内核优化。** [verified] 在受控的 24 小时沙箱测试中，K3 优化了 NVIDIA Hopper GPU 和替代 GPGPU 上的 GPU 内核（AttnRes、KDA、512-head MLA）。K3 "与 Fable 5（含 fallback）竞争持平，大幅优于 Opus 4.8、GPT 5.6 Sol 和 GPT 5.5"。K3 早期版本在开发阶段承担了团队"大部分内核优化工作"。[blog:60-64]

**MiniTriton 编译器。** [verified] K3 从零构建了一个类 Triton 的 GPU 编译器——MLIR 上的自定义 tile 级 IR 层、优化 pass 和 PTX 代码生成管线。"在支持的 roofline 基准上，MiniTriton 性能与 Triton 和 torch.compile 持平或更优——在某些任务上超越 Triton。"该编译器还支撑了 nanoGPT 端到端训练并稳定收敛。[blog:68]

**芯片设计。** [verified] 在单次 48 小时自主运行中，K3 为自研 nano 模型设计了一颗芯片——Nangate 45nm 工艺，4 mm² 面积，100 MHz，8,700+ tokens/s 解码吞吐，146 万标准单元，0.277 MB SRAM，INT4 MAC 阵列含融合反量化——全部使用开源 EDA 工具完成。[blog:78]

**科研编程。** [verified] K3 复现了计算天体物理中的 I-Love-Q 普适关系：审阅并交叉验证 20+ 篇论文，实现了完整数值管线，评估了 300+ 状态方程，识别出已发表公式中的不一致，生成 3,000+ 行 Python 代码，并产出交互式 HTML 仪表盘——实际耗时约 2 小时，而经验丰富的研究人员预估需要 1-2 周。[blog:82-84]

**游戏开发。** [verified] K3 实现了"视觉闭环"——在代码和实时截图之间迭代，精调 3D、前端和交互式输出。[blog:74]

### 2.2 知识工作

[verified] 月之暗面报告称"在源自真实用户-智能体协作工作流的内部评估中"取得了持续提升。[blog:88]

已公开案例包括：[blog:96-106]
- 42 年 AI ASIC 产业研究网站：120+ 轮递归自我改进，2,800+ 次网页搜索，1,100+ 次终端数据拉取，11,000+ 页面，涵盖 87 份季报和 99 份原始 PDF
- GWTC-5 引力波分析：391 个事件，20+ 并发子智能体，7 张可视化图，10+ 篇论文的文献综合
- 核聚变产业报告，含交互式可视化、甘特图、可发表级幻灯片

[verified] K3 可产生信息图风格的演示文稿和可编辑的可视化报告。在 Kimi Work 中，Widgets 和 Dashboard 功能提供了交互式组件和持久的个性化视图。[blog:108-112]

### 2.3 多模态

[verified] K3 具备原生视觉理解能力。视觉输入支持图片（base64 data URI）和视频（通过 `ms://` 协议上传文件）。不支持公开图片 URL——图片必须是 base64 编码或作为文件上传。[quickstart:223-277, quickstart:484]

[verified] 视频编辑案例：K3 从 56 个源素材片段编辑了自身的预告片，处理了"素材筛选、运动匹配剪辑、逐帧节拍同步、音频处理和多轮修改"。预估工作量：资深剪辑师 1-2 个工作日。[blog:120]

[verified] OfficeQA Pro 基准评估 PDF 理解能力时，"所有 PDF 均以图片形式渲染，不提供机器可读文本"。[blog:159]

---

## 3. 如何使用

### 3.1 API 访问

[verified] K3 通过 OpenAI 兼容 API 访问。安装 `openai>=1.0` 后配置：[quickstart:144-158]

```python
from openai import OpenAI
client = OpenAI(
    api_key=os.environ["MOONSHOT_API_KEY"],
    base_url="https://api.moonshot.ai/v1",
)

completion = client.chat.completions.create(
    model="kimi-k3",
    messages=[{"role": "user", "content": "..."}],
)
```

[verified] 关键参数：[quickstart:480-485]
- `reasoning_effort`：`low` | `high` | `max`（默认 `max`）。思考始终开启。
- `max_completion_tokens`：默认 131,072，最大 1,048,576。
- `temperature`、`top_p`、`presence_penalty`、`frequency_penalty`：**固定值**——请求中省略。
- `n`：固定为 1。

### 3.2 功能特性

[verified] **流式输出**：提供独立的 `reasoning_content` 和 `content` 增量。[quickstart:205]

[verified] **结构化输出**：支持 `json_schema` 及 `strict: true`。解析 `message.content`，而非 `reasoning_content`。[quickstart:279-317]

[verified] **视觉输入**：content 必须为对象数组。图片：`image_url` 配合 base64 data URI。视频：通过 `client.files.create()` 上传，以 `video_url` 引用 `ms://<file_id>`。不支持公开 URL。[quickstart:223-277]

[verified] **工具调用**：标准函数调用，支持 `tools` 数组、`tool_choice`（含 `"required"`）和 `tool` 角色消息。返回完整 assistant 消息——部分返回会破坏多轮对话。[quickstart:338-391, quickstart:482]

[verified] **动态工具加载**：通过带 `tools` 字段（不含 `content`）的系统消息在会话中途注入工具定义。[quickstart:394-438]

[verified] **上下文缓存**：自动、前缀式。仅当前一次请求的 prompt token 超过 256 时，新请求才能命中缓存。无需缓存 ID、TTL 或额外参数。保持长前缀（如包含知识库的系统提示词）在多轮请求中不变即可。[quickstart:442-462]

### 3.3 定价与访问

[verified] 统一按量付费，不按上下文长度分级：[blog:137]

| Token 类型 | 每百万 token 价格 |
|---|---|
| 输入（缓存命中） | $0.30 |
| 输入（缓存未命中） | $3.00 |
| 输出 | $15.00 |

[verified] 官方 API 借助 Mooncake 分离式推理架构，在编程工作负载中实现了"90% 以上的缓存命中率"。[blog:137-138]

[verified] 访问需要最低 $1 充值。累计充值金额决定账户等级和速率限制（并发、RPM、TPM、TPD）。[quickstart:137]

### 3.4 Claude Code 集成

[verified] Kimi 提供了在 Claude Code 中使用 K3 的官方指南：`https://platform.kimi.ai/docs/guide/claude-code-kimi`。Anthropic 兼容路径下的模型名为 `kimi-k3[1m]`。[来源：kimi-claude-code-guide]

---

## 4. 局限性

### 4.1 官方确认的局限

[verified] 月之暗面文档中列出了三项局限：[blog:171-175]

1. **对思考历史敏感。** K3 在保留思考历史模式下训练。如果 agent harness 丢弃了历史思考内容，或会话中途从其他模型切换到 K3，生成质量可能变得"高度不稳定"。月之暗面建议使用已验证兼容的 harness（如 Kimi Code），并警告不要中途切换模型。

2. **过度主动。** K3 的训练侧重长程、挑战性任务。结果在遇到小问题或用户意图模糊时"可能替用户做出意料之外的决策"。建议：在边界明确的应用中，通过系统提示词或 `AGENTS.md` 施加明确的行为约束。

3. **与领先闭源模型存在体验差距。** K3 "相比 Claude Fable 5 和 GPT 5.6 Sol 在用户体验上存在可察觉的差距"。[blog:175]

### 4.2 本报告未评估的项

- **延迟与吞吐**——无实测数据。K3 的 2.8T 规模和 MoE 稀疏度（16/896）使推理效率高度依赖部署配置；月之暗面建议"64 个或更多加速器的超级节点配置"。[blog:128]
- **规模化成本**——90% 缓存命中率声明针对"编程工作负载"。知识工作、文档问答和混合工作负载的真实命中率未知。
- **非英文性能**——基准和案例以英文为主。
- **非编程、非知识工作类任务**——创意写作、翻译、简单问答未在公开证据中涉及。
- **安全与内容护栏行为**——KCB 2.0 基准中"10% 任务触发 GPT 5.6 Sol 内容护栏"的备注暗示各模型安全策略存在差异。

---

## 5. 与 OKS 的关联

### 5.1 本报告对 OKS 的意义

本报告作为 OKS 能力测试产出。六份 Kimi/月之暗面官方网页通过 `document` 提取器（MarkItDown）摄入 OKS Raw 包。上述所有 [verified] 声明均可追溯到对应 `extractor-output.md` 文件的具体行号。报告从 Raw 证据编译、经 Candidate 审核、晋升至 Wiki——完整走通了 `Raw -> Candidate -> Human Review -> Wiki -> Recall` 闭环。

这验证了 OKS 能够摄入外部来源、提取结构化证据，并产出可溯源的知识制品——无需人工逐条对照原始网页复核每一项声明。

### 5.2 K3 作为可选远程 Provider

[inferred] K3 对 OKS 的价值在于作为候选远程模型 provider，承担本地部署成本较高的能力：
- PDF 和复杂文档理解（K3 有原生视觉；OfficeQA Pro 基准专门测试了图片渲染 PDF 的理解）
- 视频帧分析和摘要（K3 有原生视频理解）
- Candidate 质量检查（K3 可在人工审核前检查事实一致性和证据覆盖度）
- 公式和图表解读（K3 视觉+推理可处理 LaTeX、图纸、原理图）

[inferred] K3 不应替代证据链中的任何环节。API 输出是证据（需记录 provider/model/hash/timestamp），不是知识。Candidate 与 Wiki 之间的人工审核门槛不变，无论哪个模型辅助提取。

---

## 6. 来源

### 6.1 已摄入 OKS Raw 的来源（本次运行）

| 来源 | URL | Raw Bundle |
|---|---|---|
| Kimi K3 博客 | `https://www.kimi.com/blog/kimi-k3` | `raw/...kimi-k3-blog-e64e4462/` |
| Kimi K3 Quickstart (API) | `https://platform.kimi.ai/docs/guide/kimi-k3-quickstart` | `raw/...kimi-k3-quickstart-a58e290a/` |
| Kimi API Quickstart | `https://platform.kimi.ai/docs/api/quickstart` | `raw/...kimi-api-quickstart-0bf5c0e5/` |
| Kimi 模型列表 | `https://platform.kimi.ai/docs/models` | `raw/...kimi-models-383cbf82/` |
| Kimi 帮助：Agentic Chat | `https://www.kimi.com/help/getting-started/agentic-chat` | `raw/...kimi-help-agentic-chat-13e01cd6/` |
| Moonshot 主页 | `https://www.moonshot.ai/` | `raw/...moonshot-home-b345577a/` |

完整路径位于 `.codex-tmp/kimi-k3-poc/kb/raw/`。

### 6.2 外部验证来源

- arXiv `2607.24653` — Kimi K3: Open Frontier Intelligence（技术报告）
- Kimi 定价：`https://platform.kimi.ai/docs/pricing/chat-k3`
- Kimi Claude Code 指南：`https://platform.kimi.ai/docs/guide/claude-code-kimi`

---

## 7. 方法说明

**有效部分。** 六份来源通过 OKS `document` 提取器（MarkItDown）摄入。提取器输出在文档级别捕获了架构细节、API 参数、基准标注和局限性声明。证据定位器（`extractor-output.md` 中的行号）使声明到来源的溯源成为可能。

**提取器遗漏。** 基准图表、架构示意图和案例截图在原始页面中是图片。MarkItDown 保留了图片 URL 但不转录像素内容。各任务的具体基准分数（超出脚注文本描述的）需参考原始页面或 arXiv 技术报告。

**未测试项。** 本报告撰写期间未对 K3 发起任何 API 调用。延迟、吞吐、输出质量和规模化成本未在本文中实测。本报告是对官方公开声明的综合整理，非独立评测。

**使用的证据标签：**
- `[verified]` — 声明可追溯到摄入 extractor-output 的具体行号或公开可访问的 URL
- `[inferred]` — 基于已验证证据的工程判断，明确标记为"推理解释"
- 未使用任何 `[unverified]` 声明作为结论
