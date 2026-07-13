---
title: "API 设计原则（REST / 幂等 / 版本）"
type: foundation
tags: [backend, api, rest, idempotency, versioning]
area: backend

confidence: 0.9
confidence_reason: "REST 业界标准 + 实战幂等踩坑"
last_verified: 2026-06-04
verification_status: verified
verification_count: 1

created: 2026-06-04
last_accessed: 2026-06-04
access_count: 0
recent_accesses: []
ttl_days: 365
status: active

source: session/backend-api-20260604
---

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
```

- ✅ 复数名词（`/users`）
- ❌ 动词（`/getUsers` / `/createUser`）— 用 HTTP 方法表达
- ❌ 嵌套 >2 层（`/users/{id}/orders/{oid}/items` 太深）

## 2. HTTP 状态码

| Code | 含义 | 例子 |
|------|------|------|
| 200 | OK | GET 成功 |
| 201 | Created | POST 创建成功（带 Location header）|
| 204 | No Content | DELETE 成功 / PUT 无返回 |
| 400 | Bad Request | 参数错误 |
| 401 | Unauthorized | 未登录 |
| 403 | Forbidden | 登录了但无权限 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 状态冲突（如重复创建）|
| 422 | Unprocessable Entity | 业务规则不通过 |
| 429 | Too Many Requests | 限流 |
| 500 | Internal Server Error | 服务器 bug |
| 503 | Service Unavailable | 临时不可用 |

## 3. 幂等性（铁律）

| 方法 | 幂等 | 说明 |
|------|------|------|
| GET | ✅ | 多次调结果相同 |
| PUT | ✅ | 全量替换，多次=一次 |
| DELETE | ✅ | 多次=一次（第二次 404 也算成功）|
| PATCH | ⚠️ | 取决于实现（建议幂等）|
| POST | ❌ | 默认不幂等，需要客户端传 `Idempotency-Key` 实现 |

### Idempotency-Key 模式

```http
POST /payments
Headers:
  Idempotency-Key: <client-generated-uuid>

→ 服务端：
  1. 查 idempotency 表，若 key 存在 → 返回历史响应
  2. 否则正常处理 + 存 key + response
```

## 4. 版本控制

| 策略 | 例子 | 用途 |
|------|------|------|
| URL 路径 | `/v1/users` `/v2/users` | 主版本 breaking change |
| Header | `Accept: application/vnd.api+json;version=2` | 灵活但难发现 |
| Query | `/users?api_version=2` | 不推荐（cache 不友好）|

**推荐 URL 路径方式**（简单 + 文档友好）。

## 5. 错误响应统一格式

```json
{
  "error": {
    "code": "INVALID_PHONE_FORMAT",
    "message": "Phone number must be 11 digits",
    "field": "phone",
    "request_id": "req-abc-123"
  }
}
```

必含 `code`（程序可读）+ `message`（人可读）+ `request_id`（debug）。

## 反模式

- ❌ 200 OK 但 body 含 `{"success": false}`（破坏 HTTP 语义）
- ❌ DELETE 返回大对象（用 204）
- ❌ 列表接口不分页（崩了 DB）
- ❌ 版本只有 1 个（不可演化）
- ❌ 错误 message 暴露内部细节（"Could not connect to db at 10.x.x.x"）
