# Open Knowledge Studio

> Your AI tools do not remember your work for you. Open Knowledge Studio does.

It is your memory layer for AI work. Save a decision, an insight, a useful source, or a conversation. Studio makes it searchable, connects it to what you already know, and lets Claude Code start from the same context.

You do not need to wire everything at once. Save one thing, find it again, then let Claude Code use it. Once that loop works, Studio becomes much easier to understand.

The shortest path is:

1. [Set up the repo](start-here.md)
2. [Save your first knowledge](memories.md)
3. [Connect Claude Code](start-here.md#connect-claude-code)
4. [Verify recall is working](start-here.md#definition-of-done)

## Core Pipeline

```
raw/ (human-collected materials)
  ↓ /ingest — AI triage
drafts/ (intermediate proposals)
  ↓ /promote — human review
wiki/ (curated knowledge, with decay)
  ↓ oks search / /query — 6-factor recall
injected into Claude Code context
```

## What Studio Does

| Feature | Description |
|---------|-------------|
| **[Start Here](start-here.md)** | The shortest useful path: save one memory, search it, verify it works |
| **[Memories](memories.md)** | Wiki page anatomy, types, creation paths, and search modes |
| **[Raw Materials](threads.md)** | Raw intake, A/B/C grading, distillation workflow, and import paths |
| **[Architecture](architecture.md)** | Five-bucket structure + memory lifecycle (Observe→Write→Store→Retrieve→Inject→Forget) |
| **[Recall Engine](recall-engine.md)** | 6-factor scoring: token overlap, substring, topic trace, type boost, review penalty, memory curve |
| **[Memory Model](memory-model.md)** | Six memory types, injection order (stable-first), source labels, conflict priority |
| **[Dreaming Cycle](dreaming-cycle.md)** | Knowledge evolution: collect → dream → drafts → review → promote → decay → evolve |
| **[Decay System](decay-system.md)** | Memory curve fading, type-specific λ, tier classification (hot/warm/cold/evictable) |
| **[Frontmatter Schema](frontmatter-schema.md)** | YAML metadata specification v0.7 |

## Quick Start

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "your query"
```

## Philosophy

- **Raw Material vs Memory** — raw/ has typed intake (4 subdirs), A/B/C grading, and fingerprint dedup; wiki/ has 22-domain structure, decay tiers, and Crystal synthesis. Distill when the pattern matters, not every time.
- **Human-gated** — the system never auto-promotes raw content to wiki without your review.
- **Knowledge as Code** — all knowledge lives in Markdown + YAML frontmatter, versioned through Git.
- **Decay is a feature** — knowledge fades over time. Well-used knowledge stays sharp; forgotten knowledge fades to archive.
- **Do less on day one** — save one memory, run one search, verify it works. Don't wire everything at once.
