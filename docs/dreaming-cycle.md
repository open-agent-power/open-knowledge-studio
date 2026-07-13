# Dreaming Cycle

Knowledge evolves through **human-reviewed draft proposals** — the system never auto-promotes raw content to wiki.

## Dream Cycle

```
Collect → AI Dream → Write Drafts → Human Review → Promote → Decay → Evolve → Commit
```

### 1. Collect
Traces, conversations, articles accumulate in `raw/`.

### 2. AI Dream
Claude Code `/ingest` skill scans `raw/`, identifies patterns, generates candidates.

### 3. Write Drafts
Candidates → `drafts/{slug}.md` with draft frontmatter.

### 4. Human Review
`/promote` skill: accept → wiki/, revise, or reject.

### 5. Promote
`oks drafts promote <slug>` moves draft to `wiki/{domain}/{type}/`.

### 6. Apply Decay
`oks distill` re-scores all wiki pages. Below threshold → `status: dropped`.

### 7. Evolve
`evolve_knowledge()` — 3+ pages with same tag + score > 0.5 → merged draft proposal.

### 8. Git Commit
`oks sync` commits all changes.

## Core Invariant

**Never auto-promote raw to wiki without human review** (CONSTITUTION.md A3).

## Implementation

- `/ingest` — AI triage
- `oks distill` — decay + evolve
- `/promote` — human review
- `cli/knowledge_studio/distiller.py`
