---
title: Timing Strategy — 什么时候提交、什么时候等
tags:
- oss
- timing
- ci
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
| `pending` | 跑着呢 | 等 |
| `action_required` | 首次贡献者需 maintainer 批准 | **不要重提**，等批准 |
| `failure` (Codecov) | Fork 无 token | 忽略，看 upstream CI |
| `failure` (test) | 真的挂了 | 修 |
| `failure` (lint/format) | 格式不对 | 跑 formatter 重推 |

## Review 响应 SLA

| 维度 | 目标 |
|------|------|
| 首次响应 | 收到评论后 24h 内回复 |
| 代码修改 | 收到 review 后 48h 内推 fix commit |
| Ping maintainer | 最多 3 次，间隔 ≥3 天 |
| 超 3 次无响应 | 放弃，转其他 PR |

## Post-Submission Monitoring

提交后不监控 = 等于没提交。以下规则来自 PR #10532 教训：
提交后 1 天就有竞争 PR 被 merge，17 天后才发现。

### 监控频率

| 提交后时间 | 频率 | 检查内容 |
|-----------|------|---------|
| 1-3 天 | 每天 | CI 状态、mergeable、竞争 PR |
| 4-14 天 | 每 3 天 | PR 状态、issue 是否 closed、竞争 PR |
| 14+ 天 | 每周 | 是否 stale，是否该 ping |

### 检查命令

```bash
# PR 状态 + mergeable
gh pr view NNN --repo OWNER/REPO --json state,mergeable,mergeStateStatus

# Issue 是否已 closed（可能被别的 PR 修了）
gh issue view NNN --repo OWNER/REPO --json state,closedByPullRequestsReferences

# 竞争 PR（关键！）
gh pr list --repo OWNER/REPO --search "ISSUE_NUMBER" --state all
```

### 预警信号

| 信号 | 含义 | 行动 |
|------|------|------|
| `mergeable: CONFLICTING` | base 分支已变 | 立即查竞争 PR |
| issue 变成 `closed` | 已被别的 PR 修了 | 立即关闭自己的 PR |
| 出现新的 competing PR | 有人在抢同一个 issue | 评估是否放弃 |
| 7 天无任何 review | maintainer 不活跃 | 考虑 ping 或放弃 |

### 反模式

- 提交后不查 → #10532 教训：17 天后发现已被抢
- 只查自己的 PR，不查竞争 PR → base 变了不知道为什么
- 只查 PR 状态，不查 issue 状态 → issue closed 了还开着 PR

## 反模式

- CI 显示 `action_required` 就关掉重提 → 新 PR 还是 `action_required`
- Fork CI 红就慌 → 99% 是 Codecov token 缺失
- 维护者 1 天没回就 ping → 太频繁惹人烦
- 一次性推 5 个 PR 到同一个仓库 → reviewer 疲劳

## 关联

- Repo 选择：`repo-selection.md`
- 风险分散：`risk-spreading.md`
