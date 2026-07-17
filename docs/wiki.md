---
title: Wiki 知识
nav_order: 18
parent: 内部机制
---

# Wiki 知识

`wiki/` 是**语义记忆**桶：经 Dreaming 蒸馏、人工审查后从 `raw/` 提升而来的
策展知识。它是召回引擎的主战场——每次查询都在这里做 6 因子相关性打分并叠加
记忆曲线。

## 定位

| 属性 | 值 |
|------|-----|
| 来源 | raw → drafts →（人工审查）→ wiki |
| 召回方式 | 6 因子相关性 + 记忆曲线 |
| 衰减 | 类型特定 λ |
| Scope | `domain`（知识域） |

## 目录与必填 Frontmatter

```
wiki/{domain}/{concepts|strategies|anti-patterns}/{slug}.md
```

每个 wiki 页面的 IDENTITY 三字段**均为必填**（见 [Frontmatter Schema](frontmatter-schema.html)）：

- `title` — 页面标题
- `type` — `concept` / `strategy` / `anti-pattern`
- `area` — 22 个知识域之一

其余为 TRUST（`status`、`importance`、`confidence`）、PROVENANCE
（`created`、`source_type`、`fingerprint`）、RELATIONSHIPS 等分组字段。

## 三种知识类型与衰减

衰减速率由类型决定（`store.py` `DECAY_LAMBDA`）：

| 类型 | λ | 含义 |
|------|-----|------|
| `concept` | 0.0 | 概念不衰减——原理长期有效 |
| `anti-pattern` | 0.010 | 反模式缓慢衰减 |
| `strategy` | 0.014 | 策略衰减最快——最容易过时 |
| （未知类型） | 0.030 | 默认兜底 |

分数落入 tier：`hot ≥ 0.7`、`warm ≥ 0.4`、`cold ≥ 0.15`、`evictable < 0.15`。

## 召回：6 因子相关性

`recall.py` `_compute_relevance` 对每个候选页面累加：

1. **Token 重叠** — 每命中一个查询词 `× 0.3`
2. **精确匹配** — 查询串出现在标题 `+1.0`、出现在正文 `+0.5`
3. **话题 trace** — 命中 `topic_id` 的 discuss trace `+2.0`
4. **类型加权** — 乘子：anti-pattern `× 1.5`、strategy `× 0.8`、concept `× 0.6`
5. **复盘信号** — `decision_correct=false` `+2.0`；`outcome=failure` `+1.0`
6. **记忆曲线分** — 当前 `score × 0.5`

反模式加权最高：踩过的坑最该被优先想起。

## 知识演化：4 种关系

Dreaming 的 Evolve 步骤在新页面与旧页面之间建立关系（见 [Dreaming 循环](dreaming-cycle.html)）：

| 关系 | 对旧页面的影响 |
|------|---------------|
| `supersedes` | 旧页面标记 `superseded`，排除出召回 |
| `enriches` | 两者保持 active，互相链接 |
| `confirms` | 旧页面 confidence `+0.1` |
| `challenges` | 旧页面标记 `[stale]`，待审查 |

知识不是只增不减的堆积——它通过这四种关系持续被替代、补充、确认、挑战。

## 核心不变量

> 绝不未经人工审查将 raw 提升到 wiki（CONSTITUTION.md A3）。

wiki 的可信度来自"raw 忠实 + 人工把关"这条链路，而非模型自证。
