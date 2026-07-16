---
title: 衰减系统
nav_order: 15
parent: 内部机制
---
# Decay System（衰减系统）

*记忆曲线、类型特定 λ 与 tier 分级——知识如何随时间衰减。*

知识随时间衰减，衰减率由类型决定。

## 记忆曲线

```
score = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

Active 页面获得 ×1.2 乘数。Dropped/archived → 0.0。

- **importance** — 页面的重要性（0.0-1.0），人工设定
- **e^(-λ × days_old)** — 时间衰减，λ 越大衰减越快
- **ln(1 + access_count)** — 访问增强，被访问越多分数越高
- **pin_bonus** — 固定页面加成（默认 0.5）

## 类型特定衰减（λ）

| 类型 | λ | 行为 |
|------|---|------|
| concept | 0.0 | 不衰减 — 概念是永恒的 |
| strategy | 0.014 | 缓慢衰减 — 策略会过时但周期长 |
| anti-pattern | 0.010 | 中等衰减 — 教训会随场景变化 |
| unknown | 0.030 | 快速衰减（fallback） |

{: .note }
Concept 不衰减是因为 "什么是 REST API" 这类知识不会过时。Strategy 衰减最慢是因为 "用微服务拆分单体" 这类策略在几年内仍然有效。Anti-pattern 衰减略快是因为 "不要用 var 声明变量" 这类教训会随语言演进而变化。

## Tier 分级

| Tier | Score | 行为 |
|------|-------|------|
| hot | ≥ 0.7 | 优先召回 |
| warm | ≥ 0.4 | 正常召回 |
| cold | ≥ 0.15 | 低优先级 |
| evictable | < 0.15 | 归档候选 |

分数越高的页面在召回时排序越靠前。Evictable 级别的页面是归档候选 — 系统会在下一次 `oks distill` 时考虑将其标记为 `status: dropped`。

## 生命周期

```
Provisional → Active（access_count ≥ 3）→ Dropped（score < threshold）
```

- **Provisional** — 新创建的页面，尚未被足够访问
- **Active** — 被访问 3 次以上，成为正式知识
- **Dropped** — 分数低于归档阈值，被标记为 dropped

## 访问增强

每次页面被召回命中时，confidence 提升：

```python
new_confidence = min(1.0, current + 0.1 × (1 - current))
```

这意味着被频繁查询的知识会越来越"自信" — confidence 逐渐趋近 1.0 但永远不会达到。这是对有用知识的正反馈：越常被使用，越不容易被遗忘。

## 配置

`settings/decay-config.yaml`:

```yaml
archive_threshold: 0.3
pin_bonus: 0.5
```

- **archive_threshold** — 低于此分数的页面成为归档候选
- **pin_bonus** — Pinned 页面获得的额外分数

源码：`cli/knowledge_studio/store.py`

## 下一步

* **[知识库指标](metrics.md)**：`avg_score` 如何进入四维报告卡
* **[召回引擎](recall-engine.md)**：记忆曲线如何作为第六因子影响召回
* **[Dreaming 循环](dreaming-cycle.md)**：衰减在演化循环中的位置
* **[架构设计](architecture.md)**：五桶结构

---

{% include comments.html %}
