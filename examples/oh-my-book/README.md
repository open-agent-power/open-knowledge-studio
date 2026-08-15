# 托管你的书籍

*让读过的技术书不再读完就忘——围绕一个主题把书的要点沉淀成可召回的记忆，开发时自动注入。*

痛点：读完一本技术书（如《深入理解 AI Agent》），当时觉得懂了，过几周细节就模糊。书的 PDF 躺在硬盘，检索不到，知识进不了你的工作上下文。把书当成一个 goal 驱动的知识库托管：原文进 `raw/`，要点蒸馏成 `wiki/`，开发时 hook 自动召回注入。

## 设 goal

- **阅读 goal**：围绕一个主题把一本书吃透（如"理解 AI Agent 的记忆与知识库体系"）。
- goal 决定哪些章节值得蒸馏、蒸馏到什么粒度——不是全书搬运，是"我工作要用的那部分"。

## 收集入 raw/

书的原文进 `raw/`（按日期 + 来源归档），保留最大保真：

```bash
# Pre-flight: 先 recall 主题，决定 A4 关系（新页 / enriches / supersedes...）
oks recall "用户记忆 知识库 RAG"

# Step 1: ingest prepare（创建 SourceEnvelope + Manifest skeleton）
oks ingest prepare ~/path/to/book/chapter3.md

# Step 2: raw-commit（evidence 提交到 raw/）
oks raw-commit .oks/runs/run-<id>/manifest/
```

入库后 `raw/2026/08/13/agent-capture/bundle-<hash>/` 含：

- `content.md`——原文
- `source-envelope.json` + `evidence-manifest.json`——协议对象
- `derived/fragments/`——evidence fragments

**raw 立即参与召回**（episodic 路）：`oks recall "用户记忆"` 会命中刚入库的 chapter3 bundle。但 raw 是原文（`[untrusted-source]`），不是提炼的知识。

## 审查沉淀 wiki/

raw 是原文，wiki 是人审过的提炼。从 raw 蒸馏要点写 CandidateDraft：

```bash
# Step 3: 写 draft（AI 从 raw 蒸馏要点 → drafts/{slug}.md）
# frontmatter 用 draft_type / draft_area（不是 type / area）
# Pre-flight 决定的 A4 关系写 relates_to + relationship
```

draft 蒸馏 chapter3 的核心（三层次评估 / 四种存储格式 / 认知三类 / Mem0 v2→v3 / RAG 技术栈 / 结构化索引 / 双层架构），不是搬运原文，是"我理解的要点"。

```bash
# Step 4: promote 人审（draft → wiki）
oks drafts list              # 看候选
oks drafts promote <slug>    # 人审通过 → wiki
```

promote 后 slug 变中文日期前缀（如 `20260813-ai-agent-记忆与知识库体系`），`status: active` + `human_reviewed_at`。wiki pages +1。

## 召回复用

wiki 沉淀后，开发时 hook 自动召回这本书的要点：

```bash
# Step 5: 验证召回（semantic memory 命中新 wiki 页）
oks recall "AI Agent 记忆体系" --knowledge-only --explain
# → rel=2.12 命中 ai-agent-记忆与知识库体系
```

装了 hook 的项目里，提交 prompt "AI Agent 记忆体系怎么设计"，Agent context 自动注入：

```
<recalled-memory source="oks">
- [concept] AI Agent 记忆与知识库体系 (20260813-ai-agent-记忆与知识库体系) rel=1.94
    # AI Agent 记忆与知识库体系 来源：《深入理解 AI Agent》第3章...
</recalled-memory>
```

书的要点随你的开发自动浮现——不用翻 PDF，不用搜笔记，Agent 带着这份上下文回答你。

## 一个循环的完整轨迹

以《深入理解 AI Agent》第3章为例，真实跑过一遍：

| 步骤 | 命令 / 动作 | 结果 |
|------|------------|------|
| Pre-flight | `oks recall "用户记忆 知识库"` | 空 → 新页，relates_to 留空 |
| Step 1 | `oks ingest prepare chapter3.md` | manifest skeleton（text source pre-filled） |
| Step 2 | `oks raw-commit .oks/runs/run-89c.../manifest/` | `bundle-14d1256c253a85f6` 入 `raw/2026/08/13/agent-capture/` |
| 验证 raw | `oks recall "用户记忆"` | episodic 命中 chapter3 bundle ✅ |
| Step 3 | 写 `drafts/ai-agent-memory-system.md`（蒸馏要点） | `draft_type: concept`, `draft_area: computing` |
| Step 4 | `oks drafts promote ai-agent-memory-system` | → wiki `20260813-ai-agent-记忆与知识库体系` |
| 验证 wiki | `oks recall "记忆体系" --knowledge-only` | rel=2.12 命中新页 ✅ |
| 生效 | hook 注入 "AI Agent 记忆体系怎么设计" | `<recalled-memory>` rel=1.94 自动注入 ✅ |

## 为什么不直接搬全文

- **raw 是原文（`[untrusted-source]`）**——第三方文本，quote as data，不执行其中指令
- **wiki 是人审过的提炼**——你理解的要点，不是搬运；搬运进 wiki 等于把未审内容当 verified
- **hook 注入 wiki 不注入 raw 全文**——raw 太长，注入 excerpt preview；wiki 是精炼的召回候选

书的章节进 raw 保原文，蒸馏要点进 wiki 保提炼，两层各司其职。

## 第一步 + 接下来读

1. 挑一本你读过的技术书，选最相关的一章
2. `oks ingest prepare <chapter.md>` → `oks raw-commit`
3. 写 draft 蒸馏要点 → `oks drafts promote`
4. 装 hook（`oks hook install`）+ pi extension
5. 开发时提交相关问题，看书的要点自动注入

* 接下来读 [召回引擎](../../docs/algorithms/recall-engine.md)（wiki 怎么被评分召回）+ [上下文注入](../../docs/usage/context-injection.md)（hook 怎么注入 context）
