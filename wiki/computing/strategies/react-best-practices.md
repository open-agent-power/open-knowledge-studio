---
title: "React 最佳实践"
type: convention
tags: [frontend, react, best-practices, hooks]
area: frontend

confidence: 0.9
confidence_reason: "React 团队官方文档 + 主流 lint rules"
last_verified: 2026-06-04
verification_status: verified
verification_count: 1

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 180
status: active

source: session/frontend-redesign-20260604
---

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
- ❌ `key={Math.random()}` — 每次重渲染都重建

## 受控 vs 非受控

- 受控组件：`<input value={x} onChange={...}>` — 默认推荐
- 非受控组件：`<input defaultValue={x} ref={r}>` — 极少用（不可控的复杂场景）

## 副作用

```tsx
// ✅ 好：依赖明确 + cleanup
useEffect(() => {
  const sub = api.subscribe(handler);
  return () => sub.unsubscribe();  // cleanup
}, [userId]);

// ❌ 差：依赖漏 / 无 cleanup / 副作用在 render
useEffect(() => {
  api.subscribe(handler);  // 永远不会 unsubscribe
}, []);
```

## 错误边界

每个独立路由 / 大组件用 ErrorBoundary 包：

```tsx
<ErrorBoundary fallback={<ErrorPage />}>
  <Route ... />
</ErrorBoundary>
```

## Suspense + concurrent features (React 18+)

- 数据请求用 `<Suspense fallback={...}>` 包
- 配合 TanStack Query 的 `suspense: true`
- 不要混用 `isLoading` 和 `<Suspense>`

## TypeScript 强约束

- ✅ Props 接口必填，禁止 `any`
- ✅ 用 `as const` 锁定字面量类型
- ✅ 善用 utility types（`Pick` / `Omit` / `Partial`）
- ❌ 不写 `// @ts-ignore`（要不就 `// @ts-expect-error` + 注释为什么）

## 反模式（lint 应该捕获）

- ❌ `<div onClick>` 不带 keyboard accessibility
- ❌ `<button type="button">` 漏 type（form 内默认 submit 会刷新页面）
- ❌ `dangerouslySetInnerHTML` 不消毒
- ❌ inline function 在 hot path（每次 render 新引用）
- ❌ console.log 提交（用 ESLint no-console rule）
