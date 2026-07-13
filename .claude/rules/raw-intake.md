---
description: Intake conventions for raw/ materials
globs: raw/**
---

# Raw Intake Rules

## Purpose

`raw/` stores unprocessed materials — conversation logs, articles, papers, traces.
Human-collected; AI reads but does not write to `raw/` (writes go to `drafts/`).

## Structure

```
raw/
├── articles/
├── papers/
├── repos/
├── misc/
└── {YYYY}/{MM}/{DD}/
    └── {topic_id}/
        ├── conversation.jsonl
        └── summary.md
```

## Intake Rules

- Only write to `raw/` if collecting original material (not AI-generated)
- AI-generated summaries go to `drafts/`, never `raw/`
- Include source URL, date, and author when available
- File naming: `{YYYYMMDD}-{short-slug}.md`

## Recall

`recall_episodic()` searches `raw/` by keyword + freshness scoring.
Freshness decays at `0.95^days_old`.
