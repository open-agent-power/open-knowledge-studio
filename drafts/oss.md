---
title: Oss Proposal
draft_type: strategy
draft_area: computing
source_pages:
- risk-spreading
- timing-strategy
- pr-merge-patterns
- repo-selection
drafted_at: '2026-07-11'
status: draft
---

# Oss — Wiki Proposal

> Drafted from 4 wiki pages. Sources: risk-spreading, timing-strategy, pr-merge-patterns, repo-selection.

Proposed type: `strategy` | Area: `computing`

## Risk Spreading Strategy — 多项目分散风险
# Risk Spreading Strategy

## 原则

不要把所有精力投入一个项目。不同项目的 review 周期、merge 难度、
issue 数量差异很大，分散投资最大化总 merge 数。

## 竞赛分配

### 原始分配（2026-06）

| 项目 | 语言 | 精力 | 预期 merge 数 | 理由 |
|------|------|------|-------------|------|
| agentUniverse | Python | 30% | 3-5 | 快速 review，已知 gotcha |
| OSS Compass | Python/TS 

## Timing Strategy — 什么时候提交、什么时候等
# Timing Strategy

## Apache 项目时间线

Apache 项目 review 周期 1-4 周，需要提前提交：

```
竞赛截止 09-20
  ← Apache 最晚提交 08-15（留 4 周 review+merge）
  ← Apache 最晚开始 08-01（留 2 周 找 issue + 写代码）
  ← 非 Apache 最晚提交 09-06（留 2 周）
```

## CI 状态决策表

| CI 状态 | 含义 | 行动 |
|---------|------|------|
| `success` | 全绿 | 等 review |
| `p

## Silent Merge Pattern — PR size vs merge rate
# Silent Merge Pattern

## 招式

≤40 行、1 文件、1 issue 的 PR 有最高的静默 merge 率。
没有 review comment，直接 merged。

## 数据

| PR 大小 | 提交数 | 静默 merge 数 | merge 率 |
|---------|--------|--------------|---------|
| ≤40 行 | 8 | 6 | 75% |
| 40-100 行 | 3 | 1 | 33% |
| >100 行 | 1 | 0 | 0% |

## 适用场景

- 开源贡献竞赛（时间有限，需最大化 mer

## Repo Selection Strategy — 选什么仓库最容易 merge
# Repo Selection Strategy

## 选仓库标准

| 维度 | 理想值 | 理由 |
|------|--------|------|
| Stars | 100-5000 | 太少没人看，太多首次贡献者 CI 不跑 |
| 活跃度 | 最近 7 天有 commit | maintainer 还在 |
| Open PR 数 | 0-3 | 太多说明 review 积压 |
| Open Issue 数 | 10-50 | 太少没有可做的，太多说明 maintainer 不响应 |
| CLA | 无 CLA 或简单 CLA | Apache/Google CLA 会拖


---
Review and merge into wiki/ if valuable, or discard.