---
title: "数据库设计（schema / migration / index）"
type: foundation
tags: [backend, database, schema, migration, index, postgres]
area: backend

confidence: 0.9
confidence_reason: "Postgres 实战 + migrations 反模式"
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
- 金额用 `numeric(18,4)` 不 `float`

### 必含字段（每个业务表）

```sql
CREATE TABLE <name> (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  -- 业务字段...
);
```

### 软删除

- 加 `deleted_at timestamptz NULL` 而不真 DELETE
- 所有 query 默认加 `WHERE deleted_at IS NULL`
- 用 view 包装常用查询

## Migration 强约束

### 必须可回滚

每个 migration 必有 `up` + `down`：

```python
def up():
    op.add_column('users', sa.Column('phone', sa.String(11)))

def down():
    op.drop_column('users', 'phone')
```

### 两阶段 DROP（铁律）

不允许一步 `DROP COLUMN`。两阶段：

**阶段 1**（本 release）：
- 改代码停止读写该字段
- migration 把字段 rename 为 `<name>_deprecated_YYYYMM`
- 部署观察 1-2 周

**阶段 2**（下个 release）：
- migration 真 DROP

### 大表 ALTER

>100 万行的表：
- ❌ `ALTER TABLE ... ADD COLUMN` (会锁表)
- ✅ 用 `pt-online-schema-change`（MySQL）或 GH-ost
- ✅ Postgres: `ALTER TABLE ... ADD COLUMN ... CONCURRENTLY` 或分批

### 加索引

- ✅ `CREATE INDEX CONCURRENTLY`（Postgres）—— 不锁表
- ✅ MySQL: `ALTER TABLE ... ADD INDEX ... ALGORITHM=INPLACE LOCK=NONE`
- ❌ 普通 CREATE INDEX 在大表（锁表 → 业务停摆）

## Index 设计原则

- WHERE / JOIN / ORDER BY 涉及的列考虑加索引
- 组合索引顺序：选择性高的在前
- 不超过 5 个索引 / 表（写入慢）
- 用 `EXPLAIN ANALYZE` 验证索引被命中

## 反模式

- ❌ `SELECT *`（schema 改了字段顺序就崩）
- ❌ N+1 query（用 join 或 prefetch）
- ❌ 在 DB 存大文件（用 S3 + DB 存 URL）
- ❌ migration 含业务 logic（schema + data 应分离）
- ❌ production 跑 `migration --fake`（绕过执行）
