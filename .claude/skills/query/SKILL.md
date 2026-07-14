---
description: Search knowledge via 6-factor recall engine, answer with citations
---

# /query — Knowledge Recall & Answer

## Purpose

Use the 6-factor recall engine to find relevant wiki pages and episodic memory, then answer with citations.

## Steps

1. **Run recall** — Execute `oks recall "<user question>" --limit 5`
2. **Parse results** — Extract wiki pages (semantic) and raw/profile matches (episodic)
3. **Generate source labels** — For each recalled wiki page, determine label dynamically:

   | Condition | Label | Meaning |
   |-----------|-------|---------|
   | `status == "stale"` | `[stale]` | Challenged by newer knowledge, may be outdated |
   | `has_traces == true` | `[verified]` | Tool-confirmed (has trace evidence) |
   | `confidence < 0.5` | `[inferred]` | AI-distilled, low confidence, not yet verified |
   | `status == "provisional"` | `[inferred]` | Not yet promoted to active (access_count < 3) |
   | Otherwise | `[verified]` | Human-reviewed active knowledge |

   Priority: stale > verified (traces) > inferred (low confidence) > inferred (provisional) > verified (active)

4. **Inject context** — Load recalled content with generated source labels.
   If a page has `relates_to`/`relationship` fields, note the relationship
   (e.g., "this page enriches {slug}" or "this page challenges {slug}").
5. **Answer** — Synthesize answer using recalled knowledge. Cite sources by slug.
6. **Record access** — Mention which wiki pages were used

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
