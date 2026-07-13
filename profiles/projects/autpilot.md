---
title: "autpilot — AI 自主编程平台"
type: context
tags: [autpilot, ai-coding, platform, current, core]
area: computing

confidence: 0.9
confidence_reason: "核心项目，持续开发中"
last_verified: 2026-07-11
verification_status: verified
verification_count: 5

created: 2026-01-01
last_accessed: 2026-07-11
access_count: 0
recent_accesses: []
ttl_days: 365
status: active

source: human-maintained
---

# autpilot — AI 自主编程平台

## 概述

autpilot 是一个 AI 自主编程平台，支持 Discuss（讨论）→ Goal（目标）→ Execution（执行）→ Learning（学习）的完整闭环。平台通过六桶记忆架构管理知识，通过多 AI 提供商支持灵活接入。

## 三仓架构

| 仓库 | 角色 |
|------|------|
| `autpilot-web` | UI + API + CLI + E2E |
| `autpilot-plugins` | Claude Code 插件市场（4 个插件） |
| `autpilot-knowledge` | Git 同步共享知识库 — 六桶认知架构 |

## 技术栈

- **后端**: FastAPI + uvicorn + SQLite + asyncio
- **前端**: React 18 + Vite + TypeScript + Tailwind CSS v4 + TanStack Query v5 + Zustand
- **AI**: 多提供商（Anthropic, GLM, DeepSeek, Kimi, Qwen, MiniMax, Custom）
- **设计系统**: NeoBrutalism (retroui 原子组件)
- **E2E**: Playwright

## 核心功能

### Discuss（讨论）
AI 驱动的讨论页面，支持多 topic 管理、目标提案、年月日选择器。

### Goal Pipeline（目标管线）
8 阶段执行管线：Prepare → Assemble → Remote → Resolve → Env → Agent → Collect → Finalize → Cleanup。

### Learning（学习）
7-tab 知识库查看器：Profiles、Raw、Wiki、Skills、Drafts、Settings、Knowledge。

### Knowledge（知识库）
六桶架构：profiles/、raw/、wiki/、skills/、drafts/、settings/。

## 六桶记忆架构

| 桶 | 用途 | 衰减 | 召回 |
|----|------|------|------|
| `profiles/` | 团队/用户/项目画像 | 无 | 直接读取 |
| `raw/` | 原始记录（对话、trace、摘要） | 无 | 关键词 + 新鲜度 |
| `wiki/` | 策展知识（raw 经 Dreaming 蒸馏） | 类型特定 λ | 6 因子相关性 + 曲线 |
| `skills/` | 工具进化（可执行程序） | 无 | 关键词触发 |
| `drafts/` | Dreaming 候选（raw → wiki 中间态） | 无 | 人工审查 |
| `settings/` | 系统基础设施 | 无 | 查询 |

## 北极星目标

实现 autpilot 1.0 发布 — 让 AI 能够自主完成从需求讨论到代码实现的全流程。

## 22 个知识域

management, transport, finance, production, computing, repair, engineering, construction, science, agriculture, social, administration, legal, sales, education, personal, media, healthcare, care, maintenance, food, security
