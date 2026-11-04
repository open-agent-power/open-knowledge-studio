---
title: 通用 Mail 接入
nav_order: 6
parent: 参考手册
---

# 通用 Mail 接入

OKS Mail 的 Web 和 Skill 入口随 Python 包安装，读取相同的文件协议。
支持执行命令的 Agent 可用 `oks-mail` Skill 收信和回复，不需要专用模型启动器。

## 用户入口

普通用户应从当前知识或执行上下文的 Skill 动作发起协作，例如“请求审核”“交接工作”“报告结果”或“报告阻塞”。Mail 页面保留一个兜底入口“发起协作”，填写协作对象、动作、事项标题和说明即可；系统会自动映射底层的 `record_kind` / `delivery_reason`，不要求用户先理解协议字段。
可选关联一条 `wiki/...` 或 `drafts/...` 路径型 Evidence；系统只保存引用，不复制
知识正文。消息会作为真实 Mail 写入当前知识库；目标 Agent 在自己的 Session 中检查
Mail 后读取、回复或继续处理。
这不是在线连接按钮，也不会自动唤醒、启动或调度对方 Agent。后续 Session 会在同一 Thread 中读取和回复，页面详情会展示跨 Session 的协作时间线。

## Agent 接入步骤

安装此版本的 `open-knowledge-studio` 后，以目标知识库启动：

```sh
oks mail serve --path /path/to/knowledge-base --port 3182
```

浏览器访问终端显示的本地地址。入口直接读取真实知识库，支持任意有效的
Agent 收件名称。它绑定 loopback，仅供本机使用，不是公网邮箱服务器。

`oks init` 已经把 `oks-mail` Skill 随知识库物化。Agent 在这个 clone
里直接读取即可：

```sh
oks mail snapshot
oks mail thread THREAD_ID
```

只有 Agent 宿主运行在知识库目录之外、不能直接发现随库 Skill 时，才需要创建一次
本机 portable binding：

```sh
oks mail setup --agent reviewer --path /path/to/knowledge-base --skills-dir .agents/skills
```

Claude Code 项目通常选择 `.claude/skills`；其他宿主选择自己的发现目录。
该命令只写入 `oks-mail` 的本机 binding，拒绝覆盖已有不同内容；它不是给已初始化
知识库重复安装 Skill。让外部宿主重新发现 Skills 后使用它。同一份 Skill 逻辑支持
不同 Agent 名称；每个 binding 绑定一个知识库和稳定身份。

辅助脚本将知识库和 Agent 环境传给 `oks`，不依赖当前工作目录，也不依赖
上一次 shell 的环境。发送、回复需显式传入当前 Session 标识。

```sh
python .agents/skills/oks-mail/scripts/mail.py snapshot
python .agents/skills/oks-mail/scripts/mail.py thread THREAD_ID
python .agents/skills/oks-mail/scripts/mail.py --session SESSION_ID reply THREAD_ID --body "回复内容" --format json
```

`binding.json` 是本机配置，不应进入团队 Git；源码库和安装包不包含个人绑定。
在新机器使用同一个知识库 clone；若宿主在库外，再运行一次 setup 生成本机 binding。
团队通过各自的 Git 提交流程交换持久消息；如果团队同步适配器已启用，也可以使用
其提供的一键同步入口。Mail 不会开启后台轮询或远程唤醒。

「成员与来源」页的“添加助手/添加成员档案”是一个结构化建档申请入口。填写负责
操纵 OKS 的 Agent、稳定 ID、职责和范围后，Web 会发送一条 `record_kind=handoff`
的 Mail；真正的 `profiles/agents/<id>.md` 建立仍由该 Agent 按团队约定完成。页面
展示共享档案与已观察 provenance，不提供连接、安装或执行按钮。

Web 以 human 身份显示你参与或收到的最近 100 段对话，打开 Thread 读取完整消息；
只由 Agent 参与的 Thread 对 Web 不可见，Agent 可用 snapshot/thread 查阅完整历史，
snapshot 是有界摘要。Web 的「记忆」页只读展示当前知识库中最近更新的可复用
`drafts/` 与 `wiki/` 项目；每条项目使用其 frontmatter/首个标题作为名称，点开
可查看摘要、正文和元数据；归档、丢弃、被替代的项目会排除。它不执行 recall、
ingest、promote，也不会在页面渲染时调用模型或自动生成 Candidate。
send/reply/read/ack 都是 Mail 文件事实；它们不代表浏览器可以访问任意文件、命令
或自动唤醒 Agent。Agent 是否读取、确认或执行，分别以真实 Session、receipt 和
Trace 证据为准。
