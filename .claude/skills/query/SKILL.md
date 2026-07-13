---
description: Search knowledge via 6-factor recall engine, answer with citations
---

# /query — Knowledge Recall & Answer

## Purpose

Use the 6-factor recall engine to find relevant wiki pages and episodic memory, then answer with citations.

## Steps

1. **Run recall** — Execute `oks recall "<user question>" --limit 5`
2. **Parse results** — Extract wiki pages (semantic) and raw/profile matches (episodic)
3. **Inject context** — Load recalled content with source labels: `[verified]`, `[inferred]`, `[stale]`
4. **Answer** — Synthesize answer using recalled knowledge. Cite sources by slug.
5. **Record access** — Mention which wiki pages were used

## Recall Factors

| Factor | Weight |
|--------|--------|
| Token overlap (jieba) | ×0.3 |
| Substring match | +1.0 title / +0.5 body |
| Topic trace | +2.0 |
| Type boost | 1.5/0.8/0.6 (anti-pattern/strategy/concept) |
| Review penalty | +2.0 false / +1.0 failure |
| Memory curve | ×0.5 |

## Conflict Priority

current user instruction > tool-verified > recent preference > older memory > model inference
