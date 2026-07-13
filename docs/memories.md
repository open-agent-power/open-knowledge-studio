# Memories

A memory is one durable thing worth keeping: a concept, a strategy, an anti-pattern, or a decision. Each memory should stand on its own, readable without the full conversation that produced it.

Memories are the core unit of Open Knowledge Studio. Search, decay, evolution, and Claude Code integration all become more useful because memories exist underneath them.

## Memories vs Threads

| | Memory (wiki/) | Thread (raw/) |
|---|---|---|
| **What** | The durable takeaway | The original conversation or source |
| **Who writes** | LLM writes, human approves | Human collects |
| **Decay** | Type-specific λ | None |
| **Recall** | 6-factor relevance + curve | Keyword + freshness |
| **Use when** | You need the pattern | You need the full history |

A strong workflow is: save or import the source into `raw/`, then distill the parts worth keeping into `wiki/` memories.

## The First Useful Memory

If you are new, do not overthink structure first. Save one real thing such as:

* a concept you learned
* a strategy that worked
* an anti-pattern you want to avoid

Then search for it. Once that works, this whole page becomes much easier to understand.

## Anatomy of a Memory

| Field | What it is |
|-------|------------|
| **title** | A short summary. Set in frontmatter |
| **type** | `concept`, `strategy`, or `anti-pattern` |
| **area** | One of 22 knowledge domains (e.g., `computing`, `management`) |
| **importance** | 0.1 to 1.0 — affects search ranking and decay priority |
| **content** | The knowledge itself. Markdown body after frontmatter |
| **tags** | Categories for filtering and organization |
| **created** | Timestamp. Used for temporal search and decay calculation |
| **access_count** | How many times this memory was recalled. Reinforces confidence |
| **status** | `active`, `provisional`, `archived`, `dropped`, or `superseded` |

### Importance Scale

| Range | Meaning | Examples |
|-------|---------|----------|
| 0.8 – 1.0 | Critical | Architectural decisions, core patterns, production anti-patterns |
| 0.5 – 0.7 | Useful | Standard strategies, good practices, project learnings |
| 0.1 – 0.4 | Background | Reference info, minor details, casual notes |

The default is 0.5. The recall engine uses this score to prioritize what surfaces in search results.

### Memory Type

Each memory has one primary type. This helps the recall engine decide how to weight it:

| Type | Use for | Type Boost | Decay λ |
|------|---------|------------|---------|
| `concept` | Durable reference knowledge | ×0.6 | 0.0 (no decay) |
| `strategy` | Approaches, decisions, workflows | ×0.8 | 0.014 (slow) |
| `anti-pattern` | Things to avoid, failure patterns | ×1.5 | 0.010 (moderate) |

Anti-patterns get the highest boost (×1.5) because mistakes are the most valuable to recall — you want to find them before you repeat them.

### Tags

Tags are lowercase and hyphenated (`api-design`, `react-patterns`). Filter by tag in search:

```bash
oks search "error handling" --type strategy
```

### Source Labels

Every memory carries a source label indicating its confidence level:

| Label | Meaning |
|-------|---------|
| `[verified]` | Tool-confirmed (has traces) or human-reviewed |
| `[user-stated]` | User explicitly stated this |
| `[inferred]` | AI-distilled from raw materials, not yet verified |
| `[stale]` | May be outdated, pending re-verification |

## Creating Memories

### From Raw Materials (Primary Path)

1. Place source material in `raw/` (article, paper, conversation summary)
2. Run `/ingest` in Claude Code or `oks distill` — AI scans and identifies patterns
3. Candidates are written to `drafts/{slug}.md`
4. Review with `/promote` — accept, revise, or reject
5. Accepted drafts become `wiki/{domain}/{type}/{slug}.md`

### From AI Conversations

Use the `/archive` skill to extract Q&A from conversations and write them to wiki.

### From CLI

```bash
oks wiki create \
  --title "Use Typer for CLI tools" \
  --type strategy \
  --area computing \
  --importance 0.7
```

### From Templates

```bash
cp templates/strategy.md wiki/computing/strategies/my-strategy.md
# Edit the frontmatter and body
```

## Searching Memories

### Three Search Modes

| Mode | How it works | Best for |
|------|-------------|----------|
| **Semantic** | Token overlap via jieba — finds by meaning, not just exact words | "design patterns" finds "architectural approaches" |
| **Keyword** | Substring match in title and body | Exact terms, code names, specific APIs |
| **Graph** | Topic trace + type boost + review penalty | Finding related decisions, tracing topic history |

The 6-factor recall engine combines all three automatically. See [Recall Engine](recall-engine.md) for the full algorithm.

### From CLI

```bash
oks search "authentication patterns"
oks search "error handling" --domain computing --type strategy
oks recall "database design" --limit 5
oks wiki list --domain computing --status active
```

### From Claude Code

```
/query What patterns do we have for error handling?
```

Claude Code calls `oks recall`, injects relevant wiki/ pages into context with source labels, and answers with citations.

## Editing and Organizing

### Update a Memory

Edit the wiki page directly. Changes take effect immediately.

```bash
oks wiki pin <slug>      # boost importance (pin_bonus = 0.5)
oks wiki archive <slug>  # move to archived status
```

### Delete a Memory

Memories are never deleted — they are archived (`status: dropped`) or superseded (`status: superseded`). Git history is the safety net.

## How Memories Connect

When you save something new about a topic you've written about before, the system tracks the relationship:

| Relationship | Meaning |
|--------------|---------|
| `supersedes` | New page replaces the old one — old page marked `superseded` |
| `enriches` | New page adds to the old one — both stay active |
| `confirms` | New page validates the old one — confidence boosted |
| `challenges` | New page contradicts the old one — old page flagged for review |

This creates a knowledge evolution graph. Trace how your understanding of any topic changed over time.

### Crystals — Synthesized Reference Articles

When 3+ memories cover the same ground (same tag + score > 0.5), the system can synthesize them into a reference article — a **Crystal**. Sources are cited. When you save related information later, the Crystal updates.

This happens automatically during the Dreaming cycle. See [Dreaming Cycle](dreaming-cycle.md) for details.

## Memory Lifecycle

```
Provisional → Active (access_count ≥ 3) → Dropped (score < threshold)
                                         → Superseded (replaced by newer page)
```

| Tier | Score | Behavior |
|------|-------|----------|
| **hot** | ≥ 0.7 | Priority recall, high confidence |
| **warm** | ≥ 0.4 | Normal recall |
| **cold** | ≥ 0.15 | Low priority, may need review |
| **evictable** | < 0.15 | Archive candidate — suggested for removal |

Access reinforces confidence: `new_confidence = min(1.0, current + 0.1 × (1 - current))`

## Where Memories Come From

| Source | How | Learn more |
|--------|-----|------------|
| Raw materials | `/ingest` triage → drafts → `/promote` | [Threads](threads.md) |
| AI conversations | `/archive` extracts Q&A | — |
| CLI | `oks wiki create` | [Start Here](start-here.md) |
| Templates | Copy from `templates/` | — |
| Dreaming evolution | 3+ same-tag pages → Crystal | [Dreaming Cycle](dreaming-cycle.md) |

## Next Steps

* **[Threads](threads.md)**: Raw materials, distillation workflow, and import paths
* **[Recall Engine](recall-engine.md)**: 6-factor scoring algorithm in detail
* **[Dreaming Cycle](dreaming-cycle.md)**: How memories evolve, connect, and synthesize
* **[Decay System](decay-system.md)**: Memory curve, type-specific λ, and tier classification
* **[Architecture](architecture.md)**: Five-bucket structure and memory lifecycle
