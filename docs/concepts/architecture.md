---
title: 架构总览
nav_order: 2
parent: 工作原理
---

# 架构总览

OKS 不是一个单独的“记忆插件”。它是一套让 **用户、Agent、文件化知识、收录能力和交付能力**各自做对的事的工作架构。

产品主线是知识学习、沉淀、复用和复利：Raw 经过 Candidate 和人审进入 Wiki，再由 Recall 带回真实任务；明确反馈才会推动下一轮 Candidate。Agent/Skill 负责编排，Trace 保存执行证据，Mail 记录跨执行边界的协作事实，Git 负责传输，UI 只投影这些真实产物。

<picture>
  <source media="(max-width: 50rem)" srcset="../assets/architecture/oks-overview-mobile.svg">
  <img src="../assets/architecture/oks-overview.svg" alt="OKS 三段式架构：来源经过能力选择、证据片段、Manifest 和 raw-commit，进入 Raw Bundle、Candidate、人工审核和 Wiki；中段是 profiles、raw、drafts、wiki、mail 五个桶与 settings、_meta、security、Trace；下段是 6+1 因子召回与上下文注入，飞书和 Office 为可选入口与交付能力。">
</picture>

## 怎样读这张图

先看第一段摄入流水线：Source 经过模态判断、Provider、EvidenceFragment、Manifest 和 `raw-commit`，才形成可追溯的 Raw Bundle；Agent 可以据此提出 Candidate，但只有人审核后才进入 Wiki。

第二段是文件工作区和运行时：

- `profiles/` 放稳定的用户、项目、Recipe 和 Goal；
- `raw/` 放原始来源与机械提取结果；
- `drafts/` 放 Agent 的 Candidate；
- `wiki/` 只放人审后的可复用知识；
- `mail/` 与 Trace 留下协作和执行证据，但不冒充长期知识；`settings/`、`_meta/` 和 `security/` 提供配置、Schema 与脱敏边界。

Mail 是知识主线的侧车，不是第二知识库、任务引擎或 Agent 控制台。它通过 Message、Thread、Session Receipt 和 Evidence Ref 支持同一 Agent 的跨 Session 接力、不同 Agent/Host 的交接，以及不同机器间的 Git 迁移。Receipt 只能证明呈现或确认，provenance 只能证明曾经出现；没有独立 Host Adapter 时，Mail 不唤醒进程、不创建 Session，也不保证任务执行。

`oks` CLI 负责文件操作、召回和状态，不在核心中调用模型 API；Agent 根据 Recipe、Provider 和 Capability 选择网页、PDF、Office、图片、音视频等处理能力。明确要交付文件时，Office 工作流才会接手 Word、PDF、PPT 或 Excel。飞书的 Base、表单与 IM 审核是**可选参考实现**：它可以承担采集和移动审核入口，但不属于 CLI 核心，也不会绕开人审门。

第三段是召回与注入：Query 先经过 scope / goal 约束，再由 6+1 因子评分、搜索后端、过滤去重，最终把已审核的 `wiki/` 和必要的 `raw/` 注入下一次任务。相关性只能影响排序，不能把材料升级为事实。

## 需要深入时

这张图把系统层级和实际能力放在一起，但没有展开协议字段与评分公式。需要进一步实现或排障时：

- 想收集不同类型的材料，阅读[收集来源](../usage/ingest.html)。
- 想理解审核和晋升，阅读[审核候选](../usage/review.html)。
- 想了解召回如何选择知识，阅读[召回与注入](../usage/recall.html)。
- 想理解知识主线与 Mail 协作边界，阅读[产品边界与协作模型](product-boundary.html)和 [Mail 协议](../reference/mail-protocol.html)。
- 维护者需要完整文件桶、只读 VFS、Hooks 与可选飞书集成时，阅读[宪法（A1-A5）](constitution.html)和[参考手册](../reference/)。

## 架构边界

- **Raw 不等于 Wiki**：Raw 保留材料和机械提取；Wiki 是经人审核、能在后续任务中复用的知识。
- **VFS 不是新知识桶**：`oks://` 只提供受限的只读访问视图，不会绕开文件治理。
- **Hooks 和飞书是可选入口**：它们可以改变收集或反馈的位置，但不会取消人工审核。
- **信任来自证据和审核**：`[verified]` 只应来自 Trace 证据或 `human_reviewed_at`，而不是使用次数。
