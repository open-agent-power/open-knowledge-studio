---
title: 安装与创建知识库
nav_order: 1
parent: 开始使用
---

# 安装与创建知识库

本页把接入过程拆成四部分：安装 CLI、选择知识库、安装 Skill，以及决定是否配置团队库、Hook 或 Studio。前两项是使用 OKS 的基础；Skill 用于让 Agent 按 OKS 的规则操作，其他功能可以以后再配置。

Agent 是当前执行安装检查、运行命令并操作知识库的主体。可以把下面的要求交给 Agent，也可以根据[CLI 参考](reference/cli.html#手工安装)手工执行。

```text
请按 https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md 检查并接入 OKS。
先检查本机是否已有 oks CLI 和个人知识库，不要覆盖现有配置。
缺少 CLI 时安装它；已有知识库时优先沿用，没有时再创建一个。
安装适合当前宿主的 OKS Skill，并报告 CLI、Skill 和知识库的实际位置。
团队知识库和 Hook 暂不启用，只说明当前是否支持以及以后怎样配置。
```

## 1. 安装或检查 CLI

`oks` CLI 提供知识库初始化、状态检查、材料保存、审核记录和 Recall 等确定操作。Agent 应先检查当前环境，再选择合适的安装方式。当前项目要求 Python 3.12 或更新版本，并在需要版本管理或团队同步时使用 Git。

安装完成后，至少确认下面的命令可以运行：

```bash
oks --help
```

如果机器上已有 OKS，应先确认版本和来源，不要直接用另一份安装覆盖。安装失败时保留原始错误，再查[故障排除](reference/troubleshooting.html)。

## 2. 选择或创建知识库

知识库是一个独立文件夹，用于保存个人的 Raw、Candidate、Wiki、Profile、Goal 和运行记录。它不应长期放在 OKS 工具源码仓库中。

已有知识库时，先让 Agent 报告它的位置并运行状态检查。没有知识库时，可以创建一个新的实例：

```bash
oks init <知识库路径>
```

进入知识库目录后运行：

```bash
oks status
```

验收时应看到当前知识库的明确路径和可读取状态。新建知识库中没有 Wiki 是正常情况，安装验收不需要临时创建或批准知识。

如果需要在其他工作目录中调用同一个知识库，可以设置默认路径或显式使用 `OKS_ROOT`。路径解析顺序和配置方法见[CLI 参考](reference/cli.html)。

## 3. 让 Agent 获得 OKS Skill

Skill 是给 Agent 阅读的操作说明，可附带脚本和资源。它告诉 Agent 怎样收录材料、怎样生成 Candidate、什么时候必须等待人工决定，以及怎样执行 Recall。Skill 本身不保存知识，也不会在后台自动运行。

使用 Agent 操作 OKS 时，建议安装随 OKS 发布的 Skill。如果 Agent 在当前知识库目录中工作，先进入知识库根目录，再运行：

```bash
oks skills-install
```

这会把随包发布的核心 Skill 写入当前知识库中受支持的 Agent 目录。如果希望在知识库以外的工作目录也能调用 OKS，可以只为一个宿主安装全局 `oh-my-oks` 入口：

```bash
oks skills-install --global --editor codex
# 或将 codex 改为 claude / agents
```

验收时，让 Agent 说明它实际读取的 OKS Skill 路径、当前宿主，以及当前知识库位置。安装了 Skill 不表示已经执行过收录、审核或查询。

只打算手工使用 CLI 时可以不安装 Skill，但需要自己遵守 Raw、Candidate 和人工审核之间的边界。

## 4. 决定是否启用可选功能

团队知识库、Hook 和 Studio 都不影响第一次实践，可以以后再配置。

| 可选功能 | 何时需要 | 启用前确认什么 |
|---|---|---|
| 团队知识库 | 需要读取或贡献团队维护的知识 | 本地目录或 Git 来源、读取版本、同步方式和权限 |
| Hook | 希望宿主在提问时自动 Recall 或在工具调用后检查冲突 | 当前宿主是否支持、安装位置、触发时机和关闭方法 |
| Studio | 希望用本地网页查看讨论、目标、图谱和评测记录 | 当前知识库路径，以及是否需要本地编辑权限 |

关联团队库不会自动拉取远端更新，也不会把个人库和团队库合并。Hook 未启用时，仍可直接要求 Agent 运行 Recall。Studio 是操作界面，不代替 Agent 执行任务。

## 接下来检查一次完整流程

完成本页后，你应能回答三个问题：

1. `oks` CLI 从哪里运行，基本命令是否可用？
2. 当前个人知识库的实际路径是什么？
3. 当前 Agent 是否加载了 OKS Skill，还是由你手工操作 CLI？

确认后，进入[第一次实践](first-knowledge-loop.html)。教程会使用同一个知识库完成 Raw、Candidate、人工审核、Wiki 和 Recall，不要求先配置 Hook 或团队库。
