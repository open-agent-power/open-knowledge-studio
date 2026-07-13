---
title: Silent Merge Pattern — PR size vs merge rate
tags:
- oss
- pr
- merge
- strategy
area: computing
source: learnings/2026/06/20/20260620-multi-repo-pr-retrospective
type: strategy
status: active
importance: 0.7
confidence: 0.865
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---


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

- 开源贡献竞赛（时间有限，需最大化 merge 数）
- 首次贡献者（建立信任）
- 大型仓库（reviewer 没时间看大 diff）

## 反模式

- 一个 PR 修多个问题 → review 周期翻倍
- 加"顺手清理" → scope creep，reviewer 嫌弃
- 标题说 refactor 实际是 fix → bot 标记 mismatch

## 执行检查

- [ ] diff 是否 ≤40 行？
- [ ] 是否只改 1 个文件？
- [ ] 是否只解决 1 个 issue？
- [ ] 标题动词是否和 diff 一致？

## 关联

- 系统演进：`conventions/oss-competition-strategy.md`
- Repo 选择：`repo-selection.md`
- Timing：`timing-strategy.md`
- PR 模板：`plugins/autpilot-coding/skills/submit-pr/pr-body-templates.md`
