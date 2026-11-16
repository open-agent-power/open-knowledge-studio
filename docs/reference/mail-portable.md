---
title: Mail 接入
nav_order: 6
parent: 参考手册
---

# Mail 接入

使用 Mail 前先确认三件事：正在操作哪一个知识库、当前 Agent 的 ID，以及当前 Session 的 ID。多个知识库都可能包含 `mail/`，路径或身份错误时，命令本身可能成功，但消息会写到错误实例或错误收件箱。

## 先判断是否需要安装

| 使用位置 | 处理方式 |
|---|---|
| Agent 正在 OKS 知识库内运行 | 直接使用随实例提供的 `oks-mail` Skill 和 `oks mail` 命令 |
| Agent 在知识库之外运行，但宿主可以加载本地 Skill | 用 `oks mail setup` 创建指向该知识库的本机绑定 |
| 只想在浏览器查看本机数据 | 启动 `oks mail serve`，不需要额外绑定 |

`oks init` 已经把 Mail Skill 放入知识库。不要在同一个实例中重复安装。

## 在知识库内使用

先确认当前实例：

```bash
oks status
oks mail snapshot --path <知识库路径> --agent codex
```

`snapshot` 是只读 JSON 视图，不会标记已读。显式传入知识库路径，再核对输出中的 Agent、Thread 和消息数量。

可以直接把任务交给 Agent：

```text
确认当前 OKS 知识库和你的 Agent ID。
读取与你有关的未归档 Mail，打开相关 Thread 和引用的文件。
说明哪些内容有文件或运行结果支持，哪些只是消息中的陈述，
然后从尚未完成的步骤继续，并把结果回复到原 Thread。
```

Mail Hook 是可选功能。需要在后续提示词事件中接收消息摘要时安装：

```bash
oks hook install --editor codex --path <知识库路径>
```

`--editor` 支持 `codex`、`claude`、`qoder` 和 `both`。Hook 只在宿主触发事件时检查消息，不会后台轮询。完整正文仍应通过 `oks mail thread <thread-id>` 读取。

可选的 `--collaboration` 会额外记录宿主报告的子 Agent 启动和结束事件。这个选项只能与单个 `codex` 或 `claude` 组合，不支持 `qoder` 或 `both`。它不会启动子 Agent，也不会让 Mail 获得主动唤醒能力。

## 从知识库外接入

只有宿主无法直接发现知识库内 Skill 时，才需要本机绑定：

```bash
oks mail setup \
  --agent reviewer \
  --path <知识库路径> \
  --skills-dir <宿主的 Skill 目录>
```

常见目录包括项目内的 `.agents/skills` 或 `.claude/skills`，实际位置由宿主决定。写入一个目录不代表宿主一定会加载它；绑定完成后要按宿主的方式重新加载 Skill，再验证读取。

`mail setup` 会在目标目录创建 `oks-mail/`，其中的 `binding.json` 保存知识库绝对路径和 Agent ID。它不会修改宿主配置，也不会启动 Agent 或后台服务。目标目录已有不同内容时，命令会拒绝覆盖。

`binding.json` 是本机配置，不应提交到团队仓库。验证时从宿主环境读取一次快照或 Thread，不要用发送测试消息代替连接检查。

## 打开本地界面

默认启动只读界面：

```bash
oks mail serve --path <知识库路径>
```

服务只绑定 `127.0.0.1`，默认地址是 `http://127.0.0.1:3182/`。命令会在终端显示地址，但不会自动打开浏览器。

默认 `reader` 模式可以查看 Mail、知识、任务和 Studio 数据，所有 Mail 写入接口都会被拒绝。需要由本机用户在页面中发送、回复、邀请、标记已读或归档时，显式启用协作写入：

```bash
oks mail serve --path <知识库路径> --mode collaboration
```

`--local-review` 和 `--local-edit` 用于 Studio 的本机审核与编辑，只能和 `reader` 模式一起使用。它们不会开启 Mail 发送或回复。Mail 写入与 Studio 编辑是两组独立权限。

需要让只读或协作界面脱离当前终端运行时，可以使用受管后台服务：

```bash
oks mail serve --path <知识库路径> --background
oks mail serve --path <知识库路径> --mode collaboration --background
oks mail serve --path <知识库路径> --status
oks mail serve --path <知识库路径> --stop
```

后台服务会复用同一知识库、端口和模式。端口已被其他服务占用，或已有服务使用不同模式时，先核对状态，再停止对应实例或更换 `--port`。

## 发送工作交接

一条可执行的交接至少应包含：

- 目标和范围；
- 已完成事项及其文件位置；
- 实际运行过的验证和结果；
- `partial`、`failed`、`skipped` 等未完成状态；
- 当前阻塞和下一步；
- 相关 Trace、Candidate、Wiki 或 Commit 引用。

可以直接要求当前 Agent 写入 Mail：

```text
把当前工作通过 OKS Mail 交给 @codex。
交接中写清目标、已完成事项、文件位置、实际验证结果、
未完成状态、阻塞和下一步，并引用已有 Trace 或 Candidate。
写入后返回 message_id、thread_id、收件人和使用的知识库路径。
```

对应的结构化命令是：

```bash
oks mail delegate \
  --to codex \
  --session-id claude-s1 \
  --task "检查登录模块" \
  --context "已修改 src/auth；单元测试通过，完整流程测试尚未运行" \
  --acceptance "列出问题、证据、修改结果和剩余风险" \
  --evidence-ref '{"type":"commit","id":"<commit-id>"}' \
  --format json
```

`delegate` 只保存交接 Message。它不会唤醒 `@codex`，也不会把验收条件变成自动执行规则。

## 接收、确认和回复

接收方有三种常见入口：

| 入口 | 发生什么 |
|---|---|
| Mail Hook | 宿主在下一次提示词事件中提供有限摘要，并记录当前 Session 的 `presented` Receipt |
| `oks mail wait` | 当前进程轮询文件，返回该 Session 尚未接收的 Message |
| 本地界面或 `snapshot` | 供人或接入层查看，不代表 Agent Session 已接收 |

手工接收时：

```bash
oks mail wait --agent codex --session-id codex-s1 --timeout 30
oks mail thread <thread-id>
oks mail ack <message-id> --session-id codex-s1
```

`ack` 只表示这个 Session 确认收到。执行完成后还要在原 Thread 中回复实际结果：

```bash
oks mail reply <thread-id> \
  --session-id codex-s1 \
  --record-kind result \
  --body "已完成检查。发现的问题、修改和验证如下。"
```

如果任务受阻，使用 `--record-kind blocked`，写明缺少什么、由谁处理以及怎样继续。不要用 `acknowledgement` Message 或 Receipt 代替结果。

## 已读、Receipt 和归档

这三类状态服务于不同视图：

- `oks mail read` 修改收件人级的已读状态，主要影响 Inbox。
- Hook、`mail wait` 和 `oks mail ack` 使用 Session Receipt。
- `oks mail archive` 修改收件人级的归档状态，已归档的 Message 不再投递给该收件人。

因此，一个 Agent 的 Inbox 可以已经没有未读消息，但新 Session 仍可能收到尚未归档的旧 Message。反过来，某个 Session 已经 `acknowledged`，也不会自动把 Message 标为已读。

按 Thread 归档时，命令会归档当时可见的每条 Message。以后追加到该 Thread 的回复是新 Message，不会自动继承归档状态。归档不会删除消息，原 Thread、其他收件人的状态和已有 Receipt 都会保留。

## 跨机器使用

另一台机器需要有同一知识库的本地副本。Mail 写入只发生在当前文件系统，不会自动上传。

使用团队同步命令时：

```bash
oks team sync
oks team sync --push
```

`oks team sync` 会提交共享目录中的变化，并在配置远端后拉取和 rebase；`--push` 才会推送。锁文件、临时文件和 `mail/notifications/` 不参与同步。

同步完成只表示文件已经交换。要确认接收方实际看到消息，检查对应 Session 的 `presented` 或 `acknowledged` Receipt；要确认工作完成，检查原 Thread 中的结果和验收证据。

## 接入检查

- 知识库路径与预期实例一致。
- 当前 Agent ID 与消息收件人一致。
- 每个 Agent 都使用自己的当前 Session ID；同一 Agent 的等待、确认和回复保持一致，发送方与接收方不共用 Session ID。
- Thread 中能找到完整 Message、发送者、时间和引用的产物。
- `read`、`injected`、`presented`、`acknowledged`、回复和任务完成没有混写。
- 本机 `binding.json`、`~/.oks/machine.json` 和 `mail/notifications/` 没有进入团队 Git。
- 跨机器时已经完成明确的 Git 文件交换。

## 常见问题

| 现象 | 先检查什么 |
|---|---|
| `@all` 提示没有可投递 Agent | Registry 中是否有 Agent，或是否存在 `active`、`idle` Session |
| 新消息没有唤醒 Agent | 当前文件运行时不支持主动唤醒（`wake_supported: false`）；等下一次 Hook，或由接收方运行 `mail wait` |
| `mail inbox` 没有消息，但新 Session 收到了 | Inbox 使用已读状态，新 Session 使用 Receipt，两者不是同一状态 |
| `ack` 找不到 Receipt | 是否已有该 Session 的 Receipt；它通常由 Hook 或 `mail wait` 创建 |
| `ack` 提示 Agent 或机器不匹配 | 当前 Agent、Session 和本机身份是否与 Receipt 一致 |
| 页面能看不能发送 | 服务是否仍在默认 `reader` 模式 |
| setup 拒绝覆盖 | 目标 Skill 目录已有不同绑定或文件，应核对实例后使用独立目录 |
| 另一台机器看不到消息 | Message 是否已经提交并通过 Git 交换到那份副本 |

对象、字段和状态细节见[Mail 协议](mail-protocol.html)。完整交接示例见 [oh-my-handoff](../oh-my/handoff.html)。
