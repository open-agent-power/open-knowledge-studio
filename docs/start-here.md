---
title: 从这里开始
nav_order: 1
parent: 开始使用
---
# 从这里开始

OKS 把一份资料变成以后还能使用的知识，同时保留来源和人的最终判断。

```text
资料 → Candidate → 人工审核 → Wiki → Recall
```

你不需要先理解 Provider、Manifest 或评分公式。第一天只完成一次真实闭环。

## 选择第一条路径

### 我正在使用 Agent

这是推荐路径。完成[安装](installation.md)后，在 Claude Code、Codex 或兼容
Agent 中，把一份你真正想保存的资料交给它：

> 把这份资料收录到 OKS，生成 Candidate 后停下来让我审核。

Agent 会读取 `/ingest` Skill、选择可用能力、保存证据并生成 Candidate。

### 我现在只有终端

可以先创建知识库并检查环境：

```bash
oks init ./my-knowledge-base
cd ./my-knowledge-base
oks status
oks ingest prepare <文件或URL>
```

`prepare` 只创建 Run Workspace，不会调用 Agent。纯 CLI 可以查看和维护知识库，
但不会替你完成语义理解或 Candidate 判断。

## 接下来

- 尚未安装：前往[安装](installation.md)。
- 已完成安装：开始[第一个知识闭环](first-knowledge-loop.md)。
- 已经尝试过：用[确认 OKS 正在工作](verify.md)定位失败环节。
