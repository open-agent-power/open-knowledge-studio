---
title: 术语表
nav_order: 3
parent: 工作原理
---

# 术语表

OKS 的文档会同时谈到 Agent、工具、知识对象和处理状态。它们属于不同层，不能互相替代。用户决定目标并审核 Candidate，Agent 理解任务和材料，OKS 负责保存、校验、查询和记录。

## 运行环境

| 词语 | 含义 |
|---|---|
| Agent | 当前执行任务的主体，例如 Codex 或 Claude。Agent 阅读材料、选择工具、整理 Candidate，并判断 Recall 结果是否适用于当前任务。Agent 不是 OKS，也不会因为安装了 OKS 就自动开始工作。 |
| Host | 运行 Agent 的应用或环境。Host 决定怎样发现和加载 Skill，是否支持 Hook，以及能向 Agent 提供哪些会话信息。 |
| OKS CLI | `oks` 命令行工具。它创建 Instance、保存和校验文件、记录审核决定、执行 Recall。CLI 不理解材料，也不替用户作审核决定。 |
| Studio | OKS 的本地网页界面。它用于浏览和编辑知识库、审核 Candidate、查看调用记录及评测结果。Studio 不是 Agent，页面操作也不会自动完成 Agent 任务。 |
| Hook | Host 在特定事件发生时调用的程序接口。OKS Hook 可以在提交问题时执行 Recall，或在工具调用后检查文件冲突。安装 Hook 只表示接口已经配置，不能证明某次调用成功。 |
| Session | Host 中的一次 Agent 会话。Session 的创建、持续时间和上下文由 Host 管理，不是 OKS Mail 对象。新 Session 只有连接同一个 Instance 并重新读取记录，才能继续之前的工作。 |
| Mail Thread | OKS Mail 中围绕同一主题串联的一组消息。Thread 保存发送、回复和回执关系，不会创建 Host Session，也不能证明接收方已经执行消息中的任务。 |

## 知识库和来源

| 词语 | 含义 |
|---|---|
| Instance | 一套独立的 OKS 知识库目录，包含个人或团队自己的 Raw、Candidate、Wiki、Profile、配置和记录。安装 OKS 工具不会自动创建个人知识，切换 Instance 也不需要复制 OKS 源码。 |
| Source | 本次收录要处理的原始来源，例如文件、网页、仓库、对话或媒体。Source 指材料本身或它的位置，不等于已经保存的 Raw，也不等于关联知识源。 |
| Source Envelope | `oks ingest prepare` 为一次 Source 生成的来源说明。它记录来源位置、访问方式、采集者、时间、内容指纹和处理策略，但不保存证据正文。 |
| Recipe | 针对一种材料类型的处理要求。Recipe 列出需要或可选的能力、降级顺序和 `complete_when` 条件，用来判断 Evidence Manifest 是 `complete` 还是 `partial`。它不判断来源内容是否正确。 |
| Provider | 获取或处理某类 Source 的能力实现，例如网页抓取、PDF 解析、OCR 或字幕提取。Provider 返回实际处理结果，Agent 再把这次尝试记录为 Evidence Fragment。Provider 不是知识来源，也不决定材料中的说法是否正确。 |
| Connector | 随 OKS 发布的采集与格式转换组件。`oks ingest run` 可以调用它处理支持的来源。Connector 负责机械处理和记录状态，不会替 Agent 提出 Candidate，也不会审核 Wiki。 |
| 关联知识源 | 通过 `oks sources link` 注册的只读 Git 知识库。OKS 从指定提交读取已提交的文件，不把它复制进当前 Instance。关联知识源与 Ingest Provider 是两种不同配置。 |

## 收录对象

| 词语 | 含义 |
|---|---|
| Evidence Fragment | 一次 Provider 或 Agent 运行产生的证据片段。它记录产物、证据定位、模态、处理状态和产生方式。多个 Fragment 可以描述同一个 Source。 |
| Evidence Manifest | Agent 合并多个 Evidence Fragment 后提交的证据清单。它声明总体证据是否完整，并列出主要产物、证据记录、步骤和来源关系。`oks raw-commit` 会校验清单与实际文件是否一致。 |
| Raw Bundle | `oks raw-commit` 根据 Source Envelope、Evidence Manifest 和产物文件生成的标准材料包。Raw Bundle 保存证据和处理记录，不会自动生成 Candidate 或 Wiki。 |
| Raw | `raw/` 中的来源、原文、提取结果和处理记录。Raw 用于回到证据核对内容。保存 Raw 不表示来源中的说法正确。`raw/executions/` 等目录保存执行记录，不属于普通材料查询。 |

## 知识对象

| 词语 | 含义 |
|---|---|
| Candidate | 等待用户审核的提议，通常保存在 `drafts/`。CLI 将相关命令命名为 `oks drafts`，部分界面会显示 Draft。Candidate 可以来自材料、反馈或任务记录，审核前不能当作已经采用的知识。 |
| Wiki | `wiki/` 中的知识页。Candidate 经审核并 Promote 后会生成带审核证据的 Wiki。直接创建的页面、取消归档的页面和旧页面可能处于 `provisional`，因此文件位于 `wiki/` 不能单独证明它已经审核。 |
| Profile | 用户、项目或 Agent 的相对稳定背景，例如职责、偏好和项目范围。Profile 为任务提供背景，不是 Raw 到 Wiki 的中间状态。 |
| Goal | 当前任务的目标、范围和验收条件。编辑 Goal 只是在保存任务定义，不表示任务已经执行。 |
| Discussion（讨论记录） | 对问题、判断和未确定事项的记录，通常保存在 `profiles/discuss/`。讨论可以引用 Goal、Raw 或 Wiki，引用本身不能证明相关步骤已经执行。Studio 中的界面名称是“讨论”。 |
| Trace | 命令或工作流明确写下的执行事件，例如步骤、结果、错误和阻塞。Trace 不是 Agent 的完整思考过程。没有记录的事件不能从目录名或页面结构中补猜。 |

## 两类 Skill

| 词语 | 含义 |
|---|---|
| Host Skill | 安装到 Host 可发现位置的操作说明，例如全局或项目内的 `oh-my-oks`。Host 加载后，Agent 才能按这些说明调用 OKS。加载 Skill 不表示其中的步骤已经执行。 |
| 知识库管理的 Skill | 由当前 Instance 保存、审核、检索和按版本加载的 Skill 知识。`oks skills import` 会先生成 Candidate，`oks skills search` 只检索符合条件的已审核版本，`oks skills load` 才读取指定版本；只有显式提供 `--target` 时才会复制到 Host。 |

## 常见动作

| 词语 | 含义 |
|---|---|
| Ingest | 获取 Source，保存证据、产物和处理状态。一次 Ingest 可以只产生 Raw。证据不足或没有可复用结论时，不必生成 Candidate。 |
| Review | 用户检查 Candidate 的内容、来源、适用范围和当前版本，再决定接受、修改、拒绝或暂缓。审核决定只针对当时展示的版本。 |
| Promote | 将审核通过的 Candidate 版本写入 Wiki，并保存审核证据。直接执行 `oks wiki create` 不是 Promote。 |
| Recall | `oks recall` 根据问题和范围返回可能相关的内容。结果分为 `episodic`、`knowledge` 和 `team_knowledge`。Agent 仍要阅读结果并判断是否适用。 |
| Use | 明确记录某个 Wiki 在任务中被采用，例如执行 `oks wiki use`。Recall 命中、Hook 注入、Agent 采用、Use 记录和人工审核是不同事件。 |

## 状态属于哪个对象

同一个状态词可能出现在不同文件中。阅读状态时，先看它属于哪个对象。

### Wiki 状态

| 状态 | 含义 |
|---|---|
| `provisional` | 页面可以查询，但还没有当前审核证据。`oks wiki create` 和 `oks wiki unarchive` 都会产生这一状态。 |
| `active` | 页面处于正常使用状态。Candidate Promote 会生成这一状态，但是否有有效人审记录仍要检查 `human_reviewed_at` 和来源。 |
| `stale` | 页面仍可查询，但维护规则认为它需要复查。 |
| `dropped` | 页面已经退出个人 Wiki 的普通 Recall。 |
| `superseded` | 页面已被其他页面替代，退出个人 Wiki 的普通 Recall。 |

`archived` 是单独的归档标记，不是 `status` 的取值。归档页不进入普通 Recall；取消归档后状态是 `provisional`，不会恢复为 `active`。

### Evidence Manifest 状态

| 状态 | 含义 |
|---|---|
| `complete` | 当前 Recipe 的总体完成条件已经满足。它不表示证据足以支持某个 Candidate，也不表示来源或结论正确。 |
| `partial` | 证据仍有缺口。应在 `warnings` 中记录具体缺失，并用非 `none` 的 `failure_disposition` 说明后续处理方式。 |

Evidence Manifest 没有 `failed` 状态。如果所有 Fragment 都失败，Agent 不应提交一个伪装成 Manifest 的结果。

### Fragment、模态和步骤状态

不同字段允许的取值不同：

- Evidence Fragment 顶层使用 `succeeded`、`partial`、`failed`。
- Fragment 或 Manifest 的模态记录可使用 `succeeded`、`partial`、`failed`、`skipped`。
- Manifest 的执行步骤可使用 `succeeded`、`partial`、`degraded`、`failed`、`skipped`。

`degraded` 表示改用能力较弱的处理路径；`skipped` 表示步骤没有执行，并且应记录原因。`partial` 在这里描述单个产物或步骤，只完成了一部分；它与 Manifest 的总体 `partial` 不是同一层判断。

### 工作流状态

Ingest、任务、评测和 Studio 各有自己的工作流状态，例如 `pending`、`queued`、`running` 或 `complete`。这些状态只在对应工作流中解释。页面写了步骤、“学习”页面显示完成、文件存在，均不能替代实际执行记录。

查看各部分怎样配合，见[系统组成](architecture.html)；首次操作见[第一次实践](../first-knowledge-loop.html)。
