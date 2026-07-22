---
title: 内部机制
nav_order: 10
has_children: true
---
# 内部机制

*OKS 的架构、召回、记忆模型与演化机制——理解系统如何工作。*

Open Knowledge Studio 的设计由一组明确的不变量驱动：认知桶架构、六型记忆、人工审查的 Dreaming 循环、类型化衰减。这些页面讲清楚系统内部如何运作。

| 页面 | 内容 |
|------|------|
| **[架构设计](architecture.md)** | 认知桶结构 + 记忆生命周期 + 设计原则 |
| **[召回引擎](recall-engine.md)** | 6+1 因子评分：token overlap + substring + topic trace + type boost + 审查加分 + memory curve |
| **[记忆模型](memory-model.md)** | 六型记忆、注入顺序（稳定层在前）、来源标签、冲突优先级 |
| **[Dreaming 循环](dreaming-cycle.md)** | 知识演化：collect → dream → drafts → review → promote → decay → evolve |
| **[衰减系统](decay-system.md)** | 记忆曲线、类型特定 λ、tier 分级（hot/warm/cold/evictable） |
| **[知识库指标](metrics.md)** | 四维报告卡：规模、活力、价值、可信度 |
| **[Profiles 画像](profiles.md)** | 稳定认知桶：团队、用户、项目画像、recipes、goals |
| **[Wiki 知识](wiki.md)** | 语义记忆桶：22 域 × 3 类型、衰减与召回主战场 |
| **[演化与 Skills](skills-evolution.md)** | OKS 的演化发生在哪里，Skills 的真实定位 |
