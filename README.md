# Open Knowledge Studio

> A file-based knowledge engineering workspace for Claude Code.
> Core pipeline: **raw → wiki → recall**.

[English](#english) | [中文](#中文)

---

## English

### What is this?

Open Knowledge Studio is a knowledge base system designed to work with Claude Code. It provides:

- **4 cognitive buckets + 2 infrastructure layers**: buckets `profiles/`, `raw/`, `wiki/`, `drafts/`; infrastructure `settings/` (config), `_meta/` (schema)
- **6+1-factor recall engine**: token overlap + substring + topic trace + type boost + review bonus (failure lessons rank higher) + memory curve, plus an optional goal boost (active goals lift on-scope pages; no-op without goals)
- **Dreaming cycle**: AI distills raw materials into draft proposals, humans review and promote to wiki
- **Decay system**: memory curve scoring with type-specific λ, tier classification (hot/warm/cold/evictable)
- **22 knowledge domains**: soft convention — directories created on demand
- **CLI tool (`oks`)**: search, recall, wiki CRUD, drafts, distill, lint, status, metrics
- **8 Claude Code skills**: start, ingest, query, lint, compile, status, archive, promote
- **4 hooks**: pre-compact snapshot, session-start loading, wiki-write validation, opt-in auto-recall on prompt (`oks hook install`)

### Quick Start

Prerequisites: Python ≥ 3.10, git. Claude Code (or a compatible agent) is optional
but required for the skills-driven workflow (`/ingest`, `/query`, `/promote`) — the
CLI alone covers search/recall/wiki CRUD.

```bash
pip install open-knowledge-studio   # 1. install the CLI
oks init my-knowledge-base          # 2. scaffold your instance
cd my-knowledge-base
oks status                          # 3. use it
oks search "git branch"             # (empty on a fresh instance — add knowledge first)
```

`oks init` materializes the shareable layer (Claude Code skills, templates, schema,
settings) and a git-tracked memory instance — no repo clone required. This repo is
the **code/template** source; your knowledge lives in the instance you create.

### Architecture

See [CONSTITUTION.md](CONSTITUTION.md) for the full memory design.

### Documentation

See [`docs/`](docs/) for in-depth design documentation (GitHub Pages ready).

---

## 中文

### 这是什么？

Open Knowledge Studio 是一个为 Claude Code 设计的文件式知识库系统。提供：

- **4 认知桶 + 2 基础设施层**：认知桶 `profiles/`、`raw/`、`wiki/`、`drafts/`；基础设施 `settings/`（配置）、`_meta/`（schema）
- **6+1 因子召回引擎**：token 交集 + 子串匹配 + topic trace + 类型加权 + 审查加分（失败教训优先召回）+ 记忆曲线，外加可选的**目标加权**（active goal 抬升命中域/关键词的页面；无 goal 时不生效）
- **Dreaming 循环**：AI 将原始材料蒸馏为草稿提案，人工审查后提升为 wiki
- **衰减系统**：记忆曲线评分，类型特定 λ，tier 分级（hot/warm/cold/evictable）
- **22 个知识域**：软约定——目录按需创建，不预建骨架
- **CLI 工具（`oks`）**：搜索、召回、wiki CRUD、草稿、蒸馏、健康检查、状态、指标
- **8 个 Claude Code 技能**：start, ingest, query, lint, compile, status, archive, promote
- **4 个钩子**：压缩前快照、会话加载、写入验证、可选的提问自动召回（`oks hook install`）

### 快速开始

前置条件：Python ≥ 3.10、git。Claude Code（或兼容 Agent）可选，但技能工作流
（`/ingest`、`/query`、`/promote`）依赖它——纯 CLI 覆盖搜索/召回/wiki CRUD。

```bash
pip install open-knowledge-studio   # 1. 安装 CLI
oks init my-knowledge-base          # 2. 初始化你的知识库实例
cd my-knowledge-base
oks status                          # 3. 开始使用
oks search "git branch"             # （新实例为空——先写入知识再搜）
```

`oks init` 会物化可共享层（Claude Code 技能、模板、schema、配置）并生成一个用 git
跟踪记忆的实例——无需 clone 本仓库。本仓库是**代码/模板**源，你的知识存在你创建的实例里。

### 设计文档

详见 [`docs/`](docs/) 目录（支持 GitHub Pages）和 [`CONSTITUTION.md`](CONSTITUTION.md)。

## License

MIT
