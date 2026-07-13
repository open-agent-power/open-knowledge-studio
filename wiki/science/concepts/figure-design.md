---
title: 科研图表 5 原则
tags:
- research
- figure
- visualization
- data-ink
- accessibility
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
- 默认调色板：**ColorBrewer** 或 **viridis**（科研友好色盲安全）
- **学术配色推荐**：
  - **Nature 风格**: 深蓝 #1f78b4 / 橙 #ff7f00 / 绿 #33a02c
  - **CB-safe**: viridis 渐变 + diverging RdBu
  - **印刷友好**: 高对比黑 #000 / 白 #fff + 1-2 个亮色

## 原则 3: 视觉对比层次

- 标题字号 > 轴标签 > 刻度 > 注释
- 主曲线粗（lw=2）+ 辅助曲线细（lw=1）+ 参考线虚线
- 重要数据点用 marker + annotation 突出

## 原则 4: 一致性

- **整篇论文**用同一调色板（color identity）
- **每个变量**用同一颜色（如 "method A 永远是蓝色"）
- **坐标范围**对齐（多子图比较时）
- **字体**统一（推荐 Helvetica / Arial / TeX Gyre Heros）

## 原则 5: 可访问性（Accessibility）

- 色盲友好（避免 red-green 单独编码，必加 marker 形状区分）
- 黑白打印仍可分辨（用 line style / marker 而非纯色）
- alt text 描述（投顶刊必带）
- 字号 ≥8pt（即使打印缩小）

## Matplotlib 模板配置

```python
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "Helvetica",
    "font.size": 10,
    "axes.linewidth": 0.5,           # 细边框
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 2,
    "lines.markersize": 6,
    "legend.frameon": False,
    "savefig.dpi": 300,              # 投稿要求
    "savefig.bbox": "tight",
    "figure.figsize": (3.5, 2.5),    # 单栏图典型尺寸（inch）
})

# 调色板
COLORS = {
    'primary': '#1f78b4',    # 深蓝
    'secondary': '#ff7f00',  # 橙
    'tertiary': '#33a02c',   # 绿
    'baseline': '#7f7f7f',   # 灰（对照）
}
```

## 反模式

- ❌ 用 jet / rainbow 调色板（科研禁忌：感知非线性 + 色盲不友好）
- ❌ 饼图（数据量 >5 时不可读，用条形图）
- ❌ 双 y 轴（多数情况误导）
- ❌ 一图 >5 条线（用 subplot 拆分）
- ❌ 把所有数据塞一张图（信息密度过高 → 看不清）
