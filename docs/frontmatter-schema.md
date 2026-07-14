---
title: Frontmatter Schema
nav_order: 9
---
# Frontmatter Schema v0.7

Wiki 页面、draft 和画像的 YAML frontmatter 规范。

## Wiki 页面

```yaml
---
# IDENTITY（身份）
title: "Title"
type: concept | strategy | anti-pattern
area: <domain>

# TRUST（信任）
status: provisional | active | stale | dropped | superseded
importance: 0.0-1.0
confidence: 0.0-1.0

# ACCESS（访问）
pinned: false
archived: false
access_count: 0

# PROVENANCE（来源）
created: "ISO datetime"
source_type: auto | manual
fingerprint: "<sha256[:16]>"

# LINK（关联）
tags: "comma, separated"
traces: [{id, type, url}]    # 可选
review: {decision_correct, outcome, reviewer}  # 可选

# EXT（扩展）
superseded_by: "<slug>"      # 当 status: superseded 时

# RELATIONSHIPS（知识关系）
relates_to: "<slug>"           # 关联的旧页面 slug
relationship: supersedes|enriches|confirms|challenges
enriched_by: "<slug>"          # 被哪个页面补充（旧页面字段）
confirmed_by: "<slug>"         # 被哪个页面确认（旧页面字段）
challenged_by: "<slug>"        # 被哪个页面挑战（旧页面字段）
---
```

## 字段分类

- **IDENTITY** — title, type, area（均为必填）
- **TRUST** — status, importance, confidence
- **ACCESS** — pinned, archived, access_count
- **PROVENANCE** — created, source_type, fingerprint
- **LINK** — tags, traces, review
- **EXT** — superseded_by
- **RELATIONSHIPS** — relates_to, relationship, enriched_by, confirmed_by, challenged_by

### 字段说明

| 分类 | 字段 | 说明 |
|------|------|------|
| IDENTITY | `title` | 页面标题 |
| IDENTITY | `type` | 知识类型：concept（概念）、strategy（策略）、anti-pattern（反模式） |
| IDENTITY | `area` | 所属知识域（22 个域之一） |
| TRUST | `status` | 页面状态：provisional（临时）、active（活跃）、stale（过期）、dropped（废弃）、superseded（已替代） |
| TRUST | `importance` | 重要性 0.0-1.0，影响记忆曲线评分 |
| TRUST | `confidence` | 置信度 0.0-1.0，随访问增强提升 |
| ACCESS | `pinned` | 是否固定，pinned 页面获得 +0.5 加成 |
| ACCESS | `archived` | 是否归档 |
| ACCESS | `access_count` | 被召回命中的次数 |
| PROVENANCE | `created` | 创建时间 |
| PROVENANCE | `source_type` | 来源类型：auto（AI 生成）、manual（手写） |
| PROVENANCE | `fingerprint` | 内容指纹，前 16 位 sha256，用于去重 |
| LINK | `tags` | 逗号分隔的标签 |
| LINK | `traces` | 关联的 trace 列表（可选） |
| LINK | `review` | 审查结果（可选） |
| EXT | `superseded_by` | 替代此页面的新页面 slug |

## Draft

```yaml
---
title: "..."
draft_type: concept | strategy | anti-pattern
draft_area: <domain>
source_pages: [<slug>, ...]
drafted_at: "YYYY-MM-DD"
status: draft
---
```

Draft frontmatter 是 wiki 页面的前置状态。`source_pages` 记录了 draft 来自哪些 raw materials，形成来源链路。当 draft 被 promote 后，frontmatter 转换为 wiki 页面格式，`draft_type` → `type`，`draft_area` → `area`。

## 知识关系字段

RELATIONSHIPS 字段用于建立新旧知识页面之间的关系网络，支持知识的演进追踪和冲突感知。

### 新页面字段

- **`relates_to`** — 新页面关联的旧页面 slug。新页面通过此字段声明它与哪个已有页面有关系。
- **`relationship`** — 声明关系类型，取值 `supersedes`、`enriches`、`confirms`、`challenges`。

### 旧页面字段

旧页面通过以下被动字段记录被新页面引用的关系：

- **`enriched_by`** — 被哪个新页面补充（新页面提供了额外细节或上下文）。
- **`confirmed_by`** — 被哪个新页面确认（新页面验证了旧页面的结论）。
- **`challenged_by`** — 被哪个新页面挑战（新页面质疑或推翻了旧页面的结论）。

### 关系类型及效果

| 关系 | 新页面声明 | 旧页面被动字段 | 效果 |
|------|-----------|---------------|------|
| **supersedes** | `relationship: supersedes` | `status` → `superseded` + `superseded_by` | 旧页面被标记为已替代，召回时降权 |
| **enriches** | `relationship: enriches` | `enriched_by` | 旧页面保留有效，新页面提供补充信息，召回时两者均可返回 |
| **confirms** | `relationship: confirms` | `confirmed_by` | 旧页面 confidence 提升，新旧页面互相增强 |
| **challenges** | `relationship: challenges` | `challenged_by` | 旧页面 confidence 降低，召回时附带冲突警告 |

`supersedes` 是最强的关系 — 旧页面被明确替代，状态变为 `superseded`，并通过 `superseded_by` 指向新页面。其余三种关系保留旧页面的有效状态，但在召回时影响排序和置信度。

---

{% include comments.html %}
