---
title: "open-knowledge-studio — 知识工程仓库"
type: context
tags: [open-knowledge-studio, knowledge-base, cli, recall-engine, current]
area: computing

confidence: 0.9
confidence_reason: "核心项目，持续开发中"
last_verified: 2026-07-13
verification_status: verified
verification_count: 5

created: 2026-06-04
last_accessed: 2026-07-13
access_count: 1
recent_accesses:
  - 2026-07-13T00:00:00+08:00
ttl_days: 365
status: active

source: human-maintained
---

# open-knowledge-studio — 知识工程仓库

## 概述

open-knowledge-studio 是一个面向 Claude Code 的知识工程仓库，提供 4 认知桶 + 2 基础设施层的记忆架构、6 因子召回引擎、衰减系统和 Dreaming 蒸馏管线。核心管线：raw → wiki → 检索/召回。

## 记忆架构（4 认知桶 + 2 基础设施层）

| 桶 | 类别 | 用途 | 衰减 | 召回 |
|----|------|------|------|------|
| `profiles/` | 认知 | 团队/用户/项目画像 | 无 | 直接读取 |
| `raw/` | 认知 | 原始记录（对话、trace、Bundle） | 无 | 关键词 + 新鲜度 |
| `wiki/` | 认知 | 策展知识（raw 经 Dreaming 蒸馏） | 类型特定 λ | 6 因子相关性 + 曲线 |
| `drafts/` | 认知 | Dreaming 候选（raw → wiki 中间态） | 无 | 人工审查 |
| `settings/` | 基础设施·配置 | 系统配置、handlers 路由表 | 无 | 直接读取 |
| `_meta/` | 基础设施·schema | 版本化契约（CI 校验） | 无 | 直接读取 |

## 技术栈

- **CLI**: Python 3.12 + Typer + Rich + jieba + gitpython
- **知识格式**: Markdown + YAML frontmatter
- **召回引擎**: 6 因子相关性评分 + 记忆曲线
- **衰减系统**: 类型特定 λ + tier 分级
- **Claude Code**: 8 个技能 + 3 个 hooks + 2 个 rules

## CLI 命令（`oks`）

```bash
oks search <query>          # 搜索/召回
oks wiki list/get/create    # 知识管理
oks drafts list/promote     # 草稿工作流
oks distill                 # 蒸馏
oks lint | status | metrics  # 维护
oks sync                    # Git 同步
```

## 核心算法

### 6 因子召回

| 因子 | 权重 | 说明 |
|------|------|------|
| Token overlap | ×0.3 | jieba 分词后交集 |
| Substring match | +1.0/+0.5 | 标题 +1.0，正文 +0.5 |
| Topic trace | +2.0 | trace.id == topic_id |
| Type boost | 1.5/0.8/0.6 | anti-pattern/strategy/concept |
| Review penalty | +2.0/+1.0 | decision_correct=false / outcome=failure |
| Memory-curve | ×0.5 | importance × e^(-λt) + 0.5×ln(1+access) |

### 衰减系统

```
score = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

类型特定 λ：concept=0.0, strategy=0.014, anti-pattern=0.010

Tier：hot ≥0.7, warm ≥0.4, cold ≥0.15, evictable <0.15

## 北极星目标

打造一个自驱进化的知识库 — raw → wiki → 召回，让每次 AI 交互都沉淀知识，下次更聪明。

## 22 个知识域

management, transport, finance, production, computing, repair, engineering, construction, science, agriculture, social, administration, legal, sales, education, personal, media, healthcare, care, maintenance, food, security
