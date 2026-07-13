---
title: PR 审核流程与 checklist
tags:
- pr
- review
- protocol
- _shared
area: _shared
source: profiles/team.md
last_verified: 2026-06-04
type: concept
status: active
importance: 0.7
confidence: 0.85
created: 2026-06-04
pinned: false
archived: false
access_count: 0
---

# PR 审核流程与 checklist

## 必备条件

| 维度 | 要求 |
|------|------|
| 标题 | conventional commit 格式 |
| 描述 | summary / what / why / 测试计划 |
| CI | 全绿 |
| Reviewer | ≥1，跨模块改动 ≥2 |
| 核心模块 review | payment / risk 必经 Bob |
| 测试 | 业务覆盖 ≥80%，工具 ≥60% |

## Reviewer Checklist

```markdown
- [ ] 代码可读（命名、注释、复杂度）
- [ ] 测试充分（含边界值）
- [ ] 没引入 secrets / debug print / TODO
- [ ] 文档同步更新（README / API / INDEX.md）
- [ ] PII 字段标 classification
- [ ] 数据库 migration 有 down
- [ ] 性能影响评估（DB query / API latency）
- [ ] 安全影响评估（auth / authz / input validation）
- [ ] 兼容性（API 向后兼容 / 灰度策略）
- [ ] 回滚预案（feature flag / rollback SQL）
```

## SLA

- review 响应：48h 内
- 超时：自动 @ 备份 reviewer
- 紧急修复：1h 内（on-call）

## 评论分类

| Prefix | 含义 | 必须解决吗 |
|--------|------|----------|
| `nit:` | 鸡毛蒜皮 | 否，作者自决 |
| `q:` | 问题 | 是，回答即可 |
| `should:` | 应该改 | 是 |
| `blocker:` | 必须改 | 是，不改不 merge |

## 反模式

- ❌ "LGTM" 不看代码（只看 CI）
- ❌ 自己 approve 自己的 PR
- ❌ rebase 后不重新通知 reviewer
- ❌ 紧急情况绕过 review（必须留 audit）
