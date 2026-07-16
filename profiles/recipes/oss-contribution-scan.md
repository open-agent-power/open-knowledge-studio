---
title: OSS Contribution Scan
type: recipe
trigger: manual
schedule: "0 10 * * 1,4"
tools:
  - gh
  - git
  - mvn
domains:
  - computing
  - engineering
keywords:
  - open source
  - pull request
  - rocketmq
  - silent merge
status: active
---

# OSS Contribution Scan

把「知识库驱动的开源贡献」循环固化成可复用配方。受 `profiles/goals/oss-contribution.md`
约束（ODD）。核心原则：**去重前置、人类在环、失败回流**。

## 前置

- `gh auth status` 通过
- 目标仓库画像存在（如 `profiles/projects/rocketmq.md`）

## Steps

1. **召回策略**（知识驱动，先看再动）
   ```bash
   oks recall "开源贡献 PR 选仓库 issue 筛选 merge"
   ```
   必读：repo-selection / pr-merge-patterns / ci-triage / no-op 陷阱 /
   apache-project-contribution / 目标 project profile 的 Lessons Learned。

2. **repo 体检**（repo-selection 标准）
   `gh repo view OWNER/REPO --json stargazerCount,defaultBranchRef,pushedAt,forkCount`
   ——确认活跃、默认分支（Apache 多为 `develop`）、竞争程度。

3. **拉 issue 列表**（抢鲜：按创建时间倒序，无指派）
   `gh issue list --repo OWNER/REPO --state open --search "no:assignee sort:created-desc" --limit 30 --json number,title,createdAt,labels,comments`

4. **Gate 1 去重（前置，不可省）** — 对每条候选：
   `gh pr list --repo OWNER/REPO --state all --search "NNN in:title" --json number,state`
   有 OPEN / MERGED PR → 立即剔除。**先去重，再打分。**（教训：热门仓库小 diff 几小时被摘光）

5. **判合法性** — 只留 real-bug-confirmed / 已 greenlit enhancement；
   丢弃 already-fixed / not-a-bug / out-of-scope / needs-info。

6. **打分排序 + 交叉引用代码** — issue-triage 0-100 打分；对 top 候选
   `grep` 当前默认分支活代码确认 anti-pattern 仍在（verify-before-commit）。
   优先 issue-as-spec（含建议修复）+ ≤40 行 / 1 文件。

7. **产出候选清单**（只读到此为止）— 排名表 + top 候选的：文件、修复思路、
   diff 预估、分支名 `fix/issue-NNN-slug`、目标分支。

8. **⛔ 人类确认闸门** — 外部写操作（fork / branch / PR / 评论）必须用户点头。
   AI 不自动 fork、不自动提 PR、不自动评论他人仓库。

9. **确认后执行**（遵守 apache-project-contribution 约定）
   fork → 目标分支拉 feature 分支 → 最小改动 → 加 license 头 → 本地
   `mvn validate -pl <module>` → commit（`[ISSUE #NNN] ...`）→ push fork → 建 PR。

10. **提交后监控**（1-3 天一次，直到收敛）
    `gh pr checks <PR>` + `gh pr view <PR> --json mergeable,state,mergedAt`。
    首贡 CI `action_required` 是正常的，别关了重提。

11. **五维复盘 + 回流** — merge/关闭/拒绝后跑 eval-contribution 五维打分，
    任一维 <70 或被拒 → 蒸馏成 wiki strategy/anti-pattern，更新 project profile 的
    Lessons Learned / Previous PRs 表。

## 报告

`Repos scanned: N | 去重剔除: X | 合法候选: Y | 待确认 PR: Z | 已 merge 累计: M`

## 关联

- Goal / ODD：`profiles/goals/oss-contribution.md`
- 新策略：`wiki/engineering/strategies/`（热门仓库去重前置）
