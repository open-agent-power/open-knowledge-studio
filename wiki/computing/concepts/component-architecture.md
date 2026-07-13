---
title: "组件架构（容器/展示/原子设计）"
type: foundation
tags: [frontend, react, component, architecture, atomic-design]
area: frontend

confidence: 0.9
confidence_reason: "React 社区标准 + Atomic Design 已落地"
last_verified: 2026-06-04
verification_status: verified
verification_count: 1

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 365
status: active

source: session/frontend-redesign-20260604
---

# 组件架构

## 1. 容器 vs 展示组件

| 维度 | 容器组件（Container）| 展示组件（Presentational）|
|------|---------------------|-------------------------|
| 关心 | 数据如何工作 | 视觉如何呈现 |
| 状态 | 有（useState / useReducer） | 无（仅 props）|
| 副作用 | 有（useEffect / 调 API）| 无 |
| 可测试性 | 集成测试 | 单元测试 + Storybook |
| 复用性 | 低（绑业务）| 高（跨页面）|

## 2. Atomic Design 5 层

```
Atom        → 最小元素（Button / Input / Label）
Molecule    → 简单组合（SearchBar = Input + Button）
Organism    → 复杂组合（NavBar = Logo + SearchBar + UserMenu）
Template    → 页面骨架（不含真数据）
Page        → 真实页面（Template + 真数据）
```

**目录组织建议**：
```
components/
├── atoms/
│   ├── Button/
│   │   ├── Button.tsx
│   │   ├── Button.test.tsx
│   │   ├── Button.stories.tsx
│   │   └── index.ts
│   └── ...
├── molecules/
├── organisms/
├── templates/
└── pages/
```

## 3. 组件 API 设计原则

### Props 设计

- ✅ **必填 props 放前面，可选放后面**（TS 强制）
- ✅ **布尔 props 默认 false**（避免 `disabled={false}` 累赘）
- ✅ **回调命名 `on<Event>`**（onClick / onChange）
- ❌ 不要传整个 object 当 prop（用具体字段）
- ❌ 不要 spread props（破坏 TS 类型推导 + 调试困难）

### 复合组件模式

```tsx
// ✅ 好：清晰、灵活
<Card>
  <Card.Header>Title</Card.Header>
  <Card.Body>...</Card.Body>
  <Card.Footer>...</Card.Footer>
</Card>

// ❌ 差：props 爆炸
<Card title="..." body="..." footer="..." showHeader hideFooter />
```

### Render Props / Hooks

- 状态逻辑复用 → custom hook（`useFormValidation`）
- UI 逻辑复用 → render props 或 children as function

## 4. 文件 size 上限

| 类型 | 上限 |
|------|------|
| 单组件 .tsx | ≤300 行 |
| 单 hook | ≤100 行 |
| 单 utility | ≤200 行 |

超过 → 拆。

## 反模式

- ❌ 上帝组件（一个文件 1000+ 行）
- ❌ Prop drilling >3 层（用 context 或状态提升）
- ❌ 容器组件直接渲染 HTML（应该委托给展示组件）
- ❌ 展示组件含业务逻辑（应该是 pure function）
- ❌ 命名 `Component1` / `Wrapper`（无信息）
