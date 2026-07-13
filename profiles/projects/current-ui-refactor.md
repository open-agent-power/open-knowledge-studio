---
title: "当前 UI 重构项目"
type: context
tags: [frontend, current, refactor, ui]
area: frontend

confidence: 0.7
confidence_reason: "示例 context"
last_verified: 2026-06-04
verification_status: verified
verification_count: 0

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 60
status: active

source: session/frontend-redesign-20260604
---

# 当前 UI 重构项目

> 示例 context — 假设进行中的前端重构。

## 项目

把老的 jQuery + Bootstrap 后台改成 React + Tailwind。

## 进度

| 模块 | 状态 |
|------|------|
| 路由迁移到 React Router v6 | ✅ |
| 表单组件库（react-hook-form + zod）| ⏳ 60% |
| 数据层 TanStack Query 接入 | ⏳ 30% |
| Atomic Design 组件抽取 | 🔲 待开始 |
| WCAG AA 审计 | 🔲 待开始 |

## 已踩坑

- 老 jQuery 全局事件（`$(document).on`）跨页面污染 → React 严格清理 useEffect cleanup
- Bootstrap class 跟 Tailwind 冲突（v3 → v4 时 reset 不同）→ 隔离两套 stylesheet
- 老 API 返回非 JSON convention → 加 adapter layer

## Blockers

- 后端 API v2 还没上线，部分模块只能 mock 数据
- 设计稿 Figma 还在迭代，组件库 props 反复改

## 关联

- 组件架构：`domain/computing/frontend/foundations/component-architecture.md`
- 状态管理：`domain/computing/frontend/foundations/state-management.md`
- 性能：`domain/computing/frontend/foundations/performance-optimization.md`
- React 实践：`domain/computing/frontend/conventions/react-best-practices.md`
- 可访问性：`domain/computing/frontend/conventions/accessibility-rules.md`
