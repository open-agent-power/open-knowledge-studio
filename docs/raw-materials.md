---
title: Raw Materials
nav_order: 4
parent: 概述
---
# Raw Materials（原始材料）

*蒸馏前的入料层——文章、论文、仓库笔记、对话，按类型组织、A/B/C 分级。*

Raw 是你的入料层 — 蒸馏之前的原始来源。你读过的文章、收集的论文、研究过的代码仓库、经历过的对话。系统读取它们、评级、然后将持久部分蒸馏为 [Memory](memories.md)。

{: .important }
> **Raw 不是 Thread。** 竞品把所有东西都塞进"conversations"。
> 我们的 raw/ 有**类型化入料**（articles / papers / repos / misc）、**A/B/C 分级**、
> **指纹去重**和**人工审批门控**。这就是区别。

## 为什么 raw/ 不只是"对话"

| 我们的 raw/ | 通用 "Thread" |
|-------------|-------------------|
| 4 个类型子目录（articles/papers/repos/misc） | 扁平列表，仅对话 |
| 蒸馏前 A/B/C 分级 | 全量导入或全手动 |
| 指纹去重防止重复 draft | 无去重 |
| 人工门控：raw → draft → review → wiki | 自动提升或纯手动 |
| 输出到 22 域 × 3 类型的结构化 wiki/ | 扁平 memory store |
| 来源追踪：每个 draft 记录其 raw 来源 | 无来源链路 |

## 第一个有用的 Raw Material

{: .tip }
> 如果你是新用户，先做以下其中一件事：
>
> * 把一篇文章或笔记保存到 `raw/`
> * 运行一次 `/ingest` 进行分级和提取 draft
> * 从这些 draft 中蒸馏出一条有用的 memory
>
> 然后打开那条 memory，确认它捕捉了关键信息。这就是核心工作流。

| 我想... | 跳转到 |
|---|---|
| 保存文章或论文 | [保存到 raw/](#保存到-raw)
| 将 raw materials 蒸馏为 drafts | [蒸馏](#蒸馏)
| 导入对话 | [导入格式](#导入格式)
| 了解 A/B/C 分级 | [质量门](#质量门)
| 搜索历史 raw materials | [搜索 Raw](#搜索-raw)

## 目录结构

```
raw/
└── {YYYY}/{MM}/{DD}/
    └── {source}/         # articles | papers | videos | audio | repos | misc
        └── {slug}.md
```

材料**按日期 + 来源组织**。日期目录自动创建，来源对应工具类型 — 文章、论文、视频、音频、仓库、其他。这使得按时间检索和按来源过滤都很方便。

### 三级工具协议

Agent 读取 `settings/handlers.json` 路由表，按模态选择工具：

| 级别 | 类型 | 示例 | 输出 |
|------|------|------|------|
| L0 | 系统工具 | curl, pdftotext | 原始 stdout |
| L1 | OKS 协议 CLI (`oks-raw-bundle`) | oks-video, oks-audio, oks-image | Raw Bundle (`raw-multimodal/v0.1`) |
| L2 | 独立工具 | agent-reach, yt-dlp | 工具特定格式 |

Agent 直接通过 Bash 调用工具，OKS 不在运行时路径中。

### Raw 文件格式

```markdown
---
title: "Understanding Event-Driven Architecture"
source: https://example.com/event-driven-architecture
date: 2026-07-13
type: article
tags: [architecture, event-driven, microservices]
---

# Understanding Event-Driven Architecture

Event-driven architecture is a paradigm where services communicate...
```

**最简格式** — 一个带内容的 markdown 文件。Frontmatter 可选但推荐，能改善搜索结果和来源追踪。

### 来源追踪

每个 raw 文件可以在 frontmatter 中携带来源元数据：

| 字段 | 用途 |
|------|------|
| `source` | 获取材料的 URL 或路径 |
| `date` | 材料收集时间 |
| `type` | `article` / `paper` / `repo` / `conversation` / `note` |
| `tags` | 用于过滤的主题标签 |

当 raw material 被蒸馏为 draft 时，draft 会记录其来源。这形成了一条**来源链路**：wiki 页面 ← draft ← raw 文件 ← 原始来源。你随时可以追溯一条策划好的 memory 回到它的源头。

## 保存到 Raw

### 从文件

将任意 markdown 文件放入对应的 `raw/` 来源目录：

```bash
# 自动创建当天目录
mkdir -p raw/$(date +%Y/%m/%d)/articles
cp ~/Downloads/article.md raw/$(date +%Y/%m/%d)/articles/
```

### 从 CLI

```bash
mkdir -p raw/$(date +%Y/%m/%d)/misc
echo "We decided to use FastAPI for the new service" > raw/$(date +%Y/%m/%d)/misc/api-decision.md
```

### 从 AI 对话

保存对话摘要或 Q&A 提取。`/archive` 技能可以从 Agent 会话中提取 Q&A 并写入 `raw/`：

```markdown
## User

What's the best approach for state management in React?

## Assistant

For large applications, Zustand is lightweight and avoids the boilerplate
of Redux. For simpler apps, React Context is sufficient...

## Decision

Use Zustand for state management — lightweight, no boilerplate, good DX.
```

## 蒸馏

连接 raw materials（raw/）到 memories（wiki/）的关键工作流。

### 工作原理

```
raw/（人类收集 / 工具处理）
  ↓ /ingest — 三级路由 + A/B/C 分级每个文件
  ↓ A 级 → drafts/（候选 wiki 页面）
  ↓ B 级 → 保留在 raw/，等下一轮
  ↓ C 级 → 跳过
drafts/（中间提案）
  ↓ /promote — 人工审查：接受 / 修改 / 拒绝
wiki/（策展知识，带衰减 + 演化）
```

### A/B/C 分级 — 我们的优势

系统对每个 raw material 进行分级：

| 等级 | 含义 | 操作 |
|------|------|------|
| **A** | 高质量，有模式价值 | 写入 `drafts/` 供人工审查 |
| **B** | 可能有用 | 保留在 `raw/`，下一轮重新评估 |
| **C** | 低质量或重复 | 跳过，留在 `raw/` |

这意味着人工只需审查最佳候选，而非 raw/ 中的每个文件。

### 质量门

一个 raw material 成为 A 级 draft 之前，必须通过：

| 门控 | 规则 | 原因 |
|------|------|------|
| 内容长度 | < 50 字符则跳过 | 太短，不含有用知识 |
| 标题检查 | 通用标题（"Untitled"、"Note"）则跳过 | 无模式可提取 |
| 重要性下限 | < 0.3 则跳过 | 低价值知识不值得策划 |
| 指纹去重 | 内容 hash 已有 draft 则跳过 | 防止重复 wiki 页面 |

**指纹去重**是我们的独特优势 — 系统为每个 raw 文件计算内容 hash，与已有 drafts 对比。如果相同内容已被蒸馏过，不会创建重复。这让 wiki/ 在 raw/ 增长时保持干净。

### 运行蒸馏

```bash
# 预览蒸馏结果（不写入）
oks distill --dry-run

# 运行完整循环：分级 raw → 写 drafts → 应用衰减 → 演化
oks distill

# 列出待人工审查的 drafts
oks drafts list

# 提升 draft 到 wiki
oks drafts promote <slug>
```

## 导入格式

### Conversation Markdown

导入对话的通用格式。任何能写 `## User` / `## Assistant` 头部的工具生成的文件，我们都能读取。

```markdown
---
title: Python Async Patterns
source: chatgpt
date: 2026-07-13
---

## User

How does async/await work in Python?

## Assistant

Python's `async`/`await` lets you write concurrent code that doesn't block
while waiting for I/O. An `async def` function returns a coroutine...

## User

When should I use asyncio vs threading?

## Assistant

Use asyncio for I/O-bound work. Use threading for blocking libraries.
Use multiprocessing for CPU-bound work.
```

**格式规则：**
- 头部：`## User`、`## Assistant` 或 `## System`（二级标题，每条消息一个）
- 内容：头部之间的所有内容为一条消息
- Frontmatter：可选 YAML 块，含 `title`、`source`、`date`
- 无识别头部的文件作为单个文档导入

### 批量导入

```bash
# 复制所有文章到 raw/
mkdir -p raw/$(date +%Y/%m/%d)/articles
cp ~/Downloads/articles/*.md raw/$(date +%Y/%m/%d)/articles/

# 运行蒸馏处理全部
oks distill --dry-run  # 预览
oks distill            # 执行
```

## 搜索 Raw

### 按关键词

```bash
oks search "authentication" --source raw
```

### 按新鲜度

召回引擎应用新鲜度因子：`0.95^days_old`。越新的材料在 episodic recall 中得分越高。这意味着搜索时最近的 raw materials 优先呈现。

### 双路召回

```bash
oks recall "database design" --limit 5
```

同时返回 episodic 结果（来自 `raw/`）和 knowledge 结果（来自 `wiki/`），合并展示：

```json
{
  "episodic": [...],   // raw/ 材料，按关键词 + 新鲜度匹配
  "knowledge": [...]    // wiki/ 页面，按 6 因子相关性 + 曲线匹配
}
```

## Raw Material vs Memory — 何时用哪个

| 场景 | 用 Raw（raw/） | 用 Memory（wiki/） |
|------|---------------|---------------------|
| 需要完整原始来源 | 是 | 否 |
| 需要持久模式 | 否 | 是 |
| 搜索特定决策 | 也许 | 是（相关性更高，有评分） |
| 想追溯理解演化 | 两者都用 | 是（有版本链接、supersession） |
| 快速查阅带置信度 | 否 | 是（有 tier 评分、来源标签） |
| 需要来源链路 | 从这里开始 | 链接回 raw 来源 |

## 我们的管线优势

```
raw/（日期 + 来源结构）
  ↓ A/B/C 分级（过滤噪声）
  ↓ 指纹去重（防止重复）
drafts/（人工门控审查）
  ↓ /promote — 接受 / 修改 / 拒绝
wiki/（22 域 × 3 类型，带衰减）
  ↓ 6 因子召回 + 记忆曲线
  ↓ 演化：4 种知识关系
注入 Agent 上下文
```

每一步都有质量门。没有通过分级**和**人工审查的内容不会进入 wiki/。这就是我们的 wiki/ 在 raw/ 增长时保持干净的原因 — 管线在每一阶段过滤噪声。

## 下一步

* **[Memories](memories.md)**：蒸馏后会发生什么 — 结构、类型、搜索
* **[Dreaming Cycle](dreaming-cycle.md)**：完整演化管线
* **[Recall Engine](recall-engine.md)**：6 因子搜索评分如何工作
* **[Architecture](architecture.md)**：认知桶结构和生命周期

---

{% include comments.html %}
