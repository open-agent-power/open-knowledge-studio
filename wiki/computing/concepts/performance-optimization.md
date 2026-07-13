---
title: "前端性能优化"
type: foundation
tags: [frontend, performance, lazy, memo, virtual, bundle]
area: frontend

confidence: 0.85
confidence_reason: "Web Vitals 标准 + Lighthouse 实测"
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

# 前端性能优化

## Core Web Vitals 目标（Google 标准）

| 指标 | 含义 | 目标 |
|------|------|------|
| **LCP** (Largest Contentful Paint) | 最大内容绘制 | ≤2.5s |
| **FID / INP** (First Input Delay / Interaction to Next Paint) | 交互响应 | ≤200ms |
| **CLS** (Cumulative Layout Shift) | 累计布局偏移 | ≤0.1 |

## 4 类优化（按 ROI 排序）

### 1. Bundle 优化（最高 ROI）

| 技术 | 效果 |
|------|------|
| Code splitting (`React.lazy` / `dynamic import`) | 首屏 -50% |
| Tree shaking（用 ESM）| 包大小 -20-40% |
| Dependency 分析（`vite-bundle-visualizer`）| 找肿大依赖 |
| 替换重依赖（lodash → lodash-es 按需 / dayjs 替代 moment）| 个别情况 -100KB |

### 2. 渲染优化（中 ROI）

| 技术 | 何时用 |
|------|--------|
| `React.memo` | 重 props 浅比较有效的组件 |
| `useMemo` | 重计算 derive 值 |
| `useCallback` | 传给 memo 组件的回调 |
| 虚拟滚动（react-window / TanStack Virtual）| 列表 >100 项 |

**反模式**: 到处用 memo / useMemo / useCallback —— 浅比较本身有成本。**先测再优化**。

### 3. 加载优化

| 技术 | 效果 |
|------|------|
| 图片 lazy load (`loading="lazy"`) | 首屏快 |
| Preload critical CSS | LCP 提升 |
| Service Worker cache | 二次访问极快 |
| HTTP/2 + Brotli | 传输小 30% |

### 4. 资源优化

| 资源 | 优化 |
|------|------|
| 图片 | WebP / AVIF / 响应式 srcset |
| 字体 | woff2 + `font-display: swap` |
| 视频 | poster + 按需加载 |
| Icon | SVG sprite 或 inline |

## 测量工具

```bash
# 本地
npx lighthouse https://your-site --view

# CI
npx @lhci/cli@latest autorun

# 生产监控
Real User Monitoring (RUM) - Sentry / Datadog
```

## 反模式

- ❌ 没测就优化（profile-driven, not guess-driven）
- ❌ 滥用 memo（浅比较失败 + 性能反退）
- ❌ 一次性 import 整个 lodash（应按需）
- ❌ 大图片不压缩（视觉看不出但 LCP 翻倍）
- ❌ 大列表不虚拟滚动（>500 项必崩）
