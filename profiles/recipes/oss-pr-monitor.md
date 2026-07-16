---
title: OSS PR Monitor
type: recipe
trigger: scheduled
schedule: "0 10 */2 * *"
tools:
  - gh
domains:
  - computing
  - engineering
keywords:
  - pull request
  - monitor
  - merge
  - rocketmq
status: active
---

# OSS PR Monitor

监控所有「已提交、未收敛」的 PR，直到 merged / closed。补上
`oss-contribution-scan.md` 之后最容易被忘的一环——提交后监控。
教训来源：RocketMQ #10532 提交后不监控，1 天被 #10422 抢先 merge，17 天后才发现。

## 触发

每 2 天一次（或手动）。受 `profiles/goals/oss-contribution.md` KR
「提交后 1-3 天监控一次直到收敛」约束。

## Steps

1. **列出待监控 PR** — 从各 project profile 的 Previous PRs 表里
   status=Open 的行，或直接查自己名下 PR：
   ```bash
   gh search prs --author "@me" --state open --json repository,number,title,url
   ```

2. **逐个查状态**
   ```bash
   gh pr view <PR> --repo OWNER/REPO --json state,mergeable,mergedAt,statusCheckRollup,reviews
   ```
   关注：
   - `state` / `mergedAt` — 是否已收敛
   - `mergeable` — 变 CONFLICTING 说明 base 动了，需 rebase
   - `statusCheckRollup` — CI 红/绿；首贡 `action_required` 是正常的，等维护者放行，别关了重提
   - `reviews` — 有无 CHANGES_REQUESTED

3. **查竞争 PR 是否抢先**（Gate 1 的持续版）
   ```bash
   gh pr list --repo OWNER/REPO --state all --search "<ISSUE_NNN> in:title"
   ```
   若同 issue 的别的 PR 被 merge → 自己的 PR 变 no-op，关闭并记录教训。

4. **按状态行动**
   | 状态 | 动作 |
   |------|------|
   | CI 红（真失败） | 触发 debugger / ci-triage，最小改动 push 同分支 |
   | CHANGES_REQUESTED | 24h 内回应 review，只改被点名处 |
   | CONFLICTING | rebase 到最新 base 分支，force-push 自己 fork 分支 |
   | 被竞争 PR 抢先 merge | 关闭自己 PR，记 no-op 教训 |
   | Merged | 跑 eval-contribution 五维复盘，回流 wiki |
   | 长期无响应（>3 ping 或 >30d） | 停手，转其他 issue |

5. **更新记录** — 把每个 PR 的最新状态写回对应 project profile 的
   Previous PRs 表（Open → Merged/Closed + Lesson）。

## 报告

`待监控: N | 已 merge: X | 被抢/关闭: Y | 需回应 review: Z | 冲突待 rebase: W`

## 关联

- 扫描配方：`profiles/recipes/oss-contribution-scan.md`
- Goal / ODD：`profiles/goals/oss-contribution.md`
- CI 假阳性排查：`wiki/computing/strategies/ci-triage.md`
