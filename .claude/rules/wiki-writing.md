---
description: Writing conventions for wiki/ knowledge pages
globs: wiki/**/*.md
---

# Wiki Writing Rules

## Frontmatter (required)

Every wiki page must have YAML frontmatter with these fields:

```yaml
---
title: "Human-readable title"
type: concept | strategy | anti-pattern
area: <domain>
status: provisional | active | dropped | superseded
importance: 0.0-1.0
confidence: 0.0-1.0
created: "YYYY-MM-DD" or ISO datetime
tags: "comma, separated, tags"
pinned: false
archived: false
---
```

## Page Types

- **concept** — declarative knowledge, facts and explanations (λ=0.0)
- **strategy** — procedural knowledge, how-to approaches (λ=0.014)
- **anti-pattern** — mistakes and lessons learned (λ=0.010)

## Body Structure

- Start with a 1-2 sentence summary
- Use `##` for sections
- Link to related pages with relative paths
- Cite sources with `[verified]`, `[user-stated]`, `[inferred]`, or `[stale]` labels

## Quality Signals

- Add `traces:` for tool-verified facts
- Add `review:` for human-reviewed decisions
- Tags improve recall — always include at least one

## Atomic Writes

All writes use `mkstemp + fsync + os.replace` via the CLI (`oks wiki create`).
