---
title: Memories
nav_order: 2
---
# Memories

一条 memory 是一个值得保留的持久知识：一个 concept、一个 strategy、一个 anti-pattern、或一个决策。每条 memory 应该独立可读，不需要完整的对话上下文就能理解。

Memories 是 Open Knowledge Studio 的核心单元。搜索、衰减、演化和 Agent 集成都因为 memories 的存在而变得更有价值。

## Memories vs Raw Materials

| | Memory (wiki/) | Raw Material (raw/) |
|---|---|---|
| **是什么** | 持久的、蒸馏后的知识 | 原始文章、论文或对话 |
| **谁写** | LLM 写，人审批 | 人类收集 |
| **衰减** | 类型特定 λ | 无 |
| **召回** | 6 因子相关性 + 曲线 | 关键词 + 新鲜度 |
| **优势** | 22 域结构、衰减 tier、4 种知识关系 | 日期 + 来源分类、A/B/C 分级、指纹去重 |
| **何时用** | 需要模式或决策 | 需要完整历史 |

推荐工作流：把来源保存到 `raw/`，然后把值得保留的部分蒸馏为 `wiki/` memories。

## 第一条有用的 Memory

如果你是新手，不要先纠结结构。保存一条真实内容：

* 一个你学到的 concept
* 一个有效的 strategy
* 一个你想避免的 anti-pattern

然后搜索它。一旦跑通，这整页文档就更容易理解了。

## Memory 结构

| 字段 | 说明 |
|------|------|
| **title** | 简短摘要，在 frontmatter 中设置 |
| **type** | `concept`、`strategy` 或 `anti-pattern` |
| **area** | 22 个知识域之一（如 `computing`、`management`） |
| **importance** | 0.1 到 1.0 — 影响搜索排名和衰减优先级 |
| **content** | 知识本身，frontmatter 之后的 Markdown 正文 |
| **tags** | 用于过滤和组织的标签 |
| **created** | 时间戳，用于时序搜索和衰减计算 |
| **access_count** | 被召回的次数，增强 confidence |
| **status** | `active`、`provisional`、`archived`、`dropped` 或 `superseded` |

### Importance 等级

| 范围 | 含义 | 示例 |
|------|------|------|
| 0.8 – 1.0 | 关键 | 架构决策、核心模式、生产级反模式 |
| 0.5 – 0.7 | 有用 | 标准策略、良好实践、项目经验 |
| 0.1 – 0.4 | 背景 | 参考信息、次要细节、随手笔记 |

默认值 0.5。召回引擎用这个分数决定搜索结果中什么优先展示。

### Memory Type

每条 memory 有一个主类型。召回引擎按类型加权：

| Type | 用途 | Type Boost | 衰减 λ |
|------|------|------------|--------|
| `concept` | 持久参考知识 | ×0.6 | 0.0（不衰减） |
| `strategy` | 方法、决策、工作流 | ×0.8 | 0.014（缓慢） |
| `anti-pattern` | 要避免的东西、失败模式 | ×1.5 | 0.010（中等） |

anti-pattern 的 boost 最高（×1.5），因为**错误是最有价值的召回对象** — 你希望在重复之前先找到它。

### 来源标签

每条 memory 携带一个来源标签，表示其置信度：

| 标签 | 含义 |
|------|------|
| `[verified]` | 工具确认（有 trace）或人工审查通过 |
| `[user-stated]` | 用户明确陈述 |
| `[inferred]` | AI 蒸馏，尚未验证 |
| `[stale]` | 可能过时，待重新验证 |

## 创建 Memories

### 从原始材料（主路径）

1. 把来源材料放入 `raw/`（文章、论文、对话摘要）
2. 运行 `/ingest`（三级路由）或 `oks distill` — AI 扫描并识别模式
3. 候选写入 `drafts/{slug}.md`
4. 用 `/promote` 审查 — accept、revise 或 reject
5. 接受的草稿变为 `wiki/{domain}/{type}/{slug}.md`

### 从 AI 对话

用 `/archive` 技能从对话中提取 Q&A 并写入 wiki。

### 从 CLI

```bash
oks wiki create \
  --title "Use Typer for CLI tools" \
  --type strategy \
  --area computing \
  --importance 0.7
```

### 从模板

```bash
cp templates/strategy.md wiki/computing/strategies/my-strategy.md
# 编辑 frontmatter 和正文
```

## 搜索 Memories

### 三种搜索模式

| 模式 | 工作方式 | 适合 |
|------|----------|------|
| **Semantic** | jieba 分词后的 token overlap — 按语义找，不只是精确匹配 | 搜"设计模式"能找到"架构方法" |
| **Keyword** | 标题和正文中的 substring 精确匹配 | 精确术语、代码名、特定 API |
| **Graph** | topic trace + type boost + review penalty | 找相关决策、追溯主题历史 |

6 因子召回引擎自动组合这三种模式。详见 [召回引擎](recall-engine.md)。

### 从 CLI

```bash
oks search "authentication patterns"
oks search "error handling" --domain computing --type strategy
oks recall "database design" --limit 5
oks wiki list --domain computing --status active
```

### 从 Agent

```
/query What patterns do we have for error handling?
```

Agent 调用 `oks recall`，将相关 wiki 页面注入上下文（带来源标签），然后带引用回答。

## 编辑和组织

### 更新 Memory

直接编辑 wiki 页面，改动立即生效。

```bash
oks wiki pin <slug>      # 提升 importance（pin_bonus = 0.5）
oks wiki archive <slug>  # 归档
```

### 删除 Memory

Memories 从不删除 — 它们被归档（`status: dropped`）或被替代（`status: superseded`）。Git 历史是安全网。

## 知识演化关系

当你保存的新知识和已有页面相关时，系统追踪 4 种关系：

| 关系 | 含义 | 对旧页面的影响 |
|------|------|---------------|
| `supersedes` | 新页面替代旧页面 | 标记 `superseded`，排除出召回 |
| `enriches` | 新页面补充旧页面 | 两者都保持 active，互相链接 |
| `confirms` | 新页面确认旧页面 | 旧页面 confidence +0.1 |
| `challenges` | 新页面挑战旧页面 | 旧页面标记 `[stale]`，待审查 |

这构成了知识演化图。你可以追溯对任何主题的理解是如何随时间变化的。

### 来源标签 — 动态生成

来源标签在注入时**动态生成**，不存储在 frontmatter 中：

| 条件 | 标签 | 含义 |
|------|------|------|
| `status == "stale"` | `[stale]` | 被 challenges 关系标记，可能过时 |
| `has_traces == true` | `[verified]` | 工具确认（有 trace 证据） |
| `confidence < 0.5` | `[inferred]` | AI 蒸馏，低置信度 |
| `status == "provisional"` | `[inferred]` | 尚未提升为 active |
| 其他 | `[verified]` | 人工审查的活跃知识 |

## Memory 生命周期

```
Provisional → Active（access_count ≥ 3）→ Dropped（score < threshold）
                                         → Superseded（被新页面替代）
```

| Tier | Score | 行为 |
|------|-------|------|
| **hot** | ≥ 0.7 | 优先召回，高 confidence |
| **warm** | ≥ 0.4 | 正常召回 |
| **cold** | ≥ 0.15 | 低优先级，可能需要审查 |
| **evictable** | < 0.15 | 归档候选 — 建议移除 |

访问增强 confidence：`new_confidence = min(1.0, current + 0.1 × (1 - current))`

## 下一步

* **[Raw Materials](raw-materials.md)**: 原始材料、蒸馏工作流和导入格式
* **[召回引擎](recall-engine.md)**: 6 因子评分算法详解
* **[Dreaming 循环](dreaming-cycle.md)**: memories 如何演化、连接和合成
* **[衰减系统](decay-system.md)**: 记忆曲线、类型特定 λ 和 tier 分级
* **[架构设计](architecture.md)**: 五桶结构和记忆生命周期

---

{% include comments.html %}
