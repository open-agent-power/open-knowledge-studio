---
title: 参考手册
nav_order: 6
has_children: true
---

# 参考手册

需要准确的命令、协议或接入步骤时，在这里查找。

| 要查什么 | 文档 |
|---|---|
| 命令、过滤参数、VFS、Hook 与 Trace | [CLI 参考](cli.html) |
| 来源、证据和 Raw Bundle 的数据结构 | [摄入协议](ingest.html) |
| 安装、收录或召回失败 | [故障排除](troubleshooting.html) |
| 保存副本与导出知识 | [备份与导出](../connect/backup-export.html) |
| 消息、Thread 和读取回执的字段 | [Mail 协议](mail-protocol.html) |
| 在本机宿主中收信、回复与查看知识 | [Mail 接入](mail-portable.html) |

命令以当前安装版本的 `oks --help` 为准，处理能力以 `oks capability status` 为准。

## 可选集成

- **[WorkBuddy 接入](../connect/workbuddy.html)**：通过本地 Agent Skill 查询已审核知识。
- **[飞书参考实现](https://github.com/open-agent-power/open-knowledge-studio/tree/main/reference-implementations/oh-my-feishu)**：提供手机采集与移动审核入口，不随 CLI 分发。Agent 起草候选，人决定接受、修改或拒绝，worker 仅执行已发生的决定。凭据和调度由外部环境管理，不改变知识审核规则。

实现与贡献约束见[维护者文档](../maintainers/)。
