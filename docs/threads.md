# Raw Materials

Raw is your intake layer — the original sources before distillation. Articles you read, papers you collected, code repos you studied, conversations you had. The system reads them, grades them, and distills the durable parts into [memories](memories.md).

> **Raw is not Thread.** Competitors lump everything into "conversations." We don't.
> Our raw/ has **typed intake** (articles / papers / repos / misc), **A/B/C grading**,
> **fingerprint dedup**, and **human-gated promotion**. That's the difference.

## Why raw/ is not just "conversations"

| Our raw/ | Generic "Thread" |
|----------|-------------------|
| 4 typed subdirectories (articles/papers/repos/misc) | Flat list, conversations only |
| A/B/C grading before distillation | All-or-nothing import |
| Fingerprint dedup prevents duplicate drafts | No dedup |
| Human-gated: raw → draft → review → wiki | Auto-promote or manual-only |
| Feeds into 22-domain × 3-type structured wiki/ | Flat memory store |
| Source-tracked: each draft records its raw origin | No provenance |

## The First Useful Raw Material

If you are new, do one of these first:

* save one article or note into `raw/`
* let one `/ingest` run grade and extract drafts
* distill one useful memory from those drafts

Then open that memory and confirm it captured what mattered. That is the core workflow.

| I want to... | Jump to |
|---|---|
| Save an article or paper | [Save to raw/](#saving-to-raw) |
| Ingest raw materials into drafts | [Distillation](#distillation) |
| Import a conversation | [Import Formats](#import-formats) |
| Understand A/B/C grading | [Quality Gates](#quality-gates) |
| Search past raw materials | [Searching Raw](#searching-raw) |

## Directory Structure

```
raw/
├── articles/       # Blog posts, web articles, documentation pages
├── papers/         # Academic papers, PDFs (parsed to markdown)
├── repos/          # Code repository notes, README summaries, code patterns
└── misc/           # Conversations, traces, notes, anything else
```

Materials are **organized by type, not by date**. This matters because the A/B/C grading and quality gates apply differently per type — an academic paper gets deeper analysis than a quick note.

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

**Minimal format** — just a markdown file with content. Frontmatter is optional but recommended for better search results and source tracking.

### Source Tracking

Every raw file can carry provenance metadata in frontmatter:

| Field | Purpose |
|-------|---------|
| `source` | URL or path where the material was obtained |
| `date` | When the material was collected |
| `type` | `article` / `paper` / `repo` / `conversation` / `note` |
| `tags` | Topic tags for filtering |

When a raw material is distilled into a draft, the draft records its origin. This creates a **provenance chain**: wiki page ← draft ← raw file ← original source. You can always trace a curated memory back to its source.

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

Save conversation summaries or Q&A extractions. The `/archive` skill can extract Q&A from Claude Code sessions and write them to raw/misc/:

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

The key workflow that connects raw materials (raw/) to memories (wiki/).

### How It Works

```
raw/ (human-collected)
  ↓ /ingest — AI scans + A/B/C grades each file
  ↓ A-grade → drafts/ (candidate wiki pages)
  ↓ B-grade → held in raw/ for future cycles
  ↓ C-grade → skipped
drafts/ (intermediate proposals)
  ↓ /promote — human review: accept / revise / reject
wiki/ (curated knowledge, with decay + evolution)
```

### A/B/C Grading — Our Advantage

Unlike competitors that import everything or nothing, our system grades each raw material:

| Grade | Meaning | Action |
|-------|---------|--------|
| **A** | High-quality, pattern-worthy | Write to `drafts/` for human review |
| **B** | Potentially useful | Keep in `raw/`, re-evaluate in next cycle |
| **C** | Low quality or duplicate | Skip, leave in `raw/` |

This means the human only reviews the best candidates, not every file in raw/.

### Quality Gates

Before a raw material becomes an A-grade draft, it must pass:

| Gate | Rule | Why |
|------|------|-----|
| Content length | Skip if < 50 chars | Too short to contain useful knowledge |
| Title check | Skip if generic ("Untitled", "Note") | No pattern to extract |
| Importance floor | Skip if < 0.3 | Low-value knowledge not worth curating |
| Fingerprint dedup | Skip if content hash already drafted | Prevents duplicate wiki pages |

**Fingerprint dedup** is our unique advantage — the system computes a content hash for each raw file and checks it against existing drafts. If the same content was already distilled, it won't create a duplicate. This keeps wiki/ clean as raw/ grows.

### Running Distillation

```bash
# Preview what would be distilled (no writes)
oks distill --dry-run

# Run the full cycle: grade raw → write drafts → apply decay → evolve
oks distill

# List drafts awaiting human review
oks drafts list

# Promote a draft to wiki
oks drafts promote <slug>
```

## Import Formats

### Conversation Markdown

The portable format for importing conversations. Any tool that writes `## User` / `## Assistant` headers produces a file we can read.

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

### Bulk Import

```bash
# Copy all articles into raw/
cp ~/Downloads/articles/*.md raw/articles/

# Run distill to process them all
oks distill --dry-run  # preview
oks distill            # execute
```

## Searching Raw

### By Keyword

```bash
oks search "authentication" --source raw
```

### By Freshness

The recall engine applies a freshness factor: `0.95^days_old`. Newer materials score higher in episodic recall. This means recent raw materials surface first when you search.

### Dual-Path Recall

```bash
oks recall "database design" --limit 5
```

Returns both episodic results (from `raw/`) and knowledge results (from `wiki/`), combined:

```json
{
  "episodic": [...],   // raw/ materials matching by keyword + freshness
  "knowledge": [...]    // wiki/ pages matching by 6-factor relevance + curve
}
```

## Raw Material vs Memory — When to Use Which

| Scenario | Use Raw (raw/) | Use Memory (wiki/) |
|----------|---------------|---------------------|
| Need the full original source | Yes | No |
| Need the durable pattern | No | Yes |
| Searching for a specific decision | Maybe | Yes (higher relevance, scored) |
| Want to trace understanding evolution | Both | Yes (version links, supersession) |
| Quick lookup with confidence | No | Yes (tier-scored, source-labeled) |
| Need provenance chain | Start here | Links back to raw origin |

## Our Pipeline Advantage

```
raw/ (typed intake)
  ↓ A/B/C grading (filter noise)
  ↓ fingerprint dedup (prevent duplicates)
drafts/ (human-gated review)
  ↓ /promote — accept / revise / reject
wiki/ (22 domains × 3 types, with decay)
  ↓ 6-factor recall + memory curve
  ↓ evolve: 3+ same-tag → Crystal
injected into Claude Code context
```

Each step has a quality gate. Nothing reaches wiki/ without passing through grading AND human review. This is why our wiki/ stays clean as raw/ grows — the pipeline filters noise at every stage.

## Next Steps

* **[Memories](memories.md)**: What happens after distillation — anatomy, types, search
* **[Dreaming Cycle](dreaming-cycle.md)**: The full evolution pipeline including Crystals
* **[Recall Engine](recall-engine.md)**: How 6-factor search scoring works
* **[Architecture](architecture.md)**: Five-bucket structure and lifecycle
