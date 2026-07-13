---
title: "错误处理规范（边界 catch / 不要内部 try）"
type: convention
tags: [backend, error, exception, boundary]
area: backend

confidence: 0.9
confidence_reason: "经典 fail-fast 原则 + 实战防御性编程反例"
last_verified: 2026-06-04
verification_status: verified
verification_count: 1

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 180
status: active

source: session/backend-api-20260604
---

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
| 外部 process | subprocess / shell | ✅ |

### 内部代码（service / repo / util）

- ✅ Let it crash（异常自然向上传播）
- ✅ 用类型系统避免（Optional / Result）
- ❌ 防御性 try/catch 包一切
- ❌ catch 后吞掉异常 + log + return None

## Why

```python
# ❌ 反模式：每层都 try/catch，错误根因被隐藏
def get_user(id):
    try:
        return db.query(...)
    except Exception as e:
        log.error(e)
        return None

def update_user(id, data):
    try:
        user = get_user(id)
        if user is None:
            return None  # 不知道是不存在还是 db 错
        ...
    except Exception:
        return None

# ✅ 好：只在边界 catch
def get_user(id):
    return db.query(...)  # 让异常飞

def update_user(id, data):
    user = get_user(id)  # 异常自然传
    ...

# 边界（HTTP handler）
@app.put("/users/{id}")
def handle(id, data):
    try:
        update_user(id, data)
        return {"ok": True}
    except DBNotFoundError as e:
        raise HTTPException(404, str(e))
    except DBConnectionError as e:
        raise HTTPException(503, "DB unavailable")
    except Exception as e:
        sentry.capture(e)
        raise HTTPException(500, "Internal error")
```

## 异常分类（自定义）

```python
class BusinessError(Exception): pass        # 业务规则不通过（HTTP 422）
class NotFoundError(BusinessError): pass    # 资源不存在（HTTP 404）
class ConflictError(BusinessError): pass    # 状态冲突（HTTP 409）
class AuthError(Exception): pass            # 鉴权失败（HTTP 401/403）
class RateLimitError(Exception): pass       # 限流（HTTP 429）

class SystemError(Exception): pass          # 系统错（HTTP 500）
class ExternalError(SystemError): pass      # 外部依赖失败（HTTP 503）
```

边界 handler 按 类型映射 HTTP code。

## 日志原则

- ✅ 错误日志含 stack trace + request_id + user_id
- ✅ 业务异常 log level = WARN
- ✅ 系统异常 log level = ERROR + Sentry alert
- ❌ catch 后只 `log.error(e)` 不带 stack
- ❌ swallow 异常不 log（黑洞）

## 反模式

- ❌ `except: pass`（绝对禁止）
- ❌ `except Exception:`（catch 所有，掩盖 KeyboardInterrupt 等）
- ❌ raise 新异常时不带原异常（`raise NewError(...) from e`）
- ❌ 在 finally 抛新异常（覆盖原异常）
- ❌ 用异常控制流程（"if not found, raise NotFound" 用来当 return）
