---
title: 学术论文 IMRaD 结构
tags:
- research
- paper
- imrad
- structure
area: research
source: session/research-paper-figure-20260604
last_verified: 2026-06-04
type: concept
status: active
importance: 0.7
confidence: 0.9
created: 2026-06-04
pinned: false
archived: false
access_count: 0
---

# 学术论文 IMRaD 结构

## 核心结构（Introduction / Methods / Results / Discussion）

```
1. Abstract            (200-250 字，4 要素：problem / approach / finding / impact)
2. Introduction        (大背景 → 未解决问题 → 本文方法 → 贡献清单 → 结构导航)
3. Related Work        (按主题分块，每块结尾"区别于本文")
4. Methods             (整体框架图 + 各组件 + 关键决策 + 复杂度分析)
5. Experiments         (数据集 / metric / baseline ≥2 / 主实验 / ablation / case study)
6. Discussion          (含 limitations，**主动列**)
7. Conclusion + Future Work
References             (BibTeX)
```

## 投稿差异

| venue | 字数 | 结构 |
|-------|------|------|
| 顶会论文 (NeurIPS / CVPR / ACL) | 6-10 页 | IMRaD 标准 |
| 期刊 (TPAMI / Nature) | 15-25 页 | + Background / Limitations / Future Work |
| 内部白皮书 | 不限 | Exec Summary / Background / Approach / Results / Roadmap |
| Workshop paper | 4-6 页 | 简化 IMRaD |

## 各段写作要点

### Abstract（最后写，必须精准）
- 公式：`<problem> + <approach> + <main finding> + <impact>`
- **反模式**：开头堆背景，第 3 段才说核心贡献

### Introduction（5 段固定结构）
1. 大背景（1-2 句）
2. 未解决的问题 + 现有方案缺陷
3. 本文方法 high-level
4. 贡献清单（bullets，3-5 条）
5. paper 结构导航

### Related Work（按主题分块）
每块结尾必须有「区别于本文」对比，避免变成 reference dump：
```
## A. <Topic>
<ref1> 和 <ref2> 做了 X，但 limitation 是 Y。本文 focus 在 Z（不同于 Y）。
```

### Method（必须有图）
- 整体框架图
- 各组件分小节
- 关键决策 + 替代方案（reviewer 一定会问"why not X"）
- 复杂度分析（time / space）

### Experiments（5 件套）
1. 数据集 + 评测指标
2. baselines（≥2 个）
3. 主实验 table
4. ablation study（每个设计决策 ON/OFF）
5. case studies（≥2 个有趣 case）

### Discussion + Limitations（**主动列**）
- 不要只说 strengths（reviewer 会觉得幼稚）
- 主动列 limitations（reviewer 信任度提升）
- 列 future work（暗示后续可发 paper）

## 反模式

- ❌ Abstract 开头堆背景
- ❌ Related work 不做对比（变成 reference dump）
- ❌ Method 没图
- ❌ Experiments 只跑自己方法（无 baseline = 不可比）
- ❌ Discussion 全是 strengths
- ❌ Limitations 藏起来（reviewer 一发现就质疑）
