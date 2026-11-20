---
title: Profile 与 Goal
nav_order: 5
parent: 日常任务
---

# Profile 与 Goal

Profile 保存较稳定的用户或项目背景，Goal 保存当前要完成的工作和验收条件。它们为 Agent 和 Recall 提供范围，不是 Raw、Candidate、Wiki 生命周期的一部分。

## 什么时候使用

| 对象 | 适合保存什么 | 不适合保存什么 |
|---|---|---|
| User Profile | 职责、长期偏好、明确边界 | 单次聊天中的临时选择、未经确认的推断 |
| Project Profile | 项目目标、技术背景、版本约束、团队规则 | 整个源码副本、短期任务进度 |
| Goal | 当前任务、完成条件、下一步和必要范围 | 已经结束但仍标为当前的旧任务 |
| 讨论 | 问题、人的判断、Agent 理解和待确认项 | 经过审核的长期知识正文 |

```text
请整理我的项目背景和当前 Goal。先区分长期背景与本次任务，
标出我明确提供的事实和你仍需确认的内容，展示草稿后再保存。
不要把临时聊天自动写成长期偏好。
```

## 一个具体示例

```text
我负责一个中文开源项目的文档，读者主要是第一次使用 OKS 的人。
当前 Goal 是让读者完成安装，并理解 Raw、Candidate、Wiki 和 Recall 的区别。
完成条件是入口页、安装页和第一次实践能按顺序读通，命令与当前源码一致。
本轮只修改公开文档，不发布网站。
```

Agent 应把稳定背景放入对应 Profile，把本轮工作和验收条件放入 Goal。路径通常位于 `profiles/users/`、`profiles/projects/` 和 `profiles/goals/YYYY/MM/DD/`。

## Profile 怎样参与 Recall

Raw 和当前范围内的 Profile 位于 Recall 的 `episodic` 通道。用户 Profile 需要明确当前用户，项目 Profile 需要明确当前项目；这用于避免无关或私有背景进入其他任务。

Goal 可以为查询提供当前任务范围，并影响相关页面的排序。它不会：

- 把 Candidate 变成 Wiki；
- 把 `provisional` 页面变成已审核页面；
- 证明某条搜索结果已经被 Agent 使用；
- 自动执行 Goal 中列出的步骤。

## 更新与停用

职责、项目版本或工作方向变化时，更新对应 Profile 或 Goal。任务结束后不要继续把旧 Goal 当作当前范围。团队背景需要由有权确认的人维护，模板和 Agent 推断不能直接当作团队事实。

## 完成后检查

- 长期背景和当前 Goal 分开保存。
- 没有把密钥、Cookie 或不必要的私人信息写入 Profile。
- 推断和待确认项没有被伪装成用户声明。
- Goal 有清楚的完成条件，并在结束或变化时更新状态。
- Agent 能说明本次查询使用了哪些 Profile 和 Goal。

Studio 中怎样查看讨论和目标，见[本地 Studio](studio.html)。任务在 Session 之间继续时，可结合[跨会话协作](../concepts/product-boundary.html)。
