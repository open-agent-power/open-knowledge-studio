---
title: Contribution Five-Dimension Retro
type: recipe
trigger: manual
schedule: ""
tools:
  - gh
domains:
  - computing
  - engineering
keywords:
  - retro
  - contribution
  - pull request
  - lessons learned
status: active
---

# Contribution Five-Dimension Retro（eval-contribution）

每个 PR 收敛（merged / closed / rejected）后跑一次的**五维复盘**。
被 `oss-contribution-scan.md`（Step 11）和 `oss-pr-monitor.md`（Merged 行）引用。
目的：把一次贡献的成败拆成可打分的维度，任一维 <70 或被拒 → 蒸馏成 wiki
strategy / anti-pattern，并回写 project profile 的 Lessons Learned。

> **执行方式**：本配方是给 Agent 读的**自动化契约**，手动触发（PR 收敛时）。
> OKS 核心**不内置调度器/执行器**，编排由 Agent + 人类在环完成（CONSTITUTION P5）。

## 五个维度（各 0-100）

| 维度 | 问题 | <70 的典型信号 |
|------|------|----------------|
| 1. 选题合法性 | issue 是真 bug / 已 greenlit enhancement？非 no-op？ | 事后发现 not-a-bug / out-of-scope |
| 2. 去重前置 | 提交前是否执行 Gate 1（`gh pr list --search "NNN in:title" --state all`）？ | 被已存在的 PR 撞车 |
| 3. 改动质量 | 最小 diff（≤40 行 / 1 文件）、含 license 头、本地校验通过、CI 绿？ | reviewer 要求大改 / CI 真失败 |
| 4. 收敛结果 | 是否 merged？被抢先 / 拒绝 / 长期无响应？ | 被竞争 PR 抢 merge、>30d 无响应 |
| 5. 循环闭合 | 失败/教训是否回流 wiki + 更新 project profile？ | 教训只留在脑子里，没落库 |

## Steps

1. **取事实** — `gh pr view <PR> --repo OWNER/REPO --json state,mergedAt,mergeable,reviews,statusCheckRollup`，
   并回看扫描/监控阶段的记录。
2. **逐维打分** — 按上表给 1-5 维各打 0-100，写一句依据。
3. **判定回流** — 任一维 <70，或 state 为 closed/rejected：
   - 把教训蒸馏成 `drafts/` 里的 strategy 或 anti-pattern（走 `/promote` 进 wiki）；
   - 更新对应 `profiles/projects/<repo>.md` 的 Lessons Learned / Previous PRs 表。
4. **记账** — 更新 goal `oss-contribution.md` 的 KR 进度（累计 merged、no-op 数）。

## 报告

`PR <NNN> | 维度分: [合法 legit / 去重 dedup / 质量 quality / 收敛 outcome / 闭合 loop] | 回流: <slug 或 none>`

## 关联

- 扫描配方：`profiles/recipes/oss-contribution-scan.md`
- 监控配方：`profiles/recipes/oss-pr-monitor.md`
- Goal / ODD：`profiles/goals/oss-contribution.md`
