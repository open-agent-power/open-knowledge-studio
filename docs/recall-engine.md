# 6-Factor Recall Engine（六因子召回引擎）

使用六个因子对 wiki 页面评分，找到最相关的知识。引擎将语义搜索、关键词匹配和图谱关联融合在一次统一的评分过程中。

## 三种搜索模式合一

| 模式 | 做什么 | 哪些因子 |
|------|--------|----------|
| **Semantic（语义）** | 按含义查找，不只是精确匹配 | Token overlap |
| **Keyword（关键词）** | 精确匹配特定术语 | Substring match |
| **Graph（图谱）** | 通过主题关联和类型加权查找 | Topic trace + type boost + review penalty |

三种模式在每次查询时自动运行。6 因子引擎将它们与记忆曲线乘数结合，生成最终相关性评分。

## 评分公式

```
total = (token_overlap×0.3 + substring_bonus + topic_trace_bonus)
        × type_boost + review_penalty
        × memory_curve
```

## 六个因子

### 1. Token Overlap（×0.3）

jieba 分词将查询和页面内容拆分为 token。重叠率衡量查询 token 中有多少出现在页面中。

```
overlap = len(query_tokens ∩ page_tokens) / len(query_tokens) × 0.3
```

这是**语义层** — 搜索"design patterns"时能找到关于"architectural approaches"的页面，因为 token 重叠捕捉到了共享概念。

### 2. Substring Match（+1.0 / +0.5）

直接字符串匹配，属于**关键词层**：

- 标题包含查询字符串：**+1.0**
- 正文包含查询字符串：**+0.5**

两者可叠加 — 标题和正文都包含查询的页面获得 +1.5。

### 3. Topic Trace（+2.0）

如果页面是从特定对话主题创建的，而你用同一个 `topic_id` 查询，页面获得 **+2.0** 加成。这是**图谱关联** — 将 memory 关联回产生它的对话。

```python
if page.get("trace_id") == topic_id:
    relevance += 2.0
```

### 4. Type Boost（×1.5 / ×0.8 / ×0.6）

不同知识类型有不同的召回优先级。这是一个**乘法因子**，不是加法：

| 类型 | Boost | 原因 |
|------|-------|------|
| `anti-pattern` | ×1.5 | 错误最值得召回 — 在重蹈覆辙之前发现它们 |
| `strategy` | ×0.8 | 策略有用但不如错误紧迫 |
| `concept` | ×0.6 | 概念是背景知识 — 优先级最低 |

### 5. Review Penalty（+2.0 / +1.0）

来自失败决策或负面结果的页面获得加成，因为你需要回忆出了什么问题：

- `decision_correct = false`：**+2.0**
- `outcome = failure`：**+1.0**

这看似反直觉 — 为什么加成"坏"知识？因为最有价值的知识往往是"我们试了 X 但没用"。回忆失败可以防止重蹈覆辙。

### 6. Memory Curve（×0.5）

记忆曲线应用基于页面年龄、访问次数和重要性的时间衰减乘数：

```
curve = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

- Active 页面获得 ×1.2 乘数
- Archived/dropped 页面为 0.0（从召回中排除）
- 高频访问的页面抵抗衰减
- Pinned 页面获得 +0.5 加成

详见 [Decay System](decay-system.md)。

## 双路召回

| 路径 | 来源 | 评分 |
|------|------|------|
| **Episodic** | `raw/` + `profiles/` | 关键词 + 新鲜度（`0.95^days_old`） |
| **Knowledge** | `wiki/` | 6 因子相关性 + 记忆曲线 |
| **合并** | 两者 | `{"episodic": [...], "knowledge": [...]}` |

```bash
# 仅 Episodic（raw materials）
oks search "authentication" --source raw

# 仅 Knowledge（wiki 页面）
oks search "authentication" --source wiki

# 双路（默认）
oks recall "authentication" --limit 5
```

## 实现

源码：`cli/knowledge_studio/recall.py`

核心函数：
- `recall_episodic(query)` — 按关键词 + 新鲜度搜索 raw/
- `recall_knowledge(query, topic_id)` — 通过 6 因子评分所有 wiki/ 页面
- `recall(query, topic_id)` — 合并双路

## 下一步

* **[Memories](memories.md)**：Memory 结构、类型和创建路径
* **[Decay System](decay-system.md)**：记忆曲线公式和 tier 分级
* **[Architecture](architecture.md)**：五桶结构
