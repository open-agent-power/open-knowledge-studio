---
title: 参考手册
nav_order: 6
has_children: true
---

# 参考手册

遇到问题，先把现象交给 Agent：

```text
请查阅 OKS 的相关说明，帮我定位这个问题。
先确认当前知识库和可用能力，再说明原因、处理办法与未完成项。
```

下面的命令和协议主要供 Agent、开发者查阅。日常操作可以直接使用[日常任务](../usage/)里的提示词。

| 要查什么 | 文档 |
|---|---|
| 命令、过滤参数、VFS、Hook 与 Trace | [CLI 参考](cli.html) |
| 来源、证据和 Raw Bundle 的数据结构 | [摄入协议](ingest.html) |
| 安装、收录或召回失败 | [故障排除](troubleshooting.html) |
| 保存副本与导出知识 | [备份与导出](../connect/backup-export.html) |
| 消息、Thread 和读取回执的字段 | [Mail 协议](mail-protocol.html) |
| 在本机宿主中收信、回复与查看知识 | [Mail 接入](mail-portable.html) |

让 Agent 核对当前安装版本和实际可用能力，再按对应说明操作。

## 可选集成

- **[WorkBuddy 接入](../connect/workbuddy.html)**：通过本地 Agent Skill 查询已审核知识。
- **[飞书参考实现](https://github.com/open-agent-power/open-knowledge-studio/tree/main/reference-implementations/oh-my-feishu)**：提供手机采集与移动审核入口，不随 CLI 分发。Agent 起草候选，人决定接受、修改或拒绝，worker 仅执行已发生的决定。凭据和调度由外部环境管理，不改变知识审核规则。

实现与贡献约束见[维护者文档](../maintainers/)。
