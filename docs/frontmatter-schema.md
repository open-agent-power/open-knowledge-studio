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
status: provisional | active | dropped | superseded
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
---
```

## 字段分类

- **IDENTITY** — title, type, area（均为必填）
- **TRUST** — status, importance, confidence
- **ACCESS** — pinned, archived, access_count
- **PROVENANCE** — created, source_type, fingerprint
- **LINK** — tags, traces, review
- **EXT** — superseded_by

### 字段说明

| 分类 | 字段 | 说明 |
|------|------|------|
| IDENTITY | `title` | 页面标题 |
| IDENTITY | `type` | 知识类型：concept（概念）、strategy（策略）、anti-pattern（反模式） |
| IDENTITY | `area` | 所属知识域（22 个域之一） |
| TRUST | `status` | 页面状态：provisional（临时）、active（活跃）、dropped（废弃）、superseded（已替代） |
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
