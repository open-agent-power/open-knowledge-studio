---
title: "当前微服务拆分项目"
type: context
tags: [backend, current, microservice, migration]
area: backend

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

source: session/backend-api-20260604
---

# 当前微服务拆分项目

> 示例 context — 假设进行中的后端拆分。

## 项目

把 monolith 拆成 3 个微服务：user / payment / notification。

## 进度

| 阶段 | 状态 |
|------|------|
| 边界识别 (Domain-Driven Design)  | ✅ 完成 |
| user-service 抽出 + API 改 | ⏳ 60% |
| payment-service 抽出 | 🔲 待开始 |
| notification-service 抽出 | 🔲 待开始 |
| API gateway (Kong / Apisix) | 🔲 待选型 |
| 分布式追踪 (OpenTelemetry) | ⏳ POC |

## 已踩坑

- 跨服务事务用 saga 模式（之前想用 2PC 被 PR review 打回）
- 用户表跨服务引用 → user-service 提供 `/users/{id}/summary` 给其他服务
- 缓存一致性 → 用 cache invalidation + TTL 双保险

## 关联

- API 设计：`domain/computing/backend/foundations/api-design.md`
- 并发模式（saga / 限流）：`domain/computing/backend/foundations/concurrency-patterns.md`
- 数据库（跨服务 schema）：`domain/computing/backend/foundations/database-design.md`
- 错误处理：`domain/computing/backend/conventions/error-handling.md`
- 日志（分布式追踪）：`domain/computing/backend/conventions/logging-standards.md`
