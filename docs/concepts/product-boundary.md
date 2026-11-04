---
title: 协作边界
nav_order: 3
parent: 工作原理
---

# 协作边界

Agent 负责执行与编排，OKS 保存材料、候选和知识，人决定哪些候选进入 Wiki。跨会话或不同 Agent 交接时，Mail 保存需要留下的协作记录。

## 各自负责什么

| 部分 | 职责 |
|---|---|
| Wiki 与 Candidate | 保存长期知识和待审核提议 |
| Mail | 保存交接、结果、阻塞、批注和知识引用 |
| Trace | 记录执行过程与证据 |
| Git | 按团队流程传输和版本化文件 |
| Host Adapter | 将知识与消息呈现给具体宿主中的 Agent |

Mail 引用已有知识，不复制知识正文。一次发送、读取或回复只是一条通信事实，不代表任务已经执行或完成。

## 交接怎样继续

- **跨会话**：后续 Session 读取同一 Agent 身份下的消息，查看已有上下文再继续工作。
- **跨 Agent 或宿主**：各自的适配器读取同一知识库，使用同一 Thread 回复或补充。
- **跨机器**：按团队 Git 流程交换文件后，另一台机器再读取记录。

Message 保存消息，Thread 组织同一主题，Receipt 记录某个 Session 的呈现或确认。字段与命令见 [Mail 协议](../reference/mail-protocol.html)和 [Mail 接入](../reference/mail-portable.html)。

## 哪些状态需要区分

共享 Agent 档案描述角色和范围；机器本地 binding 描述本机连接配置；Session 和 Receipt 记录实际出现过的运行与通信。它们都不单独证明 Agent 在线、可调用或能够执行任务。

没有独立的 Host wake adapter 时，Mail 不启动进程、创建会话或保证执行。消息和行为日志也不会自动形成候选或进入 Wiki；新的知识提议仍需明确提交并由人审核。
