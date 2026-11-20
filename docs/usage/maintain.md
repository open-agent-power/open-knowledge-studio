---
title: 修订、替代与归档
nav_order: 4
parent: 日常任务
---

# 修订、替代与归档

知识会因项目版本、外部事实或新证据发生变化。维护时应保留旧内容和变化原因，让后续 Agent 能判断哪一版适用。OKS 没有一个通用的 `wiki revise` 命令；有实质变化时，推荐提出新的 Candidate，再通过关系说明怎样处理旧页。

## 先判断是哪种变化

| 情况 | 建议关系或操作 | 旧页会怎样 |
|---|---|---|
| 新内容补充旧页，二者都仍有效 | `enriches` | 继续参与 Recall，并记录补充页 |
| 新证据支持旧结论 | `confirms` | 继续保留，并记录印证关系 |
| 新证据使旧结论需要复核 | `challenges` | 标为 `stale`，仍可能被 Recall 返回 |
| 新版本完整取代旧版本 | `supersedes` | 标为 `superseded`，退出普通 Recall |
| 页面不应继续参与查询，但需保留文件 | `oks wiki archive` | `status: dropped` 且 `archived: true` |

`confirms` 会更新置信度元数据，但这只是程序规则，不是“正确率提高了 10%”或独立事实证明。

## 推荐的修订步骤

```text
请检查这条 Wiki 与新材料的差异。保留新材料为 Raw，
再整理一个新的 Candidate，说明它是补充、印证、质疑还是取代旧页，
列出改变的结论、适用范围和证据。等我审核后再更新关系和状态。
```

1. 保存新来源和实际证据。
2. 打开旧 Wiki，核对状态、审核记录和适用范围。
3. 新建 Candidate，明确哪些内容保持不变、哪些发生变化。
4. 选择关系并展示预期影响。
5. 人审核 Candidate 的当前版本。
6. Promote 后检查新旧页面的关系和状态。

直接编辑已有 Wiki 正文不会自动产生新的 Candidate 决定，也不会让旧审核记录自动适用于修改后的文字。涉及结论、范围或证据的变化，应重新走 Candidate 审核。

## 质疑与取代的区别

`challenges` 适合证据仍有争议、旧页需要提醒读者复核的情况。旧页变为 `stale`，普通 Recall 仍可能返回它，Agent 应同时展示质疑来源。

`supersedes` 适合新版本已经完整替代旧版本的情况。旧页变为 `superseded`，退出普通 Recall，但文件和关系仍保留，便于查历史。

不要为了清理搜索结果就随意使用 `supersedes`。如果两条内容适用于不同项目或版本，应该把范围写清，而不是强行让其中一条失效。

## 归档、衰减与恢复

显式执行 `oks wiki archive <slug>` 会把页面设为 `dropped` 并标记归档。`oks decay` 也可能把低分且未固定的页面设为 `dropped`，但不会删除 Markdown 文件。

执行 `oks wiki unarchive <slug>` 时，页面恢复为 `provisional`，不会恢复原来的 `active` 状态，也不会补写新审核记录。需要重新作为已审核内容使用时，应重新检查当前正文和证据，再按 Candidate 流程处理。

使用次数、固定和记忆分数只影响维护与排序，不表示内容更正确。完整计算规则见[衰减系统](../algorithms/decay-system.html)。

## 完成后检查

- 新证据已经保存，且能回到具体来源。
- Candidate 说明了新旧内容的差异和关系。
- Promote 针对你审核过的版本。
- `stale`、`superseded`、`dropped` 和 `archived` 与预期一致。
- 普通 Recall 不再返回应退出的旧页；仍可返回的旧页带有足够的范围和警告。
- 恢复归档页后，没有误称为已重新审核。

审核方法见[审核 Candidate](review.html)，查询时怎样理解状态见[查询与引用](recall.html)。
