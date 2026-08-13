---
title: 概述
nav_order: 1
---

<div align="center">
  <img src="assets/oks-logo-readme.png" width="360" alt="Open Knowledge Studio">
</div>

# Open Knowledge Studio

> 让 Agent 把资料转化为可审核、可追溯、以后能重新召回利用的知识。

OKS 是一个 Agent-native、文件系统优先的知识工作台。来源先成为 Raw 证据，
Agent 再提出 Candidate；只有经过人的审核，内容才进入 Wiki，并在未来任务中
被 Recall。

```text
你的资料 → Candidate → 人工审核 → Wiki → Recall
```

## 选择下一步

| 你现在要做什么 | 从这里进入 |
|---|---|
| 第一次使用 | **[安装](installation.md)** — 用唯一推荐方式安装并初始化 |
| 已经安装 | **[第一个知识闭环](first-knowledge-loop.md)** — 用自己的真实资料跑通一次 |
| 不确定哪里出错 | **[确认 OKS 正在工作](verify-it-works.md)** — 按成功信号逐步检查 |

## OKS 负责什么

- **保留来源**：Raw 保存原始材料和可追溯证据。
- **提出知识**：Agent 根据证据生成 Candidate，并执行 A/B/C 分级。
- **保留人的判断**：Candidate 经过审核后才能成为 Wiki 知识。
- **在任务中找回来**：`oks recall` 同时检索 Raw episodic 与 Wiki knowledge。
- **把失败说清楚**：`partial`、`failed`、`skipped` 和
  `environment_limited` 不会被包装成成功。

## 核心边界

- Core 不调用 AI API，只负责文件、协议、审核生命周期和 Recall 评分。
- 采集与提取由独立发布的 `oks-connector` 和 Agent 可用工具完成。
- 飞书是 `examples/feishu-loop/` 下的参考实现，删除它不影响 Core 闭环。
- `raw/executions/` 和 `raw/.logs/` 是溯源记录，不作为记忆参与 Recall。
- `[verified]` 只来自 trace 证据或 `human_reviewed_at`，不能由模型自行声明。

## 按需要深入

- **使用**：[收录资料](ingest.md) · [审核 Candidate](review-candidates.md) ·
  [Recall](recall.md) · [每日循环](daily-loop.md)
- **案例**：[托管你的简历](case-resume.md) · [托管你的 GitHub](case-github.md) ·
  [托管你的科研](case-research.md) · [托管你的学习](case-learning.md)
- **机制**：[架构设计](architecture.md) · [核心架构](architecture/oks-core-architecture.md) ·
  [召回引擎](recall-engine.md) · [Dreaming 循环](dreaming-cycle.md)
- **参考**：[命令与协议参考](reference.md) · [能力边界](capability-boundaries.md)

历史工程记录保留在仓库 `records/`，不作为当前产品文档的事实源。

---

{% include comments.html %}
