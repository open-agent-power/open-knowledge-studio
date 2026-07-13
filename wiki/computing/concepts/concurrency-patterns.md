---
title: "并发模式（锁 / 乐观锁 / 队列 / 限流）"
type: foundation
tags: [backend, concurrency, lock, queue, rate-limit]
area: backend

confidence: 0.85
confidence_reason: "实战 + 经典分布式系统设计"
last_verified: 2026-06-04
verification_status: verified
verification_count: 0

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 365
status: active

source: session/backend-api-20260604
---

# 并发模式

## 4 类并发问题 + 解决方案

### 1. 写写冲突（同时改一条记录）

| 方案 | 适合 | 实现 |
|------|------|------|
| **悲观锁** | 冲突频繁 | `SELECT ... FOR UPDATE` |
| **乐观锁** | 冲突少 | 加 `version` 列，`UPDATE WHERE version=?` |
| **CAS / atomic** | 简单数值 | `UPDATE balance = balance - 100 WHERE balance >= 100` |

### 2. 重复请求（用户双击 / 网络重试）

- **HTTP**: Idempotency-Key（见 `api-design.md`）
- **Job**: 任务 ID + 去重 set（Redis SET NX）
- **消息**: 消费者幂等（at-least-once + 业务幂等）

### 3. 雪崩 / 限流

| 算法 | 适合 |
|------|------|
| **令牌桶** (Token Bucket) | 允许突发 |
| **漏桶** (Leaky Bucket) | 强制均匀 |
| **滑动窗口** (Sliding Window) | 精确控制 |
| **固定窗口** | 不推荐（边界突刺）|

**实现**: Redis + Lua 脚本

```lua
-- sliding window with Redis ZSET
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, window / 1000)
    return 1
end
return 0
```

### 4. 异步 / 后台任务

| 队列 | 适合 |
|------|------|
| Redis Streams / Pub/Sub | 轻量 + 低延迟 |
| Kafka | 高吞吐 + 持久化 + 重放 |
| RabbitMQ | 灵活路由 |
| Celery (Python) / Sidekiq (Ruby) | 框架级 |

**铁律**: 任务必须**幂等** + **可重试** + **死信队列**（DLQ）。

## 分布式事务（saga 模式）

跨服务事务不要用 2PC（性能差）。用 **Saga**：

```
1. 调 service A 创建订单 → 失败 ABORT
2. 调 service B 扣库存   → 失败 → call A.cancel (补偿)
3. 调 service C 扣支付   → 失败 → call B.cancel + A.cancel
```

每个 step 有 **forward** + **compensation** 两个 op。

## 反模式

- ❌ 用 lock 解决幂等（应用层 lock 不可靠）
- ❌ 重试不带 exponential backoff（拖垮下游）
- ❌ 队列消费者不幂等（消息重复 → 数据脏）
- ❌ 跨服务用 transaction（用 saga）
- ❌ 限流不区分用户 / API（被恶意用户拖垮所有用户）
