---
title: 宪法
nav_order: 2
parent: 概念
---
# 宪法（A1-A5 架构不变量）

完整文本见 [CONSTITUTION.md](https://github.com/open-agent-power/open-knowledge-studio/blob/main/CONSTITUTION.md)。下面是摘要。

## A1: 认知桶 + 两基础设施

A1 列出 `profiles/` `raw/` `wiki/` `drafts/` `mail/`，并将 `settings/` `_meta/` 作为两个基础设施层。其中 `mail/` 保存 Agent 间的短期通信，不参与 Recall 或衰减。记忆生命周期：Observe → Write → Store → Retrieve → Inject → Forget。

召回索引是**可重建的派生物**——从 Git 中已审核的 `wiki/` 生成；Git 里人审过的知识才是真正来源，索引丢了重跑 `oks recall` 即可重建。这划清三层：原始证据层（`raw/`，只增不改）/ 知识层（`wiki/`，可修订）/ 服务层（召回索引，可重建）。

## A2: 六类记忆 + 注入顺序 + source labels

User / Project / Episodic / Semantic / Procedural / Draft 六类，映射到认知桶 + skills。每条注入的知识带 source label（`[verified]` / `[inferred]` / `[stale]` / `[untrusted-source]`），未识别类型默认 untrusted。

## A3: Dreaming — 人审门控

`raw/` → AI 蒸馏 → `drafts/` → 人审 → `wiki/`。**绝不 auto-promote**——raw 内容不审不进 wiki。AI 写的只是 Candidate，人的 yes/no 是决策。

Dreaming 循环：Collect（raw 积累）→ AI Dream（Agent 分级 A/B/C，A级写 draft）→ Human Review → Promote → Decay → Evolve（A4 关系）→ Commit。`oks distill` 跑衰减 + 演化，不代替 Agent 分级或人审。

**人审 vs 异源 Agent 互审**：大型共享知识库可用 Proposer-Reviewer 异源互审（Proposer 用 Claude / Reviewer 用 GPT，降低同类错误），但 OKS 面向个人 / 小团队，人审（`oks drafts promote`）即保证真实性——异源互审是 OKS 之上的可选增强，不进核心。

## A4: 知识演变

四种关系：`supersedes`（取代）/ `enriches`（补充）/ `confirms`（印证）/ `challenges`（质疑）。关系记在 frontmatter，召回时旧页降权。

## Provenance 与安全边界

`raw/executions/` + `raw/.logs/` 是 provenance（执行轨迹 + AI digests），**排除召回**——否则 agent 自己写的 `ai_comment` 会被当记忆加权喂回，压过人采材料。轨迹只能通过 wiki 页 frontmatter 的 evidence 链接到达。

远程 provider（Firecrawl 等）调外部 API 时：凭据只从环境变量 / MCP token / OS keychain 来，绝不硬编码或入 git；`policy.remote_processing`（`deny` / `allow` / `ask`）控制是否调远程；输出经 `oks security sanitize` 脱敏后才入 Raw Bundle。这是 best-effort 凭据防护，非完整防泄漏。

## A5: 原子写

所有持久化用 `mkstemp` + `fsync` + `os.replace`——写一半崩溃不留半文件。
