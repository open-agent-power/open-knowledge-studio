---
title: 召回引擎
nav_order: 1
parent: 算法
---
# 召回引擎（6+1 因子评分）

`oks recall` 是唯一召回入口。默认合并 Raw episodic 与 Wiki knowledge；`--knowledge-only` 只查 Wiki。`raw/executions/` 和 `raw/.logs/` 是 provenance，不参与召回。

## 难题背景

知识库随时间增长，`wiki/` 累积成百上千页。用户或 Agent 提一个 query，如何找到最相关知识并排序？

两条路：

- **语义召回**（embedding 相似度）——效果好，但 CLI 核心不调 AI API（P4），本地跑 embedding 模型成本高。
- **关键词召回**（字面匹配）——轻量，但跨表述召回差（搜"design patterns"命中不了只写"architectural approaches"的页）。

OKS 选了第二条，但用多因子评分把"关键词匹配"做到比纯计数更聪明：融合词项、子串、话题关联、知识类型、失败教训、记忆曲线、目标加成——7 个信号一次评分。

## 技术设计

双路召回：

| 路径 | 来源 | 评分 |
|------|------|------|
| Episodic | `raw/` + `profiles/` | 关键词 + 新鲜度（`0.95^days_old`） |
| Knowledge | `wiki/` | 6+1 因子相关性 + 记忆曲线 |

评分公式：

```
base  = token_overlap_count × 0.3 + substring_bonus + topic_trace_bonus
total = base × type_boost
        + review_bonus
        + memory_score × 0.5
        + goal_boost      # 可选第 7 因子，无 active goal 时为 0
```

`base == 0` 直接出局；review 与 memory 是**加法项不是乘数**——没有字面命中的页靠记忆热度上不来。

## 原理（七因子）

1. **词项重叠 ×0.3 + IDF 加权 bonus** — jieba 分词，统计 query token 在标题+正文+标签的命中数。词项层，逐 token 字面。**IDF 加权**（CV from TreeSearch `estimate_idf`）：全库估算 term 稀有度（`log((N+1)/(df+1))+1`），稀有 term 命中权重高，作 bonus 加在 count×0.3 之上。**标题 term 命中 +0.3/个**（CV from TreeSearch `check_title_match`）：query term 逐个命中标题，补 whole-query substring 的盲区。
2. **子串匹配 +1.0/+0.5** — 标题含 query 串 +1.0，正文含 +0.5，可叠加（都含 +1.5）。关键词层，精确短语。
3. **话题关联 +2.0** — 页面带 discuss trace 且 topic_id 匹配查询的 topic_id，+2.0。图谱层，把 memory 关联回产生它的对话。
4. **类型乘数 ×1.5/×0.8/×0.6** — anti-pattern ×1.5（错误最该召回，防重蹈覆辙）、strategy ×0.8、concept ×0.6。乘法因子。
5. **失败加成 +2.0/+1.0** — `decision_correct=false` +2.0，`outcome=failure` +1.0。反直觉但合理：最有价值的知识常是"我们试了 X 没用"。
6. **记忆曲线 ×0.5** — 页面 memory_score（[衰减系统](decay-system.md) 算）×0.5 加法进入。Active ×1.2，archived=0。
7. **目标加成 +0.8/+0.4（可选）** — 页面 `area` ∈ active goal 的 `domains` +0.8，命中 goal keyword +0.4。只作用于 `relevance>0` 的页（不凭空顶无关页上来）。

## 双层架构

### 可插拔 search backend

Knowledge 路径的召回后端可插拔（`recall(search_backend=...)` 或 `OKS_SEARCH_BACKEND` env）：

- **native**（默认）：下文 6+1 因子 + jieba + IDF + title boost，实时遍历，无新依赖
- **fts5**（CV from TreeSearch FTS5Index）：SQLite FTS5 + BM25 + column weights（title 5x > tags 3x > body 1x > code 0.5x）+ 增量 diff（content_hash）+ 持久化索引（`.oks/fts5.db`）。大库（1000+ 页）比 native 遍历快。FTS5 不可用时降级 LIKE
- **fusion**：native top-3 主排序 + fts5 独有补盲 2，实验验证最优（避免 RRF 噪声稀释 native R@1）
- **connector**：第三方包经 `entry_points(group="oks_search_backend")` 注册（embedding / 代码 ast_parser / 其他开源 search 框架），OKS 核心不改

架构决策：不假设数据少——FTS5 持久化索引是大数据标配；embedding / 代码搜索等能力以 connector 方式自由扩展替换，而非硬编码进核心。

OKS 的双路召回天然是“双层记忆架构”——结构化概览常驻 + episodic 细节按需：

| 层 | 来源 | 角色 |
|----|------|------|
| 概览（常驻候选） | `wiki/` | 结构化、人审过的稳定知识，6+1 评分后顶在排序前列 |
| 细节（按需召回） | `raw/` | episodic 原文，关键词 + 新鲜度，补 wiki 没覆盖的细节 |

这是“结构化概览常驻 + 上下文检索按需取细节”理念在文件系统范式下的落地：wiki 页 frontmatter（title/type/area/tags）是结构化概览，raw 是按需拉取的原始证据。Agent 先看 wiki 概览，不够时 recall 双路补 raw 细节。

## 技术取舍

OKS 不学主流 RAG 的稠密嵌入 / BM25 / 混合检索 / 神经重排序，是 P4（CLI 核心不调 AI API）的直接后果：

| 主流 RAG 技术 | OKS 对应 / 取舍 |
|---------------|----------------|
| 稠密嵌入（embedding） | 不做——要模型 + 向量索引，OKS 用 IDF 加权 token overlap（无 embedding、无长度归一化） |
| BM25（词频饱和 + 长度归一化） | native 不做（fts5 backend 用 SQLite FTS5 + BM25） |
| 混合检索 + RRF 融合 | native 单路（fusion backend 并行 native + fts5 补盲） |
| 神经重排序（跨编码器） | 不做——要 LLM 调用，OKS 用 type boost + review bonus 做规则重排 |
| 上下文感知检索（LLM 补前缀） | **零成本平替**：OKS 的 frontmatter（title/area/tags）就是手工上下文前缀 |

![上下文感知检索：传统分块 vs 加上下文前缀](../assets/contextual-retrieval.svg)

*图源：[《深入理解 AI Agent》第3章](https://github.com/bojieli/ai-agent-book) fig3-14，Apache-2.0*

{: .note }
Anthropic 的上下文感知检索在索引期调 LLM 给每个文本块补“前缀摘要”（如“[ACME 公司 2025 Q2 财报·关键业绩指标]”），锚定语义环境。OKS 不调 LLM，但 frontmatter 的 `title`/`area`/`tags` 字段就是开发者 / Agent 手工写的同等“上下文前缀”——检索时这些字段参与 token overlap + 子串匹配，效果同源。代价是要人 / Agent 主动维护 frontmatter，不像 LLM 自动生成。

换来的好处：可解释（`--explain` 逐项分数）、零 AI 依赖、本地小-中知识库（百到千页）够用。代价：无语义召回（跨表述差）、无长度归一化。语义召回需 embedding，暂不做。

## 对比 nowledge 搜索架构

[Nowledge Mem](https://docs.nowledge.app) 的搜索综合 5 类语义信号 + 衰减置信度时间评分。对照 OKS：

| nowledge 信号 | OKS 对应 | 取舍 |
|--------------|---------|------|
| 按含义搜索（embedding 语义相似度）| — | ❌ 不做——P4 不调 AI，无向量索引 |
| BM25 关键词排序 | token overlap ×0.3（无权计数） | ❌ 简化——无倒排索引 + IDF |
| 标签匹配 | frontmatter `tags` 参与 token overlap + 子串 | ✅ 有——人工 / Agent 维护 |
| 图遍历（实体 / 主题社区） | `topic_trace`（discuss trace 关联对话） | ⚠️ 弱关联——无实体图 / 社区检测 |
| 时效性（半衰期 30 天） | `e^(-λ × days_old)`，类型 λ 差异 | ✅ 有——concept=0, strategy=0.014 |
| 频率（对数缩放） | `ln(1 + access_count)` | ✅ 有——收益递减 |
| 重要性底线 | `importance` + `pin_bonus` | ✅ 有——高重要性不衰减 |
| 置信度（只增不减 ~5%） | `confidence`（指纹命中 +0.1） | ⚠️ 更保守——只随内容证据，不随使用 |
| 时间匹配（事件 vs 记录时间） | — | ❌ 不做——无事件时间字段 |

**OKS 学了**：多信号融合 + 衰减（时效性 / 频率 / 重要性底线）+ 可解释（`--explain` 逐项分数 ≈ nowledge 分数分解）+ 双层架构（wiki 概览 + raw 细节 ≈ 结构化概览 + 按需细节）。

**OKS 不学 + 为什么**：

- **embedding / BM25 / 图遍历**——P4 不调 AI + 文件系统范式（无向量库 / 倒排索引 / 实体图）。token overlap 是无 embedding 的折中。
- **反馈循环（展示 / 点击 / 停留）**——OKS 是 CLI 无 UI 跟踪；`access_count` 只记 `oks wiki use`（真被用上），不记被搜过几次。防自我强化（P9）：被读多说明相关不说明正确。
- **搜索强化（v0.6.6 展示算轻度访问）**——OKS 反向选择：召回不算使用，`access_count` 只在 `oks wiki use` 时 +1。代价是记忆热度更新慢，换防自我强化回路。
- **时间意图检测 / 深度模式 LLM 分析 / 自动标签**——都要 LLM 调用，P4 不调 AI。OKS 只有“快速模式”（单次词项 + 子串 + 图谱评分），无“深度模式”（查询扩展 + 时间意图）。

**nowledge 的好概念（未来方向 / 对比）**：

- **时间理解**（事件时间 vs 记录时间）——raw 的 `created` 是记录时间；事件时间要 frontmatter 加 `event_time` 字段，需 Agent 提取（P4 边界）。
- **置信度只增不减**——OKS `confidence` 已有，但只在“同一份知识被独立重新推导”时 +0.1，不随使用增长——比 nowledge 更严格（nowledge ~5% 随展示 / 点击 / 图连接增长）。

## 指标

当前无标注数据集做召回率/精确率量化（已知阻塞）。能给的"指标"是可解释输出——`oks recall "<q>" --explain` 给每个 hit 的逐项分数 + reasons + goal_matches + rank。

总分可由下面字段精确重建：

```
final_score = typed_base
            + review_decision
            + review_failure
            + memory_score
            + goal_area
            + goal_keyword
```

JSON 响应版本 `recall-response/v1`，单条 `recall-hit/v1`。

## 实验

`oks eval recall <dataset.yaml> --output <run.json>` 支持离线评测——但需要标注数据集（query + 期望命中页）。现状无官方数据集，社区可自建。

- `--goal none` — 无偏基线
- `--goal <slug>` — 固定单一 goal，可复现实验
- `--goal active` — 默认，合并全部 active goal，适合交互使用

## 结论

6+1 是无 embedding 下的折中方案，适合本地小到中知识库（百到千页）。优点：轻量、可解释、不调 AI、类型/失败/目标感知。局限：无语义召回（跨表述差）、无长度归一化。语义召回需 embedding（大改，需模型+索引+标注量化），暂不做。

OKS 提供的是 **Recall 原语，不是 agentic search**——单次查询返回结果，不做 ReAct 多轮迭代（“召回→评估→再召回”）。多轮探索由 host Agent（Claude Code 等）在宿主层做：OKS 提供召回原语 + source label（防间接提示注入），Agent 决定要不要继续召回。这是 OKS“Agent 状态栏注入 + Recall 原语”定位的边界。

召回是只读：查询不算使用，不推 `access_count`。`oks wiki use <slug>` 才 +1 驱动记忆曲线——记忆热度反映“真被用上”而非“被搜过几次”。
