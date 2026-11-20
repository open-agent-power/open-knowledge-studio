---
title: 跨会话协作
nav_order: 4
parent: 工作原理
---

# 跨会话协作

OKS Mail 用来保存跨 Session、Agent、宿主或机器需要继续传递的协作信息。这里的 Session 是 Host 中的一次 Agent 会话；Mail Thread 是 OKS 把同一主题的消息串在一起形成的记录。它适合记录交接、结果、阻塞、批注和已有知识的引用，不是聊天系统、任务调度器或第二个知识库。

## 三类内容不要混在一起

| 内容 | 保存什么 | 不能据此认定什么 |
|---|---|---|
| Wiki 页面（`wiki/`） | 可查询的知识正文和元数据 | 位于 Wiki 不等于已经人工审核 |
| Candidate（`drafts/`） | 待审核提议及其来源 | 被发送或被查看不等于通过审核 |
| Mail（`mail/`） | 交接、结果、阻塞、批注和引用 | 已发送、已读不等于任务已执行或完成 |

Mail 应尽量引用已有 Wiki、Candidate、Raw 或 Trace，避免复制多份正文。需要长期保留的新结论仍应整理为 Candidate，再由人审核；一条交接消息不会自动变成知识。

## 一次交接应包含什么

- 当前目标和范围；
- 已完成的工作，以及能核对的产物；
- 实际运行过的验证和结果；
- `partial`、`failed`、`skipped` 等未完成状态；
- 阻塞原因、需要谁处理和下一步；
- 相关 Raw、Candidate、Wiki、Goal 或 Trace 的路径。

接收方应重新检查工作区和文件。交接内容可能已经过时，也可能只记录了发送方看到的状态。

## 在不同环境中继续

- **新 Session**：确认使用同一个知识库，再读取对应 Thread 或任务记录。
- **另一个 Agent**：接收方需要具备同一知识库的读取权限和相应 Skill。
- **另一台机器**：先通过团队约定的 Git 流程同步知识库；本地写入不会自动出现在远端。

Mail 命令可以发送、回复、读取、确认和归档消息。没有宿主适配或 Hook 时，新消息不会启动 Agent、创建 Session 或唤醒进程。

消息与 Thread 的字段见[Mail 协议](../reference/mail-protocol.html)，接入方式见[Mail 接入](../reference/mail-portable.html)。实际交接示例见 [oh-my-handoff](../oh-my/handoff.html)。
