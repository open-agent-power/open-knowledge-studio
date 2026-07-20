# Open Knowledge Studio

> A file-based knowledge engineering workspace for Claude Code.
> Core pipeline: **raw → wiki → recall**.

[English](#english) | [中文](#中文)

---

## English

### What is this?

Open Knowledge Studio is a knowledge base system designed to work with Claude Code. It provides:

- **5-bucket architecture**: `profiles/`, `raw/`, `wiki/`, `drafts/`, `settings/`
- **6+1-factor recall engine**: token overlap + substring + topic trace + type boost + review penalty + memory curve, plus an optional goal boost (active goals lift on-scope pages; no-op without goals)
- **Dreaming cycle**: AI distills raw materials into draft proposals, humans review and promote to wiki
- **Decay system**: memory curve scoring with type-specific λ, tier classification (hot/warm/cold/evictable)
- **22 knowledge domains**: soft convention — directories created on demand
- **CLI tool (`oks`)**: search, recall, wiki CRUD, drafts, distill, lint, status, metrics
- **8 Claude Code skills**: start, ingest, query, lint, compile, status, archive, promote
- **3 hooks**: pre-compact snapshot, session-start loading, wiki-write validation

### Quick Start

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "git branch"
```

### Architecture

See [CONSTITUTION.md](CONSTITUTION.md) for the full memory design.

### Documentation

See [`docs/`](docs/) for in-depth design documentation (GitHub Pages ready).

---

## 中文

### 这是什么？

Open Knowledge Studio 是一个为 Claude Code 设计的文件式知识库系统。提供：

- **4 认知桶 + 2 基础设施层**：认知桶 `profiles/`、`raw/`、`wiki/`、`drafts/`；基础设施 `settings/`（配置）、`_meta/`（schema）
- **6+1 因子召回引擎**：token 交集 + 子串匹配 + topic trace + 类型加权 + 审查惩罚 + 记忆曲线，外加可选的**目标加权**（active goal 抬升命中域/关键词的页面；无 goal 时不生效）
- **Dreaming 循环**：AI 将原始材料蒸馏为草稿提案，人工审查后提升为 wiki
- **衰减系统**：记忆曲线评分，类型特定 λ，tier 分级（hot/warm/cold/evictable）
- **22 个知识域**：预创建目录骨架
- **CLI 工具（`oks`）**：搜索、召回、wiki CRUD、草稿、蒸馏、健康检查、状态、指标、同步
- **8 个 Claude Code 技能**：start, ingest, query, lint, compile, status, archive, promote
- **3 个钩子**：压缩前快照、会话加载、写入验证

### 快速开始

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "git branch"
```

### 设计文档

详见 [`docs/`](docs/) 目录（支持 GitHub Pages）和 [`CONSTITUTION.md`](CONSTITUTION.md)。

## License

MIT
