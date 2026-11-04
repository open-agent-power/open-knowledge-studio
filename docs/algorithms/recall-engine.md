---
title: 召回引擎
nav_order: 3
parent: 维护者
nav_exclude: true
search_exclude: true
---
# 召回引擎（OKS Triple-Layer Recall）

`oks recall` 是唯一召回入口。默认合并 Raw episodic 与 Wiki knowledge；`--knowledge-only` 只查 Wiki。`raw/executions/` 和 `raw/.logs/` 是 provenance，不参与召回。

## 难题背景

知识库随时间增长，`wiki/` 累积成百上千页。用户或 Agent 提一个 query，如何找到最相关知识并排序？

两条路：

- **语义召回**（embedding 相似度）——效果好，但 CLI 核心不调 AI API（P4），本地跑 embedding 模型成本高。
- **关键词召回**（字面匹配）——轻量，但跨表述召回差（搜"design patterns"命中不了只写"architectural approaches"的页）。

OKS 选了关键词召回，并用 **node-level BM25**（吸收 TreeSearch）在固定 50-case 数据集上达到 **R@1 = 82.5% / MRR = 0.907**（历史消融基准；不是通用 SLA）。

## 三层架构（v0.6.0+）

召回与注入解耦——fts5 管"找得准"，oks 灵魂管"注入时优先什么"，衰减管"长期质量"：

```
┌─ 召回层（fts5 node-level BM25, 默认 R@1=82.5%）──────┐
│  每个 ## heading 段一个 FTS5 row，多词同段高分          │
│  SQLite FTS5 + BM25 + column weights + 增量 diff       │
└──────────────────────────────────────────────────────┘
                          ↓ top-N hits
┌─ 注入层（oks 灵魂 boost）──────────────────────────────┐
│  1. goal boost 重排（goal 命中 slug 往前排）            │
│  2. injection_boost 标注（type×1.5/0.8/0.6 + review×1.2 │
│     + generic×0.5），不改召回顺序，供 /query + eval 可见 │
│  3. memory curve score（store.py 独立算的 decay 分）   │
└──────────────────────────────────────────────────────┘
                          ↓ 注入会话
┌─ 衰减层（store.py，独立后台）─────────────────────────┐
│  apply_decay: type-specific λ → score → tier 分类       │
│  hot/warm/cold/evictable，定时淘汰 stale 记忆           │
└──────────────────────────────────────────────────────┘
```

**关键洞察**（50-case 实测驱动）：oks 的"灵魂"——memory curve / goal boost / review bonus / type boost——在**召回层 re-rank 反而降精度**（fusion R@1=0.805 < fts5 R@1=0.825，不相关 page 高分挤掉精确命中）。因此**召回用 fts5 精度，灵魂在注入层 boost**。

## 双路召回

| 路径 | 来源 | 评分 |
|------|------|------|
| Episodic | `raw/` + `profiles/` | 关键词 + 新鲜度（`0.95^days_old`） |
| Knowledge | `wiki/` | fts5 node-level BM25 + 注入层 oks 灵魂 boost |

## 可插拔 search backend

Knowledge 路径的召回后端可插拔（`recall(search_backend=...)` 或 `settings/recall.yaml`）：

- **fts5**（**默认**，CV from TreeSearch FTS5Index + markdown tree parser）：SQLite FTS5 + BM25 + column weights（title 5x > tags 3x > body 1x > code 0.5x）+ 增量 diff（content_hash）+ 持久化索引（`.oks/fts5.db`）。v0.6.0 吸收 TreeSearch 的 markdown tree parser，每个 `##` heading 段一个 FTS5 row（node-level），多词同段 BM25 高分——50-case 消融 R@1=0.825 / MRR=0.907（native page-level R@1=0.525）。schema_version 检测自动 DROP 重建旧 schema。大库（1000+ 页）比 native 遍历快。FTS5 不可用时降级 LIKE。
- **native**（6+1 因子，向后兼容）：jieba + IDF + token overlap + substring + topic trace + type boost + review bonus + memory curve + goal boost，page-level，实时遍历，无 SQLite 依赖。50-case R@1=0.525——语义召回弱（词不匹配就失效）。v0.6.0 起不再默认，保留供小库 / 无 SQLite 环境 / 历史复现。
- **fusion**（实验）：fts5 node-level 主召回 + native 6+1 归一化 re-rank（0.7 fts5 + 0.3 native）。50-case R@1=0.805——低于纯 fts5 R@1=0.825，证明 native re-rank 拖累。
- **connector**：第三方包经 `entry_points(group="oks_search_backend")` 注册（embedding / 代码 ast_parser / 其他开源 search 框架），OKS 核心不改。

架构决策：不假设数据少——FTS5 持久化索引是大数据标配；embedding / 代码搜索等能力以 connector 方式自由扩展替换，而非硬编码进核心。

## native 6+1 因子（向后兼容的召回算分，v0.6.0 前默认）

native backend 的 7 个召回信号（token overlap / substring / topic trace / type boost / review bonus / memory curve / goal boost）。v0.6.0 起召回默认 fts5，但其中**灵魂因子**（type boost / review bonus / memory curve / goal boost）搬到 fts5 注入层作 `injection_boost`，**召回算分类**（token overlap / substring / topic trace）被 fts5 BM25 取代。

```
base  = token_overlap_count × 0.3 + substring_bonus + topic_trace_bonus
total = base × type_boost + review_bonus + memory_score × 0.5 + goal_boost
```

1. **词项重叠 ×0.3 + IDF 加权** — jieba 分词，稀有 term 加权（CV from TreeSearch `estimate_idf`）
2. **子串匹配 +1.0/+0.5** — 标题/正文含 query 串
3. **话题关联 +2.0** — discuss trace topic_id 匹配
4. **类型乘数 ×1.5/×0.8/×0.6** — anti-pattern / strategy / concept
5. **失败加成 +2.0/+1.0** — decision_correct=false / outcome=failure
6. **记忆曲线 ×0.5** — memory_score（衰减系统算）
7. **目标加成 +0.8/+0.4（可选）** — area ∈ goal domains / goal keyword

{: .note }
**灵魂因子去向（v0.6.0）**：type_boost + review_bonus + generic_demotion → fts5 注入层 `injection_boost`（`score_components.injection_boost`，`--explain` 可见）；memory curve → `store.py` apply_decay 独立系统；goal_boost → fts5 注入层重排。召回算分类（token overlap / substring / topic trace）被 fts5 BM25 node-level 取代（R@1 0.825 > 0.525）。

## 双层记忆架构

OKS 的双路召回天然是"双层记忆架构"——结构化概览常驻 + episodic 细节按需：

| 层 | 来源 | 角色 |
|----|------|------|
| 概览（常驻候选） | `wiki/` | 结构化、人审过的稳定知识，fts5 node-level 召回 + 灵魂 boost 后顶在排序前列 |
| 细节（按需召回） | `raw/` | episodic 原文，关键词 + 新鲜度，补 wiki 没覆盖的细节 |

## 技术取舍

OKS 不学主流 RAG 的稠密嵌入 / 神经重排序，是 P4（CLI 核心不调 AI API）的直接后果：

| 主流 RAG 技术 | OKS 对应 / 取舍 |
|---------------|----------------|
| 稠密嵌入（embedding） | 不做（核心）——要模型 + 向量索引；connector 扩展点已就位 |
| BM25（词频饱和 + 长度归一化） | ✅ 做——fts5 backend 用 SQLite FTS5 + BM25 + node-level |
| 混合检索 + RRF 融合 | fusion 实验位（fts5 + native re-rank），但实测低于纯 fts5 |
| 神经重排序（跨编码器） | 不做——要 LLM 调用；oks 用 type boost + review bonus 做注入层规则 boost |
| 上下文感知检索（LLM 补前缀） | **零成本平替**：OKS 的 frontmatter（title/area/tags）就是手工上下文前缀 |

![上下文感知检索：传统分块 vs 加上下文前缀](../assets/contextual-retrieval.svg)

*图源：[《深入理解 AI Agent》第3章](https://github.com/bojieli/ai-agent-book) fig3-14，Apache-2.0*

## 指标

`oks eval recall <dataset.yaml> --output <run.json>` 支持 recall@k / MRR / nDCG。v0.6.0 有 50-case 数据集（`records/experiments/eval-50.yaml`），三后端对比见 [召回评估](recall-evaluation.html)。

`oks recall "<q>" --explain` 给每个 hit 的 `score_components`（fts5_score + injection_boost + backend + node）。

## 结论

fts5 node-level 是 v0.6.1+ 的默认召回（OKS Triple-Layer Recall 的 Node-BM25 层）——吸收 TreeSearch markdown tree parser，消融 R@1=0.825 / MRR=0.907，轻量、可解释、不调 AI、持久化索引。oks 灵魂（memory curve / goal boost / type boost / review bonus）分层到独立衰减系统 + 注入层 boost，不在召回层 re-rank。语义召回需 embedding（connector 扩展点已就位，待实现）。

OKS 提供的是 **Recall 原语，不是 agentic search**——单次查询返回结果，不做 ReAct 多轮迭代。多轮探索由 host Agent 在宿主层做。

召回是只读：查询不算使用，不推 `access_count`。`oks wiki use <slug>` 才 +1 驱动记忆曲线——记忆热度反映"真被用上"而非"被搜过几次"。
