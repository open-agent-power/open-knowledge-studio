---
title: CI Triage — CI 红了先排除假阳性
tags:
- debugging
- ci
- triage
- strategy
area: computing
source: learnings/2026/06/20/20260620-multi-repo-pr-retrospective
type: strategy
status: active
importance: 0.7
confidence: 0.9015
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---





# CI Triage

## 招式

CI 红了不要慌。先分类是不是假阳性，再决定要不要修。

## CI 状态分类表

| 状态 | 含义 | 是真问题吗？ | 行动 |
|------|------|------------|------|
| `success` | 全绿 | — | 等 review |
| `pending` | 在跑 | — | 等 |
| `action_required` | 首次贡献者 | 否 | 等 maintainer 批准，**不要重提** |
| `failure` (Codecov) | Fork 无 token | 否 | 忽略，看 upstream CI |
| `failure` (spotless/gofmt/prettier) | 格式 | 是 | 跑 formatter 重推 |
| `failure` (test) | 测试挂了 | 是 | 读错误，修代码 |
| `failure` (license-check) | 缺 ALv2 header | 是 | 加 header |
| `failure` (PR body format) | CI 解析 PR body 失败 | 是 | 读 CI 脚本，改 body 格式 |

## 排除顺序

```
1. 是 Fork CI 还是 upstream CI？→ 只看 upstream
2. 是 Codecov 上传失败吗？→ 忽略
3. 是 action_required 吗？→ 等，不重提
4. 是格式/lint 吗？→ 跑 formatter
5. 是真的 test failure 吗？→ 读第一个 error，修代码
```

## Fork CI vs Upstream CI

```bash
# 只看 upstream CI（最准确）
gh pr checks <PR_NUMBER> --repo OWNER/REPO

# Fork CI 通常红（Codecov token 缺失），不用管
```

## 实战案例

| PR | CI 状态 | 误判 | 正确做法 |
|----|---------|------|---------|
| agentscope-java #1387 | Codecov red | 以为是代码问题 | Fork 无 token，忽略 |
| rocketmq #10531 | `action_required` | 想重提 | 首次贡献者正常，等批准 |
| openclaw #94987 | PR body format | 以为是格式问题 | 读 CI 脚本发现要 `**Field**: value` 不是 `### Field` |

## 反模式

- CI 一红就 `git push --force` → 通常不是代码问题
- `action_required` 就关 PR 重提 → 新 PR 还是 `action_required`
- Fork CI 红就修代码 → 99% 是 Codecov token

## 关联

- Smoke First：`smoke-first.md`
- Fixes INDEX：`plugins/autpilot-coding/skills/fixes/INDEX.md`
