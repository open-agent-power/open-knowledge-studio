---
title: 知识对象与生命周期
nav_order: 2
parent: 工作原理
---

# 知识对象与生命周期

OKS 把来源、提议和知识页分开保存，因为它们表达的事实不同：保存来源不等于接受结论，提出 Candidate 不等于通过审核，查询命中也不等于内容适用于当前任务。

## 四个核心概念

| 名称 | 保存位置或形式 | 表示什么 |
|---|---|---|
| Raw | `raw/` | 原文、出处、附件、提取结果和处理状态，供以后回查 |
| Candidate | `drafts/` | Agent 整理出的待审核提议，包含依据、适用范围和不确定项 |
| Wiki | `wiki/` | 可被知识查询使用的知识页；是否经过审核要看页面元数据 |
| Recall | 一次查询操作 | 返回可能相关的 Raw、Profile、Wiki 和团队知识，供 Agent 继续判断 |

Raw、Candidate 和 Wiki 是不同的内容对象；Recall 是读取这些对象的操作，不是第四个保存目录。

## 推荐路径：Raw 到带审核记录的 Wiki

{% include knowledge-cycle.html %}

例如，一份项目复盘属于 Raw。Agent 从中提出“发布前先验证数据库迁移”这一做法，并注明只适用于项目甲当前部署流程，这是一条 Candidate。人核对原文并接受当前版本后，CLI 将它保存为 Wiki 页面，同时记录审核时间和来源 Candidate。复盘原文继续保留，便于以后查证。

审核说明人接受了这个版本供后续使用，不是独立事实核验，也不保证内容永远正确。项目、版本或外部事实变化后，仍要修订或替代旧页。

## Wiki 不等于全部已审核

Wiki 是存储和查询类别，不是统一的可信度标签。页面可能通过不同路径进入 `wiki/`：

| 路径 | 默认结果 | 审核记录 |
|---|---|---|
| 接受 Candidate，执行 `oks drafts promote` | `status: active` | 写入 `human_reviewed_at`，并保留具体 Candidate 版本的审核记录 |
| 直接执行 `oks wiki create` | `status: provisional` | 不写入人工审核时间 |

普通 Recall 会排除 `dropped`、`superseded` 和已归档页面，但可以返回 `provisional` 或 `stale` 页面。看到 Wiki 命中时，应继续检查：

- `status` 是否为 `active`、`provisional` 或 `stale`；
- 是否存在 `human_reviewed_at`；
- 页面指向哪些 Raw、Candidate 或其他证据；
- 适用的项目、版本和时间是否与当前任务一致。

如果任务只允许使用经过人审的内容，Agent 应明确筛选或在使用前逐页核对审核记录。目录位置和搜索排名都不能代替这一步。

## 状态表示什么

| 状态或字段 | 含义 |
|---|---|
| `active` | 页面处于正常使用状态；是否人审仍要看 `human_reviewed_at` |
| `provisional` | 暂定页面，可以参与普通 Recall，但不应称为已审核 |
| `stale` | 页面受到质疑或可能过时，使用前需要复核 |
| `dropped` | 页面退出普通 Recall，文件仍保留 |
| `superseded` | 页面已被新页取代，退出普通 Recall |
| `archived: true` | 页面被显式归档，退出普通 Recall |
| `human_reviewed_at` | 某个版本经过人工接受的记录，不是正确率或审核人身份的完整证明 |

执行 `oks wiki unarchive` 会把页面恢复为 `provisional`，不会自动恢复为 `active`，也不会补写一次人工审核。

## 修改知识时保留关系

发现新证据后，优先提出新的 Candidate，并说明它与旧页的关系：

| 关系 | 对旧页的处理 |
|---|---|
| `enriches` | 新页补充旧页，旧页继续保留 |
| `supersedes` | 新页取代旧页，旧页标为 `superseded` |
| `confirms` | 新页印证旧页，并更新相关元数据；不等于证明结论正确 |
| `challenges` | 新页质疑旧页，旧页标为 `stale` |

具体操作见[修订、替代与归档](../usage/maintain.html)。

## 其他目录不属于这条生命周期

- Profile 和 Goal 提供用户、项目和任务范围，不是 Raw 到 Wiki 的中间状态。
- Skill 保存 Agent 可执行的方法、脚本和资源，不是普通知识页。
- Mail、Trace 和 `records/` 保存协作、执行、审核和评测记录，不会自动变成 Wiki。
- “讨论”“目标”“学习”是 Studio 中组织工作的页面，不要求每次任务都依次使用，也不代表内容状态发生变化。

接着阅读[系统由哪些部分组成](architecture.html)，或按[收录材料](../usage/ingest.html)、[审核 Candidate](../usage/review.html)和[查询与引用](../usage/recall.html)完成一次实际操作。
