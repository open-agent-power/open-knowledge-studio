---
title: 引用系统（BibTeX / DOI / arXiv）
tags:
- research
- citation
- bibtex
- doi
area: research
source: session/research-paper-figure-20260604
last_verified: 2026-06-04
type: concept
status: active
importance: 0.7
confidence: 0.85
created: 2026-06-04
pinned: false
archived: false
access_count: 0
---

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
@inproceedings{key2024title,
  author    = {Author One and Author Two},
  title     = {Paper Title},
  booktitle = {Proceedings of the X Conference},
  year      = {2024},
  pages     = {1--10},
}
```

### Journal

```bibtex
@article{key2024title,
  author  = {Author One and Author Two},
  title   = {Paper Title},
  journal = {Journal Name},
  volume  = {12},
  number  = {3},
  pages   = {100--120},
  year    = {2024},
  doi     = {10.xxxx/xxxxx},
}
```

### arXiv

```bibtex
@misc{key2024preprint,
  author        = {Author One},
  title         = {Preprint Title},
  year          = {2024},
  eprint        = {2106.04528},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
}
```

## 引用 key 命名约定

```
<first-author-last><year><first-noun>
例: vaswani2017attention / he2016resnet
```

避免：
- `paper1` / `ref23` （无意义）
- 中文 key（部分 LaTeX 编译器不支持）

## 引用工具链

- **Zotero**: 文献管理 + 自动导 BibTeX
- **Better BibTeX**: Zotero 插件，生成稳定 key
- **arxiv2bibtex.org**: 快速从 arXiv link 导
- **doi.org**: DOI 解析

## 引用礼仪

| 场景 | 做法 |
|------|------|
| 介绍 prior art | 必须引原文，不引 review |
| 比较 baseline | 引最新版本（如 v2 vs v1）|
| 引方法名 | 第一次引时给完整作者 + 简称（"BERT \citep{devlin2019bert}"）|
| Self-citation | 控制 ≤10%，避免被 review 质疑 |
| 引网页 | 用 `@misc{...,url=,note={Accessed: 2026-06-04}}` |

## 反模式

- ❌ 引用 "[1, 2, 3]" 不点明哪个 ref 说什么
- ❌ 不读原文就引（reviewer 一抽查就翻车）
- ❌ 引用过时综述代替原始论文
- ❌ Self-citation 占 30%（拒稿风险）
- ❌ BibTeX 缺字段（作者 / 年份 / venue 必填）
