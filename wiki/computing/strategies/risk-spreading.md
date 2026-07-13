---
title: Risk Spreading Strategy — 多项目分散风险
tags:
- oss
- competition
- risk
- strategy
area: computing
source: session/competition-2026
type: strategy
status: active
importance: 0.7
confidence: 0.75
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# Risk Spreading Strategy

## 原则

不要把所有精力投入一个项目。不同项目的 review 周期、merge 难度、
issue 数量差异很大，分散投资最大化总 merge 数。

## 竞赛分配

### 原始分配（2026-06）

| 项目 | 语言 | 精力 | 预期 merge 数 | 理由 |
|------|------|------|-------------|------|
| agentUniverse | Python | 30% | 3-5 | 快速 review，已知 gotcha |
| OSS Compass | Python/TS | 30% | 3-5 | 3 repos，更多 surface area |
| Higress | Go/Java | 20% | 1-3 | CLA + MCP 配置陷阱 |
| RocketMQ | Java | 20% | 1-2 | Apache review 慢 |

### 修正分配（2026-07-07）

| 项目 | 语言 | 精力 | 预期 merge 数 | 理由 |
|------|------|------|-------------|------|
| agentUniverse | Python | **5%** | 0-1 | ⚠️ 仓库 2.5 月无 push，maintainer 疑似不活跃，仅维护已有 PR |
| OSS Compass | Python/TS | **35%** | 3-5 | ✅ 3 repos 全活跃，0 PR 已提交，最大未开发机会 |
| Higress | Go/Java | **35%** | 2-4 | ✅ 仓库今天还有 push，PR #4077 CI 全绿只需 rebase |
| RocketMQ | Java | **25%** | 1-2 | Apache review 慢，2 PR 已关闭，需要找新 issue |

### 再分配触发条件

| 信号 | 行动 |
|------|------|
| 仓库 >30 天无 push | 精力降到 5%，仅维护已有 PR |
| 仓库 >60 天无 push | 放弃，精力转其他项目 |
| 3 个 PR 全部被 close/reject | 该项目精力降到 10%，转其他 |
| 某项目 merge 了第 1 个 PR | 可增加 10% 精力（建立信任） |

## 多仓库并行模式

```
扫描阶段（1天）
  → 4 个项目同时扫 issue + 评估 fixability
  → 按评分排序，取 top 10

编码阶段（2-3天）
  → 高分 issue 并行编码
  → 每个 PR ≤40 行

提交阶段（1天）
  → 按 Gate 1-6 逐个提交
  → Apache 项目优先（review 周期长）
```

## 单仓库上限

| 仓库类型 | 单仓库 PR 上限 | 理由 |
|---------|--------------|------|
| 个人项目 | 3 | maintainer 会疲劳 |
| 小型组织 | 5 | 有 review 团队 |
| Apache | 2 | review 周期长，多了管不过来 |

## 反模式

- 全投一个项目 → 风险集中，maintainer 不活跃就全挂
- 一次推 5 个 PR 到同一仓库 → reviewer 全部 mark "changes requested"
- 只做大项目（Apache）→ review 周期不可控
- 只做小项目（个人）→ maintainer 消失就全挂

## 关联

- Repo 选择：`repo-selection.md`
- Timing：`timing-strategy.md`
- Silent Merge：`pr-merge-patterns.md`
