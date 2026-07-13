# Dreaming Cycle

Knowledge evolves through **human-reviewed draft proposals** — the system never auto-promotes raw content to wiki.

This process is the platform's **Dreaming** — periodic memory consolidation that distills raw experiences into structured wiki knowledge, like sleep consolidation in human memory.

## Dream Cycle

```
Collect → AI Dream → Write Drafts → Human Review → Promote → Decay → Evolve → Commit
```

### 1. Collect

Traces, conversations, articles, and papers accumulate in `raw/`. This is the raw material layer — human-collected, LLM-readable but LLM does not write here.

### 2. AI Dream

Claude Code `/ingest` skill scans `raw/`, identifies patterns, and generates candidate wiki pages. The AI evaluates each material:

- **A-grade** — high-quality, promotes to draft
- **B-grade** — potentially useful, held in raw for future cycles
- **C-grade** — low quality, skipped

Quality gates filter out:
- Content < 50 chars
- Generic titles ("Untitled", "Note")
- Importance < 0.3
- Duplicates (by content fingerprint)

### 3. Write Drafts

A-grade candidates are written to `drafts/{slug}.md` with draft frontmatter. Each draft is a proposed wiki page with:
- Proposed title, type, area, tags
- Source attribution (which raw material it came from)
- Initial importance score

### 4. Human Review

`/promote` skill provides interactive review:

- **Accept** — promote to `wiki/{domain}/{type}/`
- **Revise** — edit the draft and re-review
- **Reject** — discard the draft

**Core invariant**: Never auto-promote raw to wiki without human review (CONSTITUTION.md A3).

### 5. Promote

```bash
oks drafts list           # see all candidates
oks drafts promote <slug> # promote to wiki
oks drafts reject <slug>  # discard
```

When promoting, the draft's frontmatter is finalized and the page moves to `wiki/{domain}/{type}/{slug}.md`.

### 6. Apply Decay

`oks distill` re-scores all wiki pages. Pages below the archive threshold get `status: dropped`. Pages not accessed in a long time fade according to their type-specific decay rate.

### 7. Evolve — Crystals

When 3+ wiki pages share the same primary tag and all have score > 0.5, the system synthesizes them into a **Crystal** — a reference article that merges insights from multiple memories.

```
evolve_knowledge():
  scan wiki/ for pages with score > 0.5
  group by primary tag
  3+ pages with same tag → merged draft proposal
```

The Crystal:
- Cites all source pages
- Merges overlapping insights
- Gets its own wiki page with `type: concept`
- Updates when related information is saved later

This is how scattered memories become organized reference knowledge.

### 8. Working Memory — Daily Briefing

Each day, Studio can generate a briefing from recent and important memories. This working memory provides Claude Code with context about what you're working on before you say a word.

The briefing draws from:
- Recently created or updated wiki pages
- High-importance memories (importance ≥ 0.7)
- Recently accessed raw materials
- Active project profiles

### 9. Git Commit

`oks sync` commits all changes — new wiki pages, updated drafts, decayed scores, Crystal articles.

```bash
oks sync           # commit + push
oks sync --pull    # pull first, then commit + push
```

## Full Cycle Command

```bash
# Run the complete dream cycle (decay + evolve)
oks distill

# Preview without writing
oks distill --dry-run

# Interactive review of generated drafts
oks drafts list
oks drafts promote <slug>
```

## Core Invariant

**Never auto-promote raw to wiki without human review** (CONSTITUTION.md A3).

The AI can dream, but humans decide what becomes permanent knowledge.

## Implementation

- `/ingest` — AI triage (Claude Code skill)
- `oks distill` — decay + evolve (CLI)
- `/promote` — human review (Claude Code skill)
- `cli/knowledge_studio/distiller.py` — core logic

## Next Steps

* **[Memories](memories.md)**: What memories look like after promotion
* **[Threads](threads.md)**: What raw materials look like before distillation
* **[Decay System](decay-system.md)**: How memory scores change over time
* **[Architecture](architecture.md)**: The five-bucket structure
