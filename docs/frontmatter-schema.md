---
title: Frontmatter Schema
nav_order: 21
parent: 参考
---

# Frontmatter Schema v1.0

本页是 wiki 页面 frontmatter 的日常使用规则。底层数据形状契约见 `_meta/raw-evidence-schema.md`。

## Wiki 页面

```yaml
---
title: "Use Typer for CLI tools"
type: strategy                 # concept | strategy | anti-pattern
area: computing
status: provisional            # provisional | active | stale | dropped | superseded
source_type: auto              # auto | manual
importance: 0.7                # 0 到 1
confidence: 0.8                # 0 到 1
created: "2026-07-27T12:00:00Z"
pinned: false
archived: false
tags: "python, cli"
fingerprint: "0123456789abcdef"
traces:
  - id: "run-001"
    kind: execution
    url: "raw/executions/run-001/events.jsonl"
review:
  decision_correct: true
  outcome: success
  lesson: ""
relates_to: "older-page"
relationship: confirms         # supersedes | enriches | confirms | challenges
---
```

`title`、`type`、`area` 是必填身份字段。`access_count`、记忆分数、tier 和质量分数由 CLI 在读取时计算，不写回 frontmatter。

关系约束：`relationship` 必须和 `relates_to` 同时存在；`status: superseded` 必须填写 `superseded_by`；`traces` 必须是对象列表且不得保存密钥、Token、Cookie 等凭据。

## Draft

```yaml
---
title: "CLI framework decision"
draft_type: strategy
draft_area: computing
source_pages: ["raw/source-note.md"]
source_note: "Optional provenance note"
drafted_at: "2026-07-27"
status: draft
---
```

Draft 是待审提案。AI 生成内容先进入 `drafts/`，只有明确的人类操作才能提升到正式 `wiki/`。

## Goal profile

```yaml
---
title: "Ship structured memory"
type: goal
status: active
domains: [computing]
keywords: [recall, evaluation, trace]
---
```

Goal 位于 `profiles/goals/`。`--goal active` 合并活跃目标，`--goal <slug>` 固定一个目标，`--goal none` 作为无目标基线。

## 机器契约

`_meta/recall-case.schema.json`、`_meta/trace-event.schema.json` 和 `_meta/run-manifest.schema.json` 分别约束评测数据集、执行事件和运行清单。

---

{% include comments.html %}
