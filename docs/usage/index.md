---
title: 日常任务
nav_order: 3
has_children: true
---

# 日常任务

你可以直接说明要完成的工作，让 Agent 选择相应的 Skill 和 CLI 命令。开始前先确认当前知识库，结束后查看实际写入的文件、状态和记录。

```text
请确认当前 OKS 知识库，并根据我的任务先查询已有内容。
需要写入时，说明准备保存为 Raw、Candidate、Wiki、Profile 还是 Goal；
完成后展示文件位置、状态、来源和仍未完成的部分。
```

## 按任务选择

| 你要做什么 | 先读哪一页 |
|---|---|
| 保存网页、文件、视频或一段文本，并保留出处 | [收录材料](ingest.html) |
| 检查 Agent 整理出的提议，决定接受或拒绝 | [审核 Candidate](review.html) |
| 在新任务中查找并使用已有内容 | [查询与引用](recall.html) |
| 修订、替代、质疑或归档旧知识 | [修订、替代与归档](maintain.html) |
| 保存用户、项目背景和当前任务范围 | [Profile 与 Goal](profiles.html) |
| 从旧聊天中提取项目决定和经验 | [导入对话](../import-conversations.html) |
| 在网页中查看讨论、目标、知识关系和评测 | [本地 Studio](studio.html) |
| 备份知识库或导出 Wiki 快照 | [备份与导出](../connect/backup-export.html) |

## 判断操作是否完成

不要只看 Agent 是否回复“已完成”。至少检查以下内容：

- 当前使用的是哪个知识库；
- 新增或修改了哪些文件；
- 内容属于 Raw、Candidate、Wiki、Profile、Goal 还是过程记录；
- Candidate 是否针对你看过的具体版本做出决定；
- Wiki 是否有 `human_reviewed_at`，当前 `status` 是什么；
- `partial`、`failed`、`skipped` 是否被如实保留；
- Agent 实际采用了哪些查询结果，以及这些内容怎样用于任务。

第一次使用从[第一次实践](../first-knowledge-loop.html)开始。命令失败时，保留原始错误并按[故障排除](../reference/troubleshooting.html)定位。
