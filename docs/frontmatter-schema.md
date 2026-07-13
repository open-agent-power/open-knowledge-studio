# Frontmatter Schema v0.7

YAML frontmatter spec for wiki pages, drafts, and profiles.

## Wiki Page

```yaml
---
# IDENTITY
title: "Title"
type: concept | strategy | anti-pattern
area: <domain>

# TRUST
status: provisional | active | dropped | superseded
importance: 0.0-1.0
confidence: 0.0-1.0

# ACCESS
pinned: false
archived: false
access_count: 0

# PROVENANCE
created: "ISO datetime"
source_type: auto | manual
fingerprint: "<sha256[:16]>"

# LINK
tags: "comma, separated"
traces: [{id, type, url}]    # optional
review: {decision_correct, outcome, reviewer}  # optional

# EXT
superseded_by: "<slug>"      # if status: superseded
---
```

## Categories

- **IDENTITY** — title, type, area (all required)
- **TRUST** — status, importance, confidence
- **ACCESS** — pinned, archived, access_count
- **PROVENANCE** — created, source_type, fingerprint
- **LINK** — tags, traces, review
- **EXT** — superseded_by

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
