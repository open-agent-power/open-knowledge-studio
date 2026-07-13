---
title: Backend Proposal
draft_type: convention
draft_area: backend
source_pages:
- logging-standards
- error-handling
- api-design
- concurrency-patterns
- database-design
drafted_at: '2026-07-11'
status: draft
---

# Backend — Wiki Proposal

> Drafted from 5 wiki pages. Sources: logging-standards, error-handling, api-design, concurrency-patterns, database-design.

Proposed type: `convention` | Area: `backend`

## 日志规范（结构化 / level / context）
# 日志规范

## 结构化日志（JSON）

```json
{
  "ts": "2026-06-04T11:00:00.123Z",
  "level": "ERROR",
  "logger": "payment.refund",
  "message": "Refund failed: insufficient balance",
  "request_id": "req-abc-123",
  "user_id": "uuid-456",
  "trace_id": "ot-789",
  "error": {
    "type": "InsufficientBalanceErr

## 错误处理规范（边界 catch / 不要内部 try）
# 错误处理规范

## 核心原则

**只在系统边界 catch，内部 let it crash**。

### 系统边界

| 边界 | 例子 | 必 catch |
|------|------|---------|
| HTTP handler | controller / route | ✅ |
| 消息消费 | Kafka / Redis subscriber | ✅ |
| 定时任务 | cron / scheduler entry | ✅ |
| 第三方 SDK 调用 | Stripe SDK / Lark SDK | ✅ |
| 外部 process | subprocess

## API 设计原则（REST / 幂等 / 版本）
# API 设计原则

## 1. RESTful 资源命名

```
GET    /users              列表
GET    /users/{id}         单个
POST   /users              创建
PUT    /users/{id}         全量更新
PATCH  /users/{id}         部分更新
DELETE /users/{id}         删除

# 子资源
GET    /users/{id}/orders  这个用户的订单
POST   /users/{id}/orders  给这个用户创建订单
`

## 并发模式（锁 / 乐观锁 / 队列 / 限流）
# 并发模式

## 4 类并发问题 + 解决方案

### 1. 写写冲突（同时改一条记录）

| 方案 | 适合 | 实现 |
|------|------|------|
| **悲观锁** | 冲突频繁 | `SELECT ... FOR UPDATE` |
| **乐观锁** | 冲突少 | 加 `version` 列，`UPDATE WHERE version=?` |
| **CAS / atomic** | 简单数值 | `UPDATE balance = balance - 100 WHERE balance >= 100` |

### 2. 重复请求（用户双击 / 网络重

## 数据库设计（schema / migration / index）
# 数据库设计

## Schema 设计原则

### 主键

- ✅ UUID v4（默认）或 v7（时间排序）
- ✅ 内部 join 表用 bigint surrogate（性能）
- ❌ 业务字段当主键（email / phone — 易冲突 + PII）

### 列命名

- snake_case：`user_id` 不 `userId`
- 布尔加 `is_` / `has_` 前缀：`is_active` / `has_paid`
- 时间戳 `_at` 后缀：`created_at` / `updated_at`
- 金额用 `numeric(18,4)` 不 `float


---
Review and merge into wiki/ if valuable, or discard.