# Open Knowledge Studio

> File-based knowledge engineering for Claude Code — **raw → wiki → recall**

## What is this?

Open Knowledge Studio provides a standalone knowledge engineering repository with:

- **Five-bucket architecture** — profiles, raw, wiki, drafts, settings
- **6-factor recall engine** — token overlap + substring + topic trace + type boost + review penalty + memory curve
- **Dreaming cycle** — raw → AI distill → drafts → human review → wiki
- **Decay system** — type-specific memory curve fading
- **22 pre-built domains**

## Core Pipeline

```
raw/ → drafts/ → wiki/ → recall
```

## Documentation

- [Architecture](architecture.md) — Five-bucket structure + memory lifecycle
- [Recall Engine](recall-engine.md) — 6-factor scoring algorithm
- [Memory Model](memory-model.md) — Six memory types + injection order
- [Dreaming Cycle](dreaming-cycle.md) — Knowledge evolution pipeline
- [Decay System](decay-system.md) — Memory curve + tier classification
- [Frontmatter Schema](frontmatter-schema.md) — YAML metadata specification

## Quick Start

```bash
git clone <repo-url>
cd open-knowledge-studio
./setup.sh
oks search "your query"
```

## Philosophy

Knowledge is a **living system**: collect → distill → review → connect → decay → recall.
