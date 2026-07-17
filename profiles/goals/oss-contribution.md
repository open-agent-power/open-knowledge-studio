---
title: OSS Contribution Goal 2026-Q3
type: goal
owner: itxaiohanglover
period: "2026-06-15..2026-09-20"
status: active
domains:
  - computing
  - engineering
keywords:
  - open source
  - pull request
  - rocketmq
  - silent merge
  - contribution
---

# OSS Contribution Goal 2026-Q3

## Objective

在 Apache 开源竞赛周期内（RocketMQ 为主，可扩展到 higress / oss-compass），
用知识库驱动的循环持续产出**小而高 ROI、能被 merge** 的贡献——
而不是盲目刷量。goal 就是这个循环的边界（ODD）：越界的动作（大 refactor、
无授权评论、给已有 PR 的 issue 提冗余 PR）一律不做。

## Key Results

- [ ] 累计 ≥ 5 个被 merge 的 PR（每个 ≤40 行 / 1 文件 / 1 issue）
- [ ] 每个 PR 提交前通过 Gate 1 去重（`gh pr list --search "NNN in:title" --state all`）
- [ ] 每个 PR 提交后 1-3 天监控一次 mergeable + issue 状态，直到收敛
- [ ] 每轮贡献结束跑一次五维复盘（eval-contribution），失败案例回流到 wiki
- [ ] no-op PR 数 = 0（提交前 verify-before-commit 100% 执行）

## 边界（对抗熵增的约束）

- **只写自己 fork + 目标仓库的 PR/评论**，不碰他人 PR、不群发评论。
- **外部写操作（fork / branch / PR / issue 评论）必须人类确认**，AI 只做到"给出待办 + 候选 + diff 预览"为止。
- 竞争 PR 存在 → 跳过；issue 非法（not-a-bug / out-of-scope）→ 跳过。

## Recall Influence

本 goal 是 `active` 的，因此召回引擎会真实加权（第 7 因子，见 [召回引擎](../../docs/recall-engine.md)）：
对**已经命中查询**的 wiki 页，若其 `area` ∈ 本 goal 的 domains（`computing` / `engineering`）
则 +0.8，若页面命中任一关键词（`open source` / `pull request` / `rocketmq` /
`silent merge` / `contribution`）再 +0.4。无 active goal 时该因子不生效。
效果：贡献循环优先看到 repo-selection / pr-merge-patterns / no-op 陷阱 / apache 约定这些策略。

## 关联

- 项目画像：`profiles/projects/rocketmq.md`（含 #10531/#10532 失败教训）
- Apache 约定：`profiles/projects/apache-project-contribution.md`
- 执行配方：`profiles/recipes/oss-contribution-scan.md`
