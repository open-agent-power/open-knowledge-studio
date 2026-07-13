---
title: Git 分支命名规范
tags:
- git
- branch
- naming
- _shared
area: _shared
source: profiles/team.md
last_verified: 2026-06-04
type: concept
status: active
importance: 0.7
confidence: 0.9
created: 2026-06-04
pinned: false
archived: false
access_count: 0
---

# Git 分支命名规范

## 格式

```
<type>/<area>-<slug>
```

| 字段 | 内容 |
|------|------|
| type | feat / fix / refactor / chore / docs / test / distill |
| area | payment / growth / marketing / merchant / risk / shared / infra |
| slug | kebab-case 简短描述，≤30 字符 |

## 例子

| ✅ 正确 | ❌ 错误 |
|--------|--------|
| `feat/payment-stripe-connect` | `feat-payment` |
| `fix/risk-rate-limit-bug` | `bobwang/fixing-bug` |
| `distill/auto-q3-planning` | `distill-pr-2` |
| `chore/infra-bump-fastapi` | `bump` |

## 禁止

- ❌ 中文 / 空格 / 大写
- ❌ 个人前缀（`bobwang/`）— 用 `feat/` 等类型前缀
- ❌ 编号（`fix/issue-123`）— 用语义描述
- ❌ 过长（>60 字符）

## 删除策略

- merged 分支：merge 后立刻删除（GitHub auto-delete on merge 开启）
- stale 分支：30 天无 commit → 自动 archive 到 `_archive/<name>-<sha>`

## 关联

- PR 标题用 conventional commit：`<type>(<area>): <subject>`
- Commit 同上
