---
title: "日志规范（结构化 / level / context）"
type: convention
tags: [backend, logging, structured, observability]
area: backend

confidence: 0.85
confidence_reason: "12-factor + OpenTelemetry 实战"
last_verified: 2026-06-04
verification_status: verified
verification_count: 0

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 180
status: active

source: session/backend-api-20260604
---

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
    "type": "InsufficientBalanceError",
    "stack": "..."
  },
  "context": {
    "amount": 100,
    "balance": 50
  }
}
```

**必含字段**：
- `ts` (ISO 8601 + UTC)
- `level`
- `message`
- `request_id` (跨服务追踪)
- 业务关键字段（user_id / order_id 等）

## Log Level 用法

| Level | 何时用 | 例子 |
|-------|--------|------|
| **TRACE** | 极详细 debug | 函数入参 / 中间状态 |
| **DEBUG** | 开发调试 | "Cache hit for key X" |
| **INFO** | 重要业务事件 | "User signed up" / "Order paid" |
| **WARN** | 业务异常但可恢复 | "Retry attempt 2/3" / "Invalid input" |
| **ERROR** | 业务失败 | "Payment failed" + stack |
| **FATAL** | 服务不可用 | "DB connection lost" + alert |

production 默认 **INFO** 起步。

## Context 传播

用 thread local / async context 自动注入 request_id 等：

```python
# Python with structlog + context vars
import structlog
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar('request_id')

def add_request_id(logger, method_name, event_dict):
    rid = request_id_var.get(None)
    if rid:
        event_dict['request_id'] = rid
    return event_dict

structlog.configure(processors=[add_request_id, ...])
```

## 敏感字段必脱敏

- ✅ 手机号: `138****8888`
- ✅ 身份证: `310101********1234`
- ✅ 银行卡: `**** **** **** 1234`
- ❌ 密码 / token / API key 永远不进日志

## 日志保留策略

| Level | 保留 |
|-------|------|
| TRACE/DEBUG | 本地，不入持久化 |
| INFO | 7-30 天 |
| WARN/ERROR | 90 天 |
| FATAL | 1 年（合规需要更久）|

## 反模式

- ❌ `print(...)` 当日志（无 level / 无 timestamp）
- ❌ 字符串拼接 `f"User {user_id} failed"`（不可结构化 query）
- ❌ 日志含敏感字段（合规事故）
- ❌ 日志同步 IO 阻塞业务（用 async logger）
- ❌ DEBUG 上 production（disk 撑爆）
