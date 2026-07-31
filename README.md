# Open Knowledge Studio

A file-based knowledge workspace for Claude Code and compatible Agents.

OKS helps Agents turn sources into reviewed, traceable and recallable knowledge.

```text
Source -> Raw -> Candidate -> Human Review -> Wiki -> Search / Recall -> Agent Output
```

[English](#english) | [中文](#chinese)

---

<a id="english"></a>

## English

### What is this?

Open Knowledge Studio is a lightweight knowledge engineering workspace for AI Agents.

It gives Agents a stable file-based memory layer, so project knowledge, source materials, failure lessons and human decisions can be reused across sessions instead of being explained from scratch every time.

The core idea is simple:

* `Raw` keeps original materials and evidence.
* `Candidate` is knowledge proposed by an Agent.
* `Human Review` decides whether the Candidate is accepted.
* `Wiki` stores reviewed knowledge.
* `Search / Recall` brings that knowledge back into future Agent work.

Agents may write Candidates. Humans approve Wiki.

### Quick Start

Requirements:

* Python >= 3.12
* Git
* pipx

Install:

```bash
# Normal users — from PyPI
pipx install open-knowledge-studio

# Developers — from local checkout
pipx install ./cli --force

# From Git (anyone)
pipx install "git+https://github.com/open-agent-power/open-knowledge-studio.git#subdirectory=cli" --force

oks --version
```

Create a workspace:

```bash
oks init ./my-knowledge-base
export OKS_ROOT=./my-knowledge-base
oks status
```

Ingest a source:

```bash
oks ingest ./sample.md --mode quick --progress
oks drafts list
```

After human approval:

```bash
oks drafts promote <slug>
oks search "agent memory"
oks recall "how should agent memory be managed?" --goal none --format table
oks lint
```

### Core CLI

```text
oks init
oks ingest
oks drafts
oks wiki
oks search
oks recall --goal --format --explain
oks eval
oks trace
oks lint
oks status
oks capability
```

### Optional Capabilities

OKS keeps the core lightweight. Heavy capabilities are installed only when needed.

| Capability | Purpose |
|---|---|
| `document` | Office (docx/pptx/xlsx), HTML, CSV — .md/.txt 开箱可用，无需安装 |
| `pdf` | PDF extraction |
| `formula` | Formula and OCR-related extraction |
| `watch` | Video, audio and subtitle extraction |
| `feishu` | Optional Feishu Base / form / review workflow |

Feishu and heavy extractors are optional. They are not required for the core knowledge loop.

### Agent Philosophy

OKS is Claude Code-first, but not Claude Code-only.

It should work with any Agent that can read files, run commands and follow project rules.

Before adding new infrastructure, reuse existing capabilities:

* Claude Code Skills
* Claude Code Marketplace
* OpenClaw Skill Hub
* mature extractors and CLI tools

Do not build a new platform when an existing Agent tool can already do the job.

### Documentation

* [Core Architecture](docs/architecture/oks-core-architecture.md)
* [Agent One-Prompt Installation](docs/deployment/agent-one-prompt-installation.md)
* [Clean Server Deployment Report](docs/acceptance/clean-server-deployment-report.md)
* [Feishu E2E Status](docs/acceptance/feishu-e2e-status.md)
* [Platform Anti-bot and Lightweight Deployment Research](docs/research/platform-antibot-and-lightweight-deployment.md)
* [Kimi K3 Case Study](docs/cases/kimi-k3-deep-analysis.md)

### License

MIT

---

<a id="chinese"></a>

## 中文

Open Knowledge Studio 是一个面向 Claude Code 和兼容 Agent 的文件式知识工作区。

它让 Agent 把外部资料、项目经验、失败教训和人工判断沉淀成可追溯、可审核、可召回的长期知识，而不是每次新会话都重新解释上下文。

核心链路：

```text
Source -> Raw -> Candidate -> Human Review -> Wiki -> Search / Recall -> Agent Output
```

核心规则：

* `Raw` 保存原始材料和证据；
* `Candidate` 是 Agent 提出的知识草稿；
* `Human Review` 是人工审核门禁；
* `Wiki` 只保存审核后的知识；
* `Search / Recall` 让后续 Agent 重新使用这些知识。

Agent 可以写 Candidate，但不能绕过人工审核直接写 Wiki。

### 快速开始

```bash
pipx install ./cli --force
oks --version

oks init ./my-knowledge-base
export OKS_ROOT=./my-knowledge-base
oks status

oks ingest ./sample.md --mode quick --progress
oks drafts list
```

人工批准后：

```bash
oks drafts promote <slug>
oks search "agent memory"
oks recall "how should agent memory be managed?"
oks lint
```

### 详细文档

* [核心架构](docs/architecture/oks-core-architecture.md)
* [Agent 一键部署与接管提示词](docs/deployment/agent-one-prompt-installation.md)
* [干净服务器部署报告](docs/acceptance/clean-server-deployment-report.md)
* [飞书 E2E 状态](docs/acceptance/feishu-e2e-status.md)
* [平台反爬与轻量化部署研究](docs/research/platform-antibot-and-lightweight-deployment.md)
* [Kimi K3 案例](docs/cases/kimi-k3-deep-analysis.md)
