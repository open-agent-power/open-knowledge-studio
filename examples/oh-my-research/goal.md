---
title: 审查 OKS Core 与 Connector 的职责边界
type: goal
owner: example
period: ongoing
status: draft
domains:
  - computing
keywords:
  - core
  - connector
  - architecture
  - evidence
  - human review
---

# 示例 Goal：审查 Core 与 Connector 的职责边界

> 这是可复制的示例，不是已激活的个人目标。复制到你的 OKS 实例后，先修改研究问题、
> `owner` 和资料范围，确认边界后再将 `status` 改为 `active`。

## Objective

基于当前宪法、代码和 Connector 仓库，形成一份可追溯的职责边界判断，说明哪些能力属于
OKS Core，哪些机械采集与格式处理应留给 Connector。

## Key Results

- [ ] 收录当前宪法、Core 说明和 Connector 说明，保留各自来源。
- [ ] Candidate 区分代码事实、维护者原则和推断。
- [ ] 人工审核至少一条边界判断，并记录接受、编辑或拒绝理由。
- [ ] 能通过 Recall 找回边界结论及其证据。
- [ ] 发现文档与实现冲突时保留冲突，不擅自统一口径。

## 边界

- 不给 OKS 增加与知识生命周期无关的能力。
- Connector 只负责采集和机械提取，不拥有 Candidate、Review 或 Wiki 状态。
- 未经人审，不把研究结论自动晋升为 Wiki。
- 个人研究产物保存在独立知识库，不提交进框架仓库。
