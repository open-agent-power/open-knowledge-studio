---
title: Repo Selection Strategy — 选什么仓库最容易 merge
tags:
- oss
- repo
- selection
- strategy
area: computing
source: learnings/2026/06/20/20260620-multi-repo-pr-retrospective
type: strategy
status: active
importance: 0.7
confidence: 0.8
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# Repo Selection Strategy

## 选仓库标准

| 维度 | 理想值 | 理由 |
|------|--------|------|
| Stars | 100-5000 | 太少没人看，太多首次贡献者 CI 不跑 |
| 活跃度 | 最近 7 天有 commit | maintainer 还在 |
| Open PR 数 | 0-3 | 太多说明 review 积压 |
| Open Issue 数 | 10-50 | 太少没有可做的，太多说明 maintainer 不响应 |
| CLA | 无 CLA 或简单 CLA | Apache/Google CLA 会拖延 |
| AI Policy | 无 AI_POLICY.md | 有则跳过 |
| 语言 | 熟悉的语言 | 降低出错率 |

## 仓库类型 vs merge 难度

| 类型 | merge 难度 | 典型 review 周期 | 建议 |
|------|-----------|----------------|------|
| 个人项目（1-2 maintainer）| 低 | 1-3 天 | 优先 |
| 小型组织（3-10 maintainer）| 中 | 3-7 天 | 适合 |
| Apache 项目 | 高 | 1-4 周 | 提前提交 |
| Google 项目 | 高 | 1-2 周 | 需签 CLA |
| 超大项目（>100k star）| 极高 | 不可预测 | 竞赛不推荐 |

## 竞争情报

提交前检查是否有竞争 PR：
```bash
gh pr list --repo OWNER/REPO --search "ISSUE_NUMBER" --state all
gh pr list --repo OWNER/REPO --search "KEYWORD" --state all
```

如果有 open PR → STOP，转而 review 已有 PR。

## 🔒 Repo Activity Hard Gate

> 教训：agentUniverse 上次 push 2026-04-24，我们 07-05 提交 PR，2 天后 0 CI、0 review。
> 维护者不活跃 = PR 永远不会 merge。

**提交前必须执行：**

```bash
# 查最近 push 时间
gh api repos/OWNER/REPO --jq '.pushed_at'
# 查最近 5 个 commit
gh api "repos/OWNER/REPO/commits?per_page=5" --jq '.[].commit.author.date'
```

| 最近 push 距今 | 判定 | 行动 |
|---------------|------|------|
| ≤7 天 | 活跃 | ✅ 可以提交 |
| 8-14 天 | 正常 | ✅ 可以提交 |
| 15-30 天 | 低活跃 | ⚠️ 仅提交高优先级 issue |
| >30 天 | 停滞 | ❌ **SKIP，不要提交** |

**注意**：即使初始选仓库时活跃，提交前也要重新检查——仓库可能在此期间变 stale。

## 反模式

- 选 >100k star 仓库 → review 周期不可控
- 选有 AI_POLICY.md 的仓库 → PR 被关闭
- 选 stale 仓库（>30 天无 commit）→ 永远不 merge
- 选需要 issue assignment 的仓库 → 等待 maintainer 分配

## 关联

- 风险分散：`risk-spreading.md`
- 竞赛策略：`conventions/oss-competition-strategy.md`
