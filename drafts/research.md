---
title: Research Proposal
draft_type: strategy
draft_area: research
source_pages:
- reproducibility-checklist
- peer-review-etiquette
- citation-system
- paper-structure
- figure-design
drafted_at: '2026-07-11'
status: draft
---

# Research — Wiki Proposal

> Drafted from 5 wiki pages. Sources: reproducibility-checklist, peer-review-etiquette, citation-system, paper-structure, figure-design.

Proposed type: `strategy` | Area: `research`

## 可复现性 checklist
# 可复现性 checklist

## 投稿前必填（NeurIPS 风格）

### 数据
- [ ] 数据集名称 / 来源 / 版本号
- [ ] 预处理步骤完整描述
- [ ] 数据划分（train/val/test 比例 + 是否固定 random seed）
- [ ] 公开数据集：给 DOI / link；私有数据集：解释为什么不公开

### 代码
- [ ] 代码 link（GitHub / Zenodo with DOI）
- [ ] README 含一行命令复现主结果
- [ ] requirements.txt / environment.yml 含精确版本（pin）
-

## 同行评议礼仪（写 review + 回 rebuttal）
# 同行评议礼仪

## 写 Review 的规范

### 结构（5 段固定）

1. **Summary**: 复述论文做了什么（证明你读了）
2. **Strengths**: 至少 2 条 具体的
3. **Weaknesses**: 至少 2 条 具体的（不模糊）
4. **Questions**: 给作者澄清的机会
5. **Score + Recommendation**

### 必做

- ✅ 给出具体行号 / 公式编号 / 图编号引用
- ✅ 对每个 weakness 提建议（不只是吐槽）
- ✅ 区分"主要"和"次要"问题
- ✅ 主动认知自己的 expertise 边界

## 引用系统（BibTeX / DOI / arXiv）
# 引用系统

## 3 种主要标识

| 标识 | 用途 | 例子 |
|------|------|------|
| **DOI** (Digital Object Identifier) | 正式出版物 | `10.1038/nature12373` |
| **arXiv ID** | 预印本 | `2106.04528` 或 `arXiv:2106.04528` |
| **BibTeX key** | 本地引用别名 | `vaswani2017attention` |

## BibTeX 模板

### Conference

```bibtex
@inproceedings{

## 学术论文 IMRaD 结构
# 学术论文 IMRaD 结构

## 核心结构（Introduction / Methods / Results / Discussion）

```
1. Abstract            (200-250 字，4 要素：problem / approach / finding / impact)
2. Introduction        (大背景 → 未解决问题 → 本文方法 → 贡献清单 → 结构导航)
3. Related Work        (按主题分块，每块结尾"区别于本文")
4. Methods             (整体框架图 + 各组件 + 关键决策 +

## 科研图表 5 原则
# 科研图表 5 原则

## 原则 1: 最大化数据墨水比（Data-Ink Ratio，Tufte）

> "Above all else show the data."

- ❌ 3D 柱状图（多余视觉噪音）
- ❌ 重影 / 阴影 / 渐变（无信息含量）
- ❌ 厚边框 / 网格密 / 装饰花纹
- ✅ 极简坐标轴 + 数据点本身突出 + 标签精确

**衡量方法**：每个像素是否传递了不可替代的信息？

## 原则 2: 颜色弱化原则

- **主体颜色 ≤3 种**（含背景白）
- 用**灰色作为对照基线**，彩色突出焦点数据
- 默认调色板：**ColorBrewer** 或 *


---
Review and merge into wiki/ if valuable, or discard.