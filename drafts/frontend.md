---
title: Frontend Proposal
draft_type: convention
draft_area: frontend
source_pages:
- accessibility-rules
- react-best-practices
- state-management
- performance-optimization
- component-architecture
drafted_at: '2026-07-11'
status: draft
---

# Frontend — Wiki Proposal

> Drafted from 5 wiki pages. Sources: accessibility-rules, react-best-practices, state-management, performance-optimization, component-architecture.

Proposed type: `convention` | Area: `frontend`

## 可访问性强约束（WCAG AA）
# 可访问性强约束（WCAG AA）

## 必做（lint 强制）

### 语义化 HTML

- ✅ `<button>` 不要 `<div onClick>`（键盘可达 + 屏幕阅读器友好）
- ✅ `<a href>` 不要 `<div>` 当链接
- ✅ heading 层级正确（h1 → h2 → h3，不跳级）
- ✅ landmark（`<header>` / `<nav>` / `<main>` / `<footer>` / `<aside>`）

### Alt text

- ✅ `<img alt="...">` 必填（装饰图用 `alt=""` 显式跳过）
- ❌ 

## React 最佳实践
# React 最佳实践

## Hooks 强约束

1. **只在顶层调** — 不在循环 / 条件 / 嵌套函数里调
2. **只在 React 函数调** — 不在普通 JS 函数调
3. **依赖数组必填准** — `useEffect(fn, [a, b])` 漏依赖会导致 stale closure

```bash
# 装这个 lint，强制 hooks 规则
npm i -D eslint-plugin-react-hooks
```

## key 强约束

- ✅ `key={item.id}` — 稳定 ID
- ❌ `key={index}` — 列表顺序变就崩
- 

## 状态管理（local/lift/global/server）
# 状态管理决策树

## 4 类状态（按"谁需要"分类）

| 状态类型 | 例子 | 工具 |
|---------|------|------|
| **Local** | 组件内开关、输入框 | `useState` |
| **Lifted** | 表单跨组件 | 状态提升到共同父 + props |
| **Global** | 主题、用户登录态、权限 | `Context` / `Zustand` / `Redux Toolkit` |
| **Server** | API 数据、缓存 | `TanStack Query` / `SWR` / `RTK Query` |

## 

## 前端性能优化
# 前端性能优化

## Core Web Vitals 目标（Google 标准）

| 指标 | 含义 | 目标 |
|------|------|------|
| **LCP** (Largest Contentful Paint) | 最大内容绘制 | ≤2.5s |
| **FID / INP** (First Input Delay / Interaction to Next Paint) | 交互响应 | ≤200ms |
| **CLS** (Cumulative Layout Shift) | 累计布局偏移 | ≤0.1 |

## 4 类优化（按 ROI 排序）

###

## 组件架构（容器/展示/原子设计）
# 组件架构

## 1. 容器 vs 展示组件

| 维度 | 容器组件（Container）| 展示组件（Presentational）|
|------|---------------------|-------------------------|
| 关心 | 数据如何工作 | 视觉如何呈现 |
| 状态 | 有（useState / useReducer） | 无（仅 props）|
| 副作用 | 有（useEffect / 调 API）| 无 |
| 可测试性 | 集成测试 | 单元测试 + Storybook |
| 复用性 | 低（绑业务）| 高（跨页面）|

## 2. 


---
Review and merge into wiki/ if valuable, or discard.