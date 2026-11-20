---
title: 工作原理
nav_order: 5
has_children: true
---

# 工作原理

OKS 把材料、知识页、任务背景和运行记录保存在可直接查看的文件中，再通过 CLI 提供校验、审核、查询和维护操作。Agent 负责理解任务和使用这些工具；OKS 本身不会阅读材料后自行得出结论。

建议按下面的顺序阅读：

1. [系统由哪些部分组成](architecture.html)：人、Agent、CLI、Skill、Hook、Studio 和知识库各自负责什么。
2. [知识对象与生命周期](philosophy.html)：Raw、Candidate、Wiki 和 Recall 之间是什么关系。
3. [术语表](glossary.html)：查找页面和命令中使用的正式名称。
4. [跨会话协作](product-boundary.html)：Mail 能保存什么，以及它不会自动完成什么。

## 先分清四类内容

| 类别 | 包含什么 | 主要作用 |
|---|---|---|
| 知识内容 | Raw、Candidate、Wiki | 保存来源、待审核提议和可查询知识页 |
| 任务上下文 | Profile、Goal | 说明用户、项目和当前任务的范围 |
| 执行方法 | Skill | 告诉 Agent 何时使用哪些步骤、脚本和资源 |
| 过程记录 | Mail、Trace、`records/` | 保存交接、执行事件、审核决定和评测结果 |

Studio 中的“讨论”“目标”“学习”是组织入门和日常工作的页面入口，不是另一套知识状态。一次讨论不一定产生 Candidate，“学习”页面显示完成也不表示内容已经通过审核。

## 进一步了解

- [个人库、团队库与工具仓库](../knowledge-repositories.html)
- [知识库目录与本地状态](../instance-layout.html)
- [查询、使用与评测记录](../linked-knowledge-observability.html)

精确命令和字段见[参考手册](../reference/)；实现约束和算法说明见[维护者文档](../maintainers/)。
