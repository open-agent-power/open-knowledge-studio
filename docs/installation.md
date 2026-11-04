---
title: 安装与创建知识库
nav_order: 1
parent: 开始使用
---

# 安装与创建知识库

本页完成环境准备，并创建一个保存个人知识的独立目录。已有知识库时，先让 Agent 检查并连接它。

## 准备什么

- Python 3.12 或更新版本、Git；推荐通过 `pipx` 隔离安装。
- 能阅读文件、访问安装说明并执行本机命令的 Agent，例如编码 Agent。只有聊天能力的界面无法自行完成安装。
- 一个知识库目录，与 OKS 源码仓库分开。已有资料不要直接放进源码仓库。

## 交给 Agent

将下面这段话交给你正在使用的 Agent：

> 请阅读并按照 [OKS 安装 Skill](https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md) 操作。先检查本机环境和已有知识库；没有实例时，为我的个人知识创建独立目录。完成后报告实例位置、已安装的 Skill、可用能力和失败项。不要为了验收创建或批准知识。

安装完成后，让 Agent 确认它正在使用哪个实例，并报告 `oks status` 与 `oks capability status` 的结果。新实例的长期知识为空是正常状态。

自动召回 Hook 按需开启；首次教程可以直接要求 Agent 查询，无需先配置 Hook。

<details markdown="1">
<summary>手工安装</summary>

先确认 Python 版本，并准备好 `pipx`。新安装使用：

```bash
pipx install open-knowledge-studio
pipx ensurepath
```

重新打开终端，在你准备保存知识的上级目录执行：

```bash
oks init my-knowledge-base
cd my-knowledge-base
oks status
oks capability status
```

初始化会同时提供 Agent Skill。让 Agent 读取实例内的 `.agents/skills/`；不要立即重复运行 `skills-install`。更新已有实例请遵循安装 Skill，先检查本地修改。

</details>

命令无法运行时，查看[故障排除](reference/troubleshooting.html)。准备好后，进入[第一次知识循环](first-knowledge-loop.html)。
