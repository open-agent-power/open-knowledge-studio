---
title: "Frontmatter 字段规范 (v0.7)"
version: v0.7
updated: 2026-06-04
---

# Frontmatter 字段规范（v0.7）

> 知识库所有 `.md` 文件的 frontmatter 字段定义 + 各类文件需要哪些字段。

---

## 1. 字段定义（按用途分组）

> 命名约定：snake_case。日期 `YYYY-MM-DD`，时间戳 ISO8601。

### 组 IDENTITY ─ 人识别这是什么文件

| 字段 | 类型 | 含义 |
|------|------|------|
| `title` | string | 人读标题，< 50 字符 |
| `type` | enum | `foundation` / `convention` / `context` / `profile` / `intent-spec` |
| `tags` | string[] | find 关键词匹配，3-5 个 |

### 组 TRUST ─ 信任度（供 apply-decay 使用）

| 字段 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `confidence` | float [0-1] | 见 §3 | 信任度 |
| `confidence_reason` | string | — | confidence 的依据 |
| `last_verified` | date | created | 上次人工校验日期 |
| `verification_status` | enum | `unverified` | `unverified` / `verified` / `outdated` / `disputed` |
| `verification_count` | int | 0 | 人工校验次数 |
| `last_verification_by` | string | `""` | 上次校验者（github username）|
| `last_confidence_update` | date | created | apply-decay 上次改 confidence 日期 |

### 组 ACCESS ─ 访问统计（供 apply-decay + record-access.sh 使用）

| 字段 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `created` | date | 创建日 | 用于计算 age |
| `last_accessed` | date | created | record-access.sh 自动更新 |
| `access_count` | int | 0 | record-access.sh ++ |
| `recent_accesses` | ISO8601[] | `[]` | 最近 10 次访问时间戳 |
| `ttl_days` | int | 见 §4 | 超过 ttl + 低 access → archive |
| `status` | enum | `active` | 见 §5 状态机 |

### 组 PROVENANCE ─ 溯源

| 字段 | 类型 | 含义 |
|------|------|------|
| `source` | string | `session/<name>` / `setup` / `manual` / `lift-from-logs` |

### 组 LINK ─ 关联

| 字段 | 类型 | 含义 |
|------|------|------|
| `area` | enum | `payment` / `growth` / `marketing` / `merchant` / `risk` / `_shared` |
| `session` | string | 关联 session_name |
| `topic_id` | int | 关联 .logs/topics.jsonl 的 topic id（Web 来源）|
| `run_id` | string | execution / distillation 的运行 ID |
| `goal_id` / `workspace_id` | int / string | 关联 .logs/ 的 ID |

### 组 GOAL ─ goal-note 专属（v0.8 新增）

| 字段 | 类型 | 含义 |
|------|------|------|
| `goal_id` | int | 关联 .logs/goals.jsonl 的 id |
| `goal_slug` | string | goal 简称 |
| `goal_status` | enum | `pending` / `in-progress` / `completed` / `failed` |
| `distill_status` | enum | `not-distilled` / `distilled` / `skipped` |
| `distilled_at` | date / null | 蒸馏完成日期 |

### 组 EXT ─ extension fragment 专属

| 字段 | 类型 | 含义 |
|------|------|------|
| `target` | string | 注入目标：`skill:<n>` / `mcp:<n>` / `plugin:<n>` |
| `priority` | enum | `high` / `medium` / `low` |
| `when` | string | 触发条件描述 |
| `hit_count` | int | 命中注入次数（替代 access_count）|

### 组 LEARNING ─ learnings 专属（autpilot-web runtime 管理）

> **注意**：Learnings 使用独立的记忆曲线衰减系统，不走 TRUST/ACCESS 组。
> 由 `autpilot-web` 的 `knowledge_distiller` 自动读写。

| 字段 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `category` | enum | `insight` | `mistake` / `insight` / `decision` / `pattern` / `external` / `rejected`（决定衰减速率。`rejected` = 否决提案/反模式，衰减最慢） |
| `importance` | float [0-1] | 0.5 | 重要度，用于 `score = importance * e^(-λt)` |
| `confidence` | float [0-1] | 0.7 | 信任度（可选，与 TRUST 组含义一致） |
| `pinned` | bool | false | 置顶（+0.5 score bonus） |
| `archived` | bool | false | 归档（score 直接为 0） |
| `options` | object[] | — | 决策选项树：`[{id, chosen, rationale/rejected_because}]`。捕获"选了什么"和"放弃了什么"——品味的 DNA |
| `traces` | object[] | — | 溯源：`[{kind, id, ...}]`。kind ∈ discuss/goal/code/execution/external |
| `review` | object | — | 决策复盘：`{outcome, decision_correct, lesson, reviewed_at}`。goal 执行后回写 |
| `promoted_to` | string / null | — | 升级到 domain/ 的路径（个案→模式跃迁指针） |

---

## 2. 各类文件用哪些组

> **✅ = 整组必填** ｜ **◯ = 整组可选** ｜ **— = 不要** ｜ **部分** = 看右侧备注

| 文件 | IDENTITY | TRUST | ACCESS | PROVENANCE | LINK | 专属组 | 备注 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|------|
| `domain/<area>/.../*.md` | ✅ | ✅ | ✅ | ✅ | `area` | — | |
| `profiles/team.md` `profiles/users/*.md` | ✅ | ✅ | ✅ | ✅ | — | — | |
| `sessions/topic-*/INDEX.md` | — | — | ✅ | — | `topic_id` | — | topic 概览，goals 列表 |
| `sessions/topic-*/goal-*.md` | — | — | ✅ | ✅ | `goal_id` + `topic_id` | GOAL ✅ | type=goal-note；含 goal_status + distill_status |
| `extensions/*/<n>/*.md` | 部分 | — | 部分 | ✅ | — | EXT ✅ | IDENTITY 只 `tags`；ACCESS 用 `hit_count` 代 `access_count`，其余 ACCESS 字段保留 |
| `learnings/*.md` | 部分 | — | — | — | — | LEARNING ✅ | **独立系统**：由 autpilot-web runtime 管理，使用记忆曲线衰减，不走 TRUST/ACCESS 组 |

---

## 3. Confidence 初始值（按来源）

| 来源 | 初始 confidence |
|------|----------------|
| stub / lift 占位 | 0.0 |
| 单 session 提取 | 0.6 |
| 用户明确陈述 | 0.7 |
| ≥2 session 复现 | 0.8 |
| 用户纠正过 AI | 0.9 |
| 代码 / config 实现 | 1.0 |

## 4. TTL 默认值（按 type）

| type | TTL | 延长条件 |
|------|-----|---------|
| foundation | 365 | access_count > 10 → +90 |
| convention | 180 | access_count > 5 → +90 |
| context | 60 | status=active → +60 |
| profile | 180 | manual |
| goal-note | 90 | — |
| extension | 180 | hit_count > 10 → +90 |

## 5. status 状态机

```
draft (stub / 未填好)
  │ 填好内容
  ▼
active (默认)
  │ /distill 完成
  ▼
distilled
  │ 90 天无新 access
  ▼
archived (移到 <layer>/archive/)
```

goal-note 用 `goal_status` + `distill_status` 双状态追踪（见 GOAL 组定义）。

---

## 6. 修改本 schema 的规则

字段变更 = 全知识库 schema 变更：

1. **先**改本文
2. **再**同步：
   - 读 frontmatter 的脚本（`_apply_decay.py` / `_record_access.py` / `_lift_session.py`）
   - 各 INDEX.md 里"本层差异"章节
   - 现有文件批量补字段（如新增必填字段）
3. PR 描述明列 schema 变更
