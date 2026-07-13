# Threads

Threads are your raw material layer. They keep the original flow of what happened: articles you read, papers you collected, conversations you had, and traces from tool results.

Their real value is not just storage. Threads become useful when you can search past sources, reopen exact context, and distill the durable parts into [memories](memories.md).

> **Use threads when you need the full history. Use memories when you only need the takeaway.**
> If you need the original source, keep it in `raw/`. If you only need the durable pattern, distill it into `wiki/` memories and work from there.

## The First Useful Thread

If you are new, do one of these first:

* save one article or note into `raw/`
* let one `/ingest` run extract drafts from it
* distill one useful memory from those drafts

Then open that memory and confirm it captured what mattered. That is the core workflow.

| I want to... | Jump to |
|---|---|
| Save an article or paper | [Save to raw/](#saving-to-raw) |
| Ingest raw materials into drafts | [Distillation](#distillation) |
| Import a conversation | [Import Formats](#import-formats) |
| Search past raw materials | [Searching Threads](#searching-threads) |
| Learn the raw/ directory structure | [Directory Structure](#directory-structure) |

## Directory Structure

```
raw/
├── articles/       # Blog posts, web articles, documentation
├── papers/         # Academic papers, PDFs (parsed to markdown)
├── repos/          # Code repository notes, README summaries
└── misc/           # Conversations, traces, notes, anything else
```

Materials are organized by type, not by date. Each file is a self-contained markdown document with optional YAML frontmatter.

### Raw File Format

```markdown
---
title: "Understanding Event-Driven Architecture"
source: https://example.com/event-driven-architecture
date: 2026-07-13
type: article
tags: [architecture, event-driven, microservices]
---

# Understanding Event-Driven Architecture

Event-driven architecture is a paradigm where services communicate...
```

**Minimal format** — just a markdown file with content. Frontmatter is optional but recommended for better search results.

## Saving to Raw

### From a File

Drop any markdown file into the appropriate `raw/` subdirectory:

```bash
cp ~/Downloads/article.md raw/articles/
```

### From CLI

```bash
echo "We decided to use FastAPI for the new service" > raw/misc/api-decision.md
```

### From AI Conversations

Save conversation summaries or Q&A extractions:

```markdown
## User

What's the best approach for state management in React?

## Assistant

For large applications, Zustand is lightweight and avoids the boilerplate
of Redux. For simpler apps, React Context is sufficient...

## Decision

Use Zustand for state management — lightweight, no boilerplate, good DX.
```

## Distillation

The key workflow that connects threads (raw/) to memories (wiki/).

### How It Works

1. **Scan** — `/ingest` skill or `oks distill` scans `raw/` for patterns
2. **Grade** — AI evaluates each material: A-grade (promote to draft), B-grade (hold), C-grade (skip)
3. **Write Drafts** — A-grade materials become candidate wiki pages in `drafts/{slug}.md`
4. **Human Review** — `/promote` skill: accept → `wiki/`, revise, or reject
5. **Apply Decay** — all wiki pages re-scored; low-score pages archived
6. **Evolve** — 3+ same-tag pages with score > 0.5 → synthesized Crystal draft

```bash
oks distill --dry-run    # preview
oks distill              # execute
oks drafts list          # review candidates
oks drafts promote <slug>
```

### Quality Gates

Materials are filtered before becoming drafts:

- Skip if content < 50 chars
- Skip if title is generic (e.g., "Untitled", "Note")
- Skip if importance < 0.3
- Deduplicate by content fingerprint

## Import Formats

### Conversation Markdown

The portable format for importing conversations. Any tool that writes `## User` / `## Assistant` headers produces a file Studio can read.

```markdown
---
title: Python Async Patterns
source: chatgpt
date: 2026-07-13
---

## User

How does async/await work in Python?

## Assistant

Python's `async`/`await` lets you write concurrent code that doesn't block
while waiting for I/O. An `async def` function returns a coroutine...

## User

When should I use asyncio vs threading?

## Assistant

Use asyncio for I/O-bound work. Use threading for blocking libraries.
Use multiprocessing for CPU-bound work.
```

**Format rules:**
- Headers: `## User`, `## Assistant`, or `## System` (level-2 heading, one per message)
- Content: Everything between headers is one message
- Frontmatter: Optional YAML block with `title`, `source`, `date`
- Files without recognized headers are imported as a single document

## Searching Threads

### By Keyword

```bash
oks search "authentication" --source raw
```

### By Freshness

The recall engine applies a freshness factor: `0.95^days_old`. Newer materials score higher in episodic recall.

### Dual-Path Recall

```bash
oks recall "database design" --limit 5
```

Returns both episodic results (from `raw/`) and knowledge results (from `wiki/`).

## Thread vs Memory — When to Use Which

| Scenario | Use Thread (raw/) | Use Memory (wiki/) |
|----------|-------------------|---------------------|
| Need the full conversation | Yes | No |
| Need the durable pattern | No | Yes |
| Searching for a specific decision | Maybe | Yes (higher relevance) |
| Want to trace how understanding evolved | Both | Yes (version links) |
| Quick lookup | No | Yes (faster, scored) |

## Next Steps

* **[Memories](memories.md)**: What happens after distillation
* **[Dreaming Cycle](dreaming-cycle.md)**: The full evolution pipeline
* **[Recall Engine](recall-engine.md)**: How search scoring works
* **[Architecture](architecture.md)**: Five-bucket structure
