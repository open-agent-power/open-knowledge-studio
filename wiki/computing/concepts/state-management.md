---
title: "状态管理（local/lift/global/server）"
type: foundation
tags: [frontend, state, react, redux, zustand, tanstack-query]
area: frontend

confidence: 0.85
confidence_reason: "React 团队官方推荐 + 主流社区实践"
last_verified: 2026-06-04
verification_status: verified
verification_count: 0

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 365
status: active

source: session/frontend-redesign-20260604
---

# 状态管理决策树

## 4 类状态（按"谁需要"分类）

| 状态类型 | 例子 | 工具 |
|---------|------|------|
| **Local** | 组件内开关、输入框 | `useState` |
| **Lifted** | 表单跨组件 | 状态提升到共同父 + props |
| **Global** | 主题、用户登录态、权限 | `Context` / `Zustand` / `Redux Toolkit` |
| **Server** | API 数据、缓存 | `TanStack Query` / `SWR` / `RTK Query` |

## 决策树

```
该状态只有 1 个组件用？
  ├─ 是 → useState
  └─ 否 → 2-3 个父子组件？
            ├─ 是 → 状态提升（lift）
            └─ 否 → 跨页面？
                      ├─ 是，源自服务端 → TanStack Query
                      └─ 是，纯客户端 → Zustand 或 Context
```

## 何时用 Context

- **静态全局值**（主题色 / 国际化 locale / current user）
- ❌ **频繁变化的**（用 Zustand，否则全组件重渲染）

## 何时用 Zustand vs Redux

| 维度 | Zustand | Redux Toolkit |
|------|---------|--------------|
| 学习曲线 | 低 | 中 |
| 样板代码 | 极少 | 多（createSlice 等）|
| Time-travel debug | 弱 | 强 |
| 适合规模 | 中小（<50 reducer） | 大（>50 reducer + 多团队）|

**MVP / 单团队 → Zustand。大型企业 / 时间旅行 debug 需求 → Redux Toolkit。**

## TanStack Query 必备字段

```tsx
const { data, error, isLoading, refetch } = useQuery({
  queryKey: ['users', userId],
  queryFn: () => fetchUser(userId),
  staleTime: 5 * 60 * 1000,        // 5 min 内不重新 fetch
  cacheTime: 10 * 60 * 1000,       // 10 min 后从 cache 移除
  refetchOnWindowFocus: false,     // 默认 true 经常坑
  retry: 3,
})
```

## 反模式

- ❌ 全局 Redux 存表单输入（频繁 dispatch 性能差）
- ❌ Context 存 API 数据（重新发明 TanStack Query）
- ❌ 多个 useState 关联状态（用 useReducer）
- ❌ `prop drilling` 超过 3 层不抽 context
- ❌ 服务端数据手动 fetch + setState（不 cache / 不 refetch / 不防抖）
