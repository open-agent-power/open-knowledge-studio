---
title: Dreaming 循环
nav_order: 14
parent: 内部机制
---
# Dreaming Cycle（做梦循环）

*人工审查的知识演化：raw → 蒸馏 → drafts → 审查 → wiki。*

知识通过**人工审查的 draft 提案**演化 — 系统绝不自动将 raw 内容提升到 wiki。

这个过程是平台的 **Dreaming** — 周期性记忆固化，将原始经验蒸馏为结构化 wiki 知识，类似人类睡眠中的记忆巩固。

## Dream 循环

```
Collect → AI Dream → Write Drafts → Human Review → Promote → Decay → Evolve → Commit
```

### 1. Collect（收集）

Trace、对话、文章和论文在 `raw/` 中积累。这是原始材料层 — 人类收集，LLM 可读但 LLM 不写入。

### 2. AI Dream（AI 做梦）

`/ingest` 技能（三级路由）扫描 `raw/`，识别模式，生成候选 wiki 页面。AI 评估每个材料：

- **A 级** — 高质量，提升为 draft
- **B 级** — 可能有用，保留在 raw 等下一轮
- **C 级** — 低质量，跳过

质量门过滤掉：
- 内容 < 50 字符
- 通用标题（"Untitled"、"Note"）
- Importance < 0.3
- 重复（按内容指纹）

### 3. Write Drafts（写草稿）

A 级候选写入 `drafts/{slug}.md`，带 draft frontmatter。每个 draft 是一个提案 wiki 页面，包含：
- 提议的标题、类型、域、标签
- 来源归属（来自哪个 raw material）
- 初始重要性评分

### 4. Human Review（人工审查）

`/promote` 技能提供交互式审查：

- **Accept（接受）** — 提升到 `wiki/{domain}/{type}/`
- **Revise（修改）** — 编辑 draft 后重新审查
- **Reject（拒绝）** — 丢弃 draft

**核心不变量**：绝不未经人工审查将 raw 提升到 wiki（CONSTITUTION.md A3）。

### 5. Promote（提升）

```bash
oks drafts list           # 查看所有候选
oks drafts promote <slug> # 提升到 wiki
oks drafts reject <slug>  # 丢弃
```

提升时，draft 的 frontmatter 被最终确定，页面移动到 `wiki/{domain}/{type}/{slug}.md`。

### 6. Apply Decay（应用衰减）

`oks distill` 重新评分所有 wiki 页面。低于归档阈值的页面标记为 `status: dropped`。长时间未访问的页面按其类型特定衰减率衰减。

### 7. Evolve — 知识演化关系（演化）

当新知识与已有页面相关时，系统追踪 4 种关系：

| 关系 | 含义 | 对旧页面的影响 |
|------|------|---------------|
| `supersedes` | 新页面替代旧页面 | 标记 `superseded`，排除出召回 |
| `enriches` | 新页面补充旧页面 | 两者保持 active，互相链接 |
| `confirms` | 新页面确认旧页面 | 旧页面 confidence +0.1 |
| `challenges` | 新页面挑战旧页面 | 旧页面标记 `[stale]`，待审查 |

`write_wiki_page()` 接受 `relates_to` 和 `relationship` 参数，自动更新旧页面 frontmatter。

### 8. Git Commit（提交）

`oks sync` 提交所有变更 — 新 wiki 页面、更新的 drafts、衰减后的评分。

```bash
oks sync           # commit + push
oks sync --pull    # 先 pull，再 commit + push
```

## 完整循环命令

```bash
# 运行完整 dream 循环（衰减 + 演化）
oks distill

# 预览不写入
oks distill --dry-run

# 交互式审查生成的 drafts
oks drafts list
oks drafts promote <slug>
```

## 核心不变量

{: .important }
> **绝不未经人工审查将 raw 提升到 wiki**（CONSTITUTION.md A3）。
>
> AI 可以 dream，但人类决定什么成为持久知识。

## 实现

- `/ingest` — 三级路由 + AI 分诊
- `oks distill` — 衰减 + 演化（CLI）
- `/promote` — 人工审查
- `cli/knowledge_studio/distiller.py` — 核心逻辑

## 下一步

* **[每日循环](daily-loop.md)**：Dreaming 在每天的训练闭环里处于哪一步
* **[Memories](memories.md)**：提升后的 memory 长什么样
* **[Raw Materials](raw-materials.md)**：蒸馏前的 raw material 长什么样
* **[Decay System](decay-system.md)**：memory 评分如何随时间变化
* **[Architecture](architecture.md)**：五桶结构

---

{% include comments.html %}
