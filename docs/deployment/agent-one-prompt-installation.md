---
title: 一键部署提示词
parent: 参考
nav_order: 7
---

# OKS Agent 一键部署与项目接管提示词

日期：2026-07-30

用途：把下面这段提示词交给一个新的 Agent，让它在当前环境中部署并接管 Open Knowledge Studio。目标是先把 OKS 跑起来、理解清楚、处理一个轻量文本到 Candidate 阶段，而不是扩展架构或全量测试组件。

## 可直接发送给 Agent 的提示词

```text
你需要在当前环境中部署并接管 Open Knowledge Studio。

## 目标

1. 完成 OKS 的最小可用部署。
2. 快速理解 OKS 的核心目标、架构、目录和工作流。
3. 验证一个最小知识闭环可以开始运行。
4. 不新增架构，不重复实现 Claude Code、OpenClaw 或现有插件已经具备的能力。

## 执行步骤

### 1. 了解项目

优先阅读：

* README.md
* docs/
* pyproject.toml 或 cli/pyproject.toml
* CLI 入口
* .claude/skills/
* .agents/skills/，如果存在
* 最近的 Git 提交

然后用简短文字说明：

* OKS 解决什么问题；
* 核心链路是什么；
* 哪些能力是核心，哪些是可选组件；
* 当前真实可用的 CLI、Skill 和插件；
* 当前最重要的未完成问题。

核心链路应理解为：

Source -> Raw -> Candidate -> Human Review -> Wiki -> Recall -> Agent Output

### 2. 检查环境

检查：

```bash
git --version
python --version
pipx --version
uv --version
oks --version
```

如果某个工具不存在，先判断它是否是部署 OKS 的必要条件。

缺少工具时，只安装部署 OKS 必需的最小依赖。

不要默认安装 PDF、OCR、ASR、视频、飞书、浏览器等重型组件。

### 3. 部署 OKS

如果当前目录是源码仓库，优先从当前源码安装。

优先尝试：

```bash
pipx install ./cli --force
```

如果项目实际使用其他安装方式，以 pyproject.toml、真实包结构和真实 CLI 为准。

安装后验证：

```bash
oks --version
oks --help
oks capability list
```

不要盲信旧文档中的命令。文档与真实 CLI 冲突时，以代码和 --help 为准，并记录文档问题。

### 4. 初始化隔离知识库

创建一个独立测试目录：

```text
<workspace>/oks-poc
```

执行真实可用的初始化命令，例如：

```bash
oks init <workspace>/oks-poc
```

设置：

```bash
OKS_ROOT=<workspace>/oks-poc
```

Windows PowerShell 使用：

```powershell
$env:OKS_ROOT = "<workspace>\oks-poc"
```

验证 Raw、Drafts、Wiki 等内容都写入该隔离目录，不得污染用户已有知识库、生产知识库、仓库根目录或宿主目录。

### 5. 最小验证

使用一个本地 Markdown 或 TXT 文件，验证：

```text
文本来源 -> Raw Bundle -> Candidate
```

优先使用本地临时文本，避免公网、反爬、PDF 或重型提取器干扰第一次部署。

如果 `oks ingest` 提示缺少 `document` 能力，可以安装最小文档能力：

```bash
oks capability install document --yes
```

必须记录 Raw Bundle 路径，并确认它位于 OKS_ROOT 下。

如果当前 CLI 不能自动生成 Candidate，Agent 可以基于 Raw 的 digest/content/evidence 手工生成一个最小 Candidate，写入 drafts/，但必须明确记录：

```text
Candidate 类型：Agent-authored
```

如果 Candidate 晋升需要人工审核，停在 Candidate 阶段并明确输出：

```text
awaiting_human_review
```

不得自动晋升 Wiki。

### 6. 优先复用现有能力

优先复用：

* Claude Code Skills；
* Claude Code Marketplace；
* OpenClaw Skill Hub；
* 项目现有脚本；
* 已安装的系统工具。

禁止重新设计：

* 插件市场；
* Skill Hub；
* Agent 框架；
* 工具注册中心；
* 分布式 Worker；
* Redis、消息队列或微服务。

遇到新设计想法时先判断：

它是否是部署 OKS 和跑通第一个知识闭环的必要条件？

不是则不要实现，只记录为后续事项。

## 最终输出

完成后输出一份简短报告：

```markdown
# OKS 部署与接管结果

- OKS 版本：
- Git 分支与 Commit：
- 安装方式：
- OKS_ROOT：
- 部署状态：
- 核心 CLI：
- 已识别的 Skills / 插件：
- 最小 Raw 是否生成：
- Raw Bundle 路径：
- Candidate 是否生成：
- Candidate 路径：
- 当前是否等待人工审核：
- 发现的文档或产品问题：
- 下一步唯一优先任务：
```

不要输出长篇架构设想。

本次成功标准是：

新 Agent 能在干净环境中完成 OKS 部署，理解项目核心链路，并将一个轻量文本处理到 Candidate 阶段。
```

## 当前验证状态

状态：`passed_with_findings`

说明：

* 远端干净服务器已经证明核心 CLI 部署和最小闭环可跑通。
* 测试中发现过 Raw 写入宿主目录的问题，后续已修复并复验。
* OpenClaw 自主读取提示词并全自动执行未证明通过，因此不要宣传为“所有 Agent 全自动部署通过”。

证据：

* `records/acceptance/clean-server-deployment-report.md`
