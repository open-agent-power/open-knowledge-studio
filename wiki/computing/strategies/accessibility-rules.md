---
title: "可访问性强约束（WCAG AA）"
type: convention
tags: [frontend, accessibility, a11y, wcag]
area: frontend

confidence: 0.85
confidence_reason: "WCAG 2.1 AA 标准 + axe lint 强制"
last_verified: 2026-06-04
verification_status: verified
verification_count: 0

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 180
status: active

source: session/frontend-redesign-20260604
---

# 可访问性强约束（WCAG AA）

## 必做（lint 强制）

### 语义化 HTML

- ✅ `<button>` 不要 `<div onClick>`（键盘可达 + 屏幕阅读器友好）
- ✅ `<a href>` 不要 `<div>` 当链接
- ✅ heading 层级正确（h1 → h2 → h3，不跳级）
- ✅ landmark（`<header>` / `<nav>` / `<main>` / `<footer>` / `<aside>`）

### Alt text

- ✅ `<img alt="...">` 必填（装饰图用 `alt=""` 显式跳过）
- ❌ `<img alt="image">`（无信息）
- ❌ `<img alt="点击查看">`（错位描述）

### ARIA 属性

- ✅ 表单 `<label htmlFor="...">` 关联 `<input id="...">`
- ✅ icon button 加 `aria-label`
- ✅ 动态内容用 `aria-live="polite"` 或 `aria-busy`
- ❌ `role="button"` on div（应该用真 `<button>`）

### 颜色对比

| 文本类型 | 对比度 |
|---------|--------|
| 正文（<18px）| ≥4.5:1 |
| 大文本（≥18px / bold ≥14px）| ≥3:1 |
| 非文本（图标 / 边框）| ≥3:1 |

工具：[WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)

### 键盘可达

- ✅ Tab 顺序合理
- ✅ Focus indicator 明显（不要 `outline: none` 除非提供替代）
- ✅ Escape 关闭 modal / dropdown
- ✅ Enter / Space 触发 button / link

## 必不做

- ❌ 用颜色单独表意（色盲不可用 → 加 icon / 形状辅助）
- ❌ autoplay 视频带声音
- ❌ Modal 不 trap focus
- ❌ 表单错误只在 placeholder 提示（用 aria-describedby）
- ❌ 时间限制（如倒计时验证码 60s）无暂停 / 延长选项

## 测试工具

```bash
# CI lint
npm i -D eslint-plugin-jsx-a11y axe-core

# 自动化测试
npm i -D @axe-core/playwright

# 手测
- 拔 mouse，全程键盘操作能完成所有任务
- 开 VoiceOver (mac) / NVDA (win)，听一遍页面
- Chrome DevTools Lighthouse a11y score >90
```
