---
title: 产品边界与协作模型
nav_order: 3
parent: 工作原理
---

# 产品边界与协作模型

- 状态：Accepted
- 日期：2026-09-16
- 范围：OKS 产品定位、知识复利、Mail 协作事实和跨执行边界

## 一句话定位

> **知识闭环是主产品，Mail 是协作侧车，Agent/Skill 是执行与编排者，Trace 是证据，Git 是传输，UI 是投影。**

OKS 的价值不是增加一个聊天窗口，而是让一次真实任务产生的、经过证据和人审的判断，在下一次任务中可召回、可复用、可修正。

```text
Raw → Candidate → 人工审核 → Wiki → Recall → 真实任务使用
                                                  ↓
                                      明确反馈 → Candidate
```

行为日志、Mail 阅读记录或“使用过一次”都不会自动变成 Wiki 或 Candidate；新的知识提议必须由人或 Agent 明确提交，并继续经过原有审核门。

## Mail 的职责

Mail 只保存需要跨 Session、跨 Agent 或跨机器留下的协作事实：交接、结果、阻塞、批注、重要消息和知识引用。它不是第二知识库、任务引擎、聊天替代品、实时总线或 Agent 控制台。

Mail 的事实对象只有一套：

```text
Message       已发生或明确提出的协作事实
Thread        Message 的持久主题边界和详情上下文
Session       一次具体 Agent 运行
Receipt       某个 Session 是否呈现/确认消息的证据
Evidence Ref  指向现有 Wiki、Candidate、Trace 等产物的相对引用
```

Thread 不承担任务状态机。`record_kind` 只描述记录本身的事实分类：
`message`、`handoff`、`result`、`blocked`、`note`、`knowledge_ref`。投递原因由
`delivery_reason` 单独描述；不要把 `draft_created`、`review_passed` 或
`wiki_promoted` 塞进 Mail，它们属于 Candidate、Wiki 或 Trace 的生命周期。

## 三种通信边界

同一套 Message、Thread、Receipt 和 Evidence Ref 支持三种接力，不要求每种接力都实现实时唤醒：

| 边界 | 例子 | Agent 如何读取 | 这轮的保证 |
| --- | --- | --- | --- |
| Session 内部 | 同一 Agent 从 Session A 交给 Session B | 新 Session 的 Hook、`oks mail snapshot` 或 `oks mail wait` | 共享稳定 Agent ID；Receipt 按 Session 记录 |
| Agent / Host | Claude、Codex、DSH 之间交接 | 各 Host Adapter 读取同一 KB 的 Mail；适配器可呈现、ack、reply | 统一协议和 provenance；不保证对方进程已启动 |
| Machine / Team | 电脑 A 到电脑 B | 两台 clone 按团队 Git 流程 fetch/merge/push 后读取文件 | 可迁移、可审计、可合并；不保证对方已读取 |

因此，Mail 的“发送成功”只表示 canonical Message 已写入当前知识库（或已进入明确的 Git 提交流程）。没有 Host wake adapter 时，它不会启动进程、唤醒 Agent、创建 Session 或保证任务执行。

## Agent 档案、连接和验证

`profiles/agents/<id>.md` 是团队共享的角色档案：职责、范围、输入输出和协作边界。它不是在线状态、权限授予或运行时连接。机器本地的 binding、Session registry 和 machine ID 属于运行 provenance，不应提交为团队成员名册。

状态要分开表达：

- **未验证**：只有配置或档案声明，没有运行证据；
- **已观察**：出现过真实 Agent、Session 或 Machine provenance；
- **Mail 已验证**：至少有一次真实 Mail 生命周期证据（呈现后 ack，或同一 Thread 产生回复）。

这些状态都不等价于在线、可达、可调用、能执行或任务完成。Host 执行能力必须由独立 Adapter capability 证据表示。

## 用户入口

用户不应先学习 `thread_id`、`@agent-id`、Session ID 或文件路径。Mail 动作应从当前上下文进入：在 Wiki 页面发起“请求审核”，在 Candidate 页面发起“交接/补充”，在 Trace 或结果页发起“报告阻塞/结果”。Mail 页面保留兜底的“发起协作”，让用户选择对象、动作和说明；底层字段由 Adapter 映射。

页面只能展示真实事实、Evidence、来源和 Receipt，并把 Thread、Session、Machine 和协议 ID 放到详情。发送、回复、ack 是通信事实，不是执行按钮。

## 明确非目标

本边界不引入：Mail → ingest、自动 Candidate、行为日志自动转知识、后台 Git sync、实时 presence、自动 Session continuation、远程唤醒或把浏览器变成 Agent 启动器。未来若加入这些能力，必须作为独立 Host Adapter/运行时能力定义目标、权限、超时、失败和回滚，并重新审核产品合同。
