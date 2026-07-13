# Architecture

## Thread vs Memory — The Core Distinction

| | Thread (raw/) | Memory (wiki/) |
|---|---|---|
| **What** | The original conversation, article, or source | The durable takeaway, distilled and curated |
| **Who writes** | Human collects, LLM reads only | LLM writes via Dreaming, human approves |
| **Decay** | None — raw materials are permanent | Type-specific λ — knowledge fades over time |
| **Recall** | Keyword + freshness | 6-factor relevance + memory curve |
| **Use when** | You need the full history or exact source | You need the pattern, decision, or lesson |

A strong workflow: save the source into `raw/`, then distill the parts worth keeping into `wiki/` memories.

## Five-Bucket Memory Architecture

| Bucket | Purpose | Decay | Recall |
|--------|---------|-------|--------|
| `profiles/` | Team, user, project profiles | None | Direct read |
| `raw/` | Raw materials (threads) | None | Keyword + freshness |
| `wiki/` | Curated knowledge (memories) | Type-specific λ | 6-factor recall |
| `drafts/` | Dreaming candidates | None | N/A (human review) |
| `settings/` | System config | None | Direct read |

## Directory Structure

```
open-knowledge-studio/
├── profiles/          # ① Profiles
│   ├── team.md
│   ├── users/{id}.md
│   └── projects/{slug}.md
├── raw/               # ② Raw materials (threads)
│   ├── articles/  papers/  repos/  misc/
├── wiki/              # ③ Curated knowledge (memories)
│   └── {domain}/{type}/{slug}.md
│       # types: concept | strategy | anti-pattern
├── drafts/            # ④ Dreaming candidates
└── settings/          # ⑤ System config
    ├── decay-config.yaml
    └── input-sources.json
```

## 22 Knowledge Domains

management, transport, finance, production, computing, repair, engineering, construction, science, agriculture, social, administration, legal, sales, education, personal, media, healthcare, care, maintenance, food, security

Each domain has three subdirectories: `concepts/`, `strategies/`, `anti-patterns/`.

## Memory Lifecycle

```
Observe → Write → Store → Retrieve → Inject → Forget
```

1. **Observe** — conversations, tool results, traces, feedback
2. **Decide to write** — high-confidence, reusable, source-annotated
3. **Store** — write to appropriate bucket by type
4. **Retrieve** — scope first (workspace → topic → goal → time), then keyword search
5. **Inject** — layered, stable first (KV Cache), with source labels
6. **Update/Forget** — mark stale, re-score, archive

## Wiki Page Lifecycle

```
Provisional → Active (access_count ≥ 3) → Dropped (score < threshold)
                                         → Superseded (replaced by newer page)
```

### Knowledge Evolution Relationships

When new knowledge relates to existing knowledge, four relationships are tracked:

| Relationship | Meaning | Effect on old page |
|--------------|---------|---------------------|
| `supersedes` | New page replaces the old one | Marked `superseded`, excluded from recall |
| `enriches` | New page adds to the old one | Both stay active, linked |
| `confirms` | New page validates the old one | Old page confidence boosted |
| `challenges` | New page contradicts the old one | Old page flagged `[stale]` for review |

### Crystals — Synthesized Reference Articles

When 3+ memories share the same tag and score > 0.5, the system synthesizes them into a reference article — a **Crystal**. Sources are cited. When related information is saved later, the Crystal updates.

### Working Memory — Daily Briefing

Each day, Studio can generate a briefing from recent and important memories. This working memory file (`~/ai-now/memory.md` or equivalent) provides Claude Code with context about what you're working on before you say a word.

## Design Principles

- **Git IS the migration** — no database, schema changes versioned through `_meta/`
- **Atomic writes** — all persistent writes use `mkstemp + fsync + os.replace`
- **Human-gated** — the system never auto-promotes raw content to wiki without review
- **No AI configuration** — Claude Code is the AI engine, CLI only handles file ops + recall scoring
