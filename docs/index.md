---
title: 概述
nav_order: 1
has_children: true
---
# Open Knowledge Studio

> 你的 AI 工具不会替你记住工作内容。Open Knowledge Studio 会。

它是你的 AI 工作记忆层。保存一个决策、一个洞察、一个有用的来源、或一段对话——Studio 让它可搜索，把它和你已有的知识连接起来，让 Claude Code 从同样的上下文开始工作。

你不需要一次性配置所有东西。先保存一条知识，再找到它，然后让 Claude Code 用它。一旦这个循环跑通，Studio 就变得容易理解了。

## 核心概念

| 概念 | 是什么 | 了解更多 |
|------|--------|----------|
| **Memory** | 从原始材料蒸馏出的持久知识——一个 concept、strategy 或 anti-pattern | [Memories →](memories.md) |
| **Raw Material** | 蒸馏前的入料层——文章、论文、仓库笔记、对话 | [Raw Materials →](raw-materials.md) |
| **召回引擎** | 六因子评分找到最相关知识：token overlap + substring + topic trace + type boost + review penalty + memory curve | [召回引擎 →](recall-engine.md) |
| **Dreaming 循环** | 人工审查的知识演化：raw → AI 蒸馏 → drafts → 人工审查 → wiki | [Dreaming 循环 →](dreaming-cycle.md) |

## 核心管线

```
raw/（人类收集的原始材料）
  ↓ /ingest — AI 分级 A/B/C
drafts/（中间态草稿）
  ↓ /promote — 人工审查
wiki/（策展知识，带衰减）
  ↓ oks search / /query — 6 因子召回
注入 Claude Code 上下文
```

## 独特之处

- **Knowledge as Code** — 所有知识以 Markdown + YAML frontmatter 存储，通过 Git 版本管理。
- **Git IS the migration** — 无数据库，schema 变更通过 `_meta/` 版本化。
- **Agent-direct** — OKS 只提供能力，不包装工具调用。Claude Code 是 AI 引擎，CLI 只做文件操作 + 召回评分。
- **人工审批门控** — 系统绝不在未经审查的情况下将 raw 内容提升到 wiki。
- **衰减是特性** — 知识随时间遗忘。常用的保持敏锐，被遗忘的淡入归档。
- **第一天少做** — 保存一条记忆，跑一次搜索，验证它工作。不要一次性配置所有东西。

## 准备开始？

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "your query"
```

- **[快速开始](start-here.md)** — 最短可用路径：保存一条 → 搜索到它 → 验证工作
- **[使用你的知识](memories.md)** — wiki 页面结构、类型和搜索
- **[Raw Materials](raw-materials.md)** — 原始材料、A/B/C 分级、蒸馏工作流
