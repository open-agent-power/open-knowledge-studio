---
title: 召回评估
nav_order: 5
parent: 维护者
nav_exclude: true
search_exclude: true
---
# 召回评估（OKS Triple-Layer Recall 消融实验）

`oks eval recall <dataset.yaml>` 支持离线评测召回质量。这一页讲评估方法论——三层次能力框架 + 三个量化指标——以及 OKS 当前的位置和阻塞。

> 下文的数值是绑定固定 50-case 数据集和当时运行记录的历史基准，不是所有知识库、机器或 backend 的通用 SLA。修改代码或评测环境后，请按文末命令重新运行。

## 三层次能力框架

借鉴长期对话记忆研究（LoCoMo 等），用户记忆能力可分三层递进：

| 层次 | 能力 | 例子 | OKS 当前 |
|------|------|------|----------|
| **第一层：基础回忆** | 存取用户直接给的、结构化、无歧义信息 | "我的会员号是 12345"→精确返回 | ✅ `oks recall` 单次召回 |
| **第二层：多会话检索** | 跨对象 / 时间找全相关信息 + 推理判断 | 两辆车问"为我的车预约"→找全两辆 + 问哪辆 | ⚠️ 部分——`raw/` 按时间分区，双路召回能跨会话，但无多跳推理 |
| **第三层：主动服务** | 跨会话深层关联，预见性主动帮助 | 订国际航班→关联数月前护照→预警将过期 | ❌ 不做——需 Agent 层主动推理，OKS 只提供召回原语 |

OKS 定位在第一层 + 第二层基础：`oks recall` 是 Recall 原语，第三层"主动服务"要 host Agent 在宿主层做（调 recall + 推理 + 再调 recall）。这是"Agent 状态栏注入 + Recall 原语"的边界——OKS 不替 Agent 思考。

## 三个量化指标

召回质量在带标注答案的测试集上算（query + 期望命中页）：

| 指标 | 回答什么 | 公式直觉 |
|------|---------|---------|
| **recall@k**（召回率@k） | 前 k 个结果含正确答案的查询比例——"该找的找到了吗" | 命中查询数 / 总查询数 |
| **MRR**（平均倒数排名） | 第一个相关结果排名的倒数平均——"找到得够不够靠前" | Σ 1/rank ÷ 查询数；排第 1 得 1 分，第 10 得 0.1 分 |
| **nDCG**（归一化折损累积增益） | 整个排序列表质量，排名越靠后折扣越大——"整个列表质量如何" | 考虑所有相关文档排名 + 相关程度 |

工业报告常见"检索失败率" = 1 − recall@k（如 top-20 未命中率）。跨来源比较先弄清 k 取多少、recall@k 是命中率还是相关文档比例。

## OKS 现状

`oks eval recall <dataset.yaml> --output <run.json>` 跑评测：

- **输入**：YAML 数据集（query + 期望命中 slug 列表 + 可选 `topic_id`）
- **输出**：每个 query 的召回结果 + 三指标聚合 + `--explain` 逐项分数
- **基线**：`--goal none` 无偏基线，`--goal <slug>` 固定 goal 可复现

**阻塞**：OKS 无官方标注数据集——三指标要 query + 期望命中页，需人工标注。社区可自建（把常用 query + 该命中的 wiki 页标好）。在标注数据集就绪前，召回评分权重不盲调（P9 精神）——只能用 `--explain` 做定性检查。

## v0.6.1 实测：OKS Triple-Layer Recall 消融实验

v0.6.1 把三层架构（召回 fts5 node-level / 注入 Soul Boost / 衰减 Memory Curve）定名 **OKS Triple-Layer Recall**。在 50 个语义改写 case（query 不含 slug 关键词，测试同义词/改写召回，严格精确 slug 匹配）上做消融实验：

| backend | R@1 | R@3 | R@5 | MRR | nDCG@5 | p50 延迟 |
|---------|------|------|------|------|---------|----------|
| **fts5（完整 Triple-Layer）** | **0.825** | **0.925** | 0.927 | **0.907** | **0.893** | 93ms |
| native（去 Node-BM25，回 page-level 6+1） | 0.525 | 0.647 | 0.689 | 0.630 | 0.624 | 137ms |
| fusion（fts5 + native re-rank） | 0.805 | 0.905 | 0.927 | 0.900 | 0.887 | 226ms |

### 关键发现（数据驱动）

1. **Node-BM25 全面碾压 native 6+1**——召回层从 page-level 手写 token overlap 换成 fts5 node-level BM25：R@1 +57%（0.525→0.825）、R@3 +43%（0.647→0.925）、MRR +44%（0.630→0.907）。多词同段 BM25 高分，语义改写召回精准。
2. **fusion re-rank 反而降精度**——native 6+1 的 memory curve / goal boost / review bonus 在召回层 re-rank 拖累（R@1 0.825→0.805，MRR 0.907→0.900）。证实 **oks 灵魂应在注入层 boost，不在召回层 re-rank**——不相关 page 高分挤掉精确命中。
3. **fts5 还更快**——93ms vs native 137ms vs fusion 226ms。SQLite 持久化索引比实时遍历快，fusion 因双路调用最慢。
4. **R@5 三者接近**（0.689/0.927/0.927）——fts5 优势集中在 top-1/top-3 精准排序，top-5 宽网 native 也能捞到。

### 三层消融拆解

| 消融 | 去掉什么 | R@1 | MRR | 证明 |
|------|---------|------|------|------|
| 完整 Triple-Layer | — | 0.825 | 0.907 | baseline |
| 去 Node-BM25 | 召回层 fts5→native 6+1 | 0.525 | 0.630 | Node-BM25 是精度主力（-36%） |
| 去 Soul Boost（fusion re-rank 误用） | 灵魂因子搬回召回层 re-rank | 0.805 | 0.900 | 灵魂在注入层才对，召回层 re-rank 是负优化 |

### embedding backend 对比（语义召回 connector 扩展）

v0.6.2 加 embedding backend（oks-connector[embedding]，sentence-transformers
本地 MiniLM，不调远程 API）。语义召回本应解决同义词鸿沟，实测却反直觉：

| backend | R@1 | R@3 | R@5 | MRR | p50ms |
|---------|------|------|------|------|-------|
| **fts5（Node-BM25 字面）** | **0.825** | **0.925** | 0.927 | **0.907** | 93 |
| embedding（语义 cosine） | 0.617 | 0.737 | 0.817 | 0.733 | 18304 |

**为什么 embedding 反不如字面 BM25？**

1. **中文术语重合高**——50-case 是语义改写但 query 与 wiki 用词高度重合（中文技术术语），BM25 字面已能命中，embedding 的语义泛化反而引入噪声（"自进化"→ auto-knowledge-distillation 而非 ai-native-strategy）。
2. **R@5 接近**（0.817 vs 0.927）——embedding 宽网捞得到，但排序精度差。
3. **慢 18304ms**——MiniLM CPU 每页 embed ~250ms，需 GPU 或 query embedding 缓存。

**决策**：fts5 Node-BM25 仍是默认最优（R@1=0.825 + 93ms）。embedding 作语义鸿沟的 **fallback 补充**（fts5 miss 时走 embedding），不替代默认。语义召回的真正价值在大库 + 跨语言 + 同义词重的场景。

### 决策

- 算法定名 **OKS Triple-Layer Recall = Node-BM25（召回）+ Soul Boost（注入）+ Memory Curve（衰减）**。
- 默认 `search_backend: fts5`（R@1=82.5% 最优召回）。
- native (6+1) 退为向后兼容召回（page-level，无 SQLite 依赖，`--search-backend native` 仍可跑）。
- fusion 退为实验位（灵魂 re-rank 在召回层是负优化）。

复现：`oks eval recall records/experiments/eval-50.yaml --output run.json --search-backend {fts5|native|fusion}`。run json 归档于 `records/experiments/runs/`。

## 评测驱动调权

有标注数据集后，评测驱动调分：

1. 建基线（`--goal none` + 默认权重）跑 recall@k / MRR / nDCG
2. 调一个因子（如 type boost ×1.5→×1.8）重跑
3. 看三指标变化——升则保留，降则回滚
4. 逐因子迭代，每步只动一个

不靠直觉调权重——Triple-Layer 三层互相耦合，盲调一处可能拖垮全局。v0.6.1 实测已证明：召回层加 native re-rank（看似"增强"）反而降 R@1 2.4pp。
