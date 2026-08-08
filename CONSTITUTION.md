# Open Knowledge Studio Constitution

> Engineering principles and architecture invariants for the knowledge base.
> Every contributor must read this before making non-trivial changes.

## Engineering Principles

### P0: Python version requirement

The runtime and connector Python modules require Python >= 3.12.
This is already stated in the project README.  The `from __future__ import
annotations` usage, `str | None` union syntax, `pathlib.Path` features,
and `itertools.batched` (used in tests) all depend on 3.12+ semantics.

### P1: Git IS the migration

The knowledge repo is synced via `git clone/pull`. Schema changes to knowledge
files (frontmatter fields, directory structure) are versioned through the
`_meta/` schema docs and applied on read. There are no database migrations.

### P2: Atomic file writes

All persistent writes use the `mkstemp + fsync + os.replace` pattern.
Directory fsync after replace is required for crash safety.

**Do not** write wiki pages or config with bare `open(path, 'w')`.

### P3: raw/ is human-collected or tool-processed, wiki/ is LLM-written

- `raw/` contains original materials collected by humans OR processed by
  external tools (modality conversion: video→text, audio→text, URL→markdown).
  Tools preserve maximum fidelity — they convert format, not knowledge.
  LLM does not write knowledge to `raw/`.
- `wiki/` contains curated knowledge written by LLM via the Dreaming cycle,
  approved by humans through `drafts/` review.
- `raw/executions/` holds append-only execution traces and `raw/.logs/` holds
  tool- and AI-written digests. Both are provenance — a record of what
  happened, not knowledge. They are **excluded from recall**
  (`recall_episodic` skips both) and are reached only through evidence links on
  a wiki page, so an agent's own output can never be fed back to it as memory.

### P4: CLI core is API-free, external tools may use AI APIs

The AI engine is Claude Code itself — it IS the orchestrator. The CLI core
(`oks`) handles only file system operations and recall scoring — it does
not call AI APIs and does not wrap tool calls.

External tools (Level 1/2) may use AI APIs (vision, STT) independently.
The agent calls these tools directly via Bash; OKS is not in the runtime path.

### P5: OKS provides capability; Agent is the orchestrator

**Core invariant: OKS 提供能力，Agent 负责编排。**

OKS is a capability layer — it installs, configures, routes, and health-checks.
`oks ingest` is the human-readable orchestration entry point: it routes a
source to the correct Level-1 extractor and produces a Raw Bundle, but never
summarizes, grades, or promotes content. Heavy extractors (watch / pdf /
document / formula) remain independent L1 tools that the Agent can also call
directly via Bash.

**Three-level tool protocol:**

| Level | Type | Example | Called by | Output |
|-------|------|---------|-----------|--------|
| 0 | System tool | curl, pdftotext | Agent via Bash | Raw stdout |
| 1 | OKS protocol CLI | oks-connector watch | Agent or `oks ingest` | Raw Bundle |
| 2 | Independent tool | agent-reach, yt-dlp | Agent via Bash | Tool-specific |

**Capability install model:**
Heavy dependencies (faster-whisper, MinerU, PaddleOCR) are opt-in extras.
`oks capability install watch|document|pdf|formula` prompts the user before
downloading. The Agent selects the lowest-cost available capability at runtime
(API → system CLI → install on demand → remote Worker).

**Feishu as optional component:**
`oks feishu setup` auto-creates a Base, capture table, and form. When set up,
the form becomes the daily intake interface with Agent-driven IM review.
Without Feishu, `oks ingest` and the CLI loop work independently.

**Do not** add AI API calls to the CLI core — `oks` handles only file
system operations and recall scoring. External tools (L1/L2) may use AI
APIs independently.

---

## Architecture Invariants

### A1: Four cognitive buckets + two infrastructure layers

The knowledge repo separates **four cognitive buckets** — content the agent
observes, writes, recalls, and forgets — from **two infrastructure layers**
(config + schema) that the agent reads to know how to behave but never writes
as knowledge. Config and schema do not decay and are not recalled by relevance.

| Layer | Dir | Contents | Decay | Access |
|-------|-----|----------|-------|--------|
| Cognitive | `profiles/` | Team/user/project portraits, recipes, goals | None | Direct read (goals influence recall relevance) |
| Cognitive | `raw/` | Original records, date-based by source | None | Keyword + freshness (rglob any structure) |
| Cognitive | `wiki/` | Curated knowledge (from raw via Dreaming) | Type-specific λ | 6+1-factor relevance + curve |
| Cognitive | `drafts/` | Dreaming candidates (raw → wiki intermediate) | None | N/A (human review) |
| Config | `settings/` | Runtime knobs: input-sources.json, raw-tools | None | Direct read |
| Schema | `_meta/` | Data-shape contracts: raw-evidence-schema | None | Applied on read |

`settings/` answers *"what should happen"* (config, changes per deployment);
`_meta/` answers *"what shape is valid"* (schema, versioned, CI-gated). Both
are git-synced (P1) and sit at top level alongside the cognitive buckets, but
neither is "memory" in the cognitive sense — do not treat them as recallable
knowledge.

**Directory structure:**

```
open-knowledge-studio/
├── profiles/                     # ① Portraits
│   ├── team.md
│   ├── users/{id}.md
│   ├── projects/{slug}.md
│   ├── recipes/{slug}.md         # Executable automation recipes
│   └── goals/{slug}.md           # Goals & objectives (influences recall)
├── raw/                          # ② Original records
│   ├── {YYYY}/{MM}/{DD}/
│   │   └── {source}/             # articles | papers | videos | audio | repos | misc
│   │       ├── {slug}.md
│   │       └── {slug}.jsonl
│   └── executions/{run-id}/      # Append-only execution traces
│       ├── events.jsonl
│       └── run.json
├── wiki/                         # ③ Curated knowledge
│   └── {domain}/{type}/{slug}.md  # concepts/ | strategies/ | anti-patterns/
├── drafts/                       # ④ Dreaming candidates
│   └── {slug}.md
├── settings/                     # ⑤ Config layer
│   ├── input-sources.json        # Scheduled intake sources
└── _meta/                        # ⑥ Schema layer
    └── raw-evidence-schema.md    # raw/ evidence shape contract
```

**Infrastructure (not buckets):** `cli/` (the API-free `oks` core),
`templates/`, and `docs/` live at top level but hold code/docs, not knowledge.

**Memory curve scoring** (wiki/):

```
score = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

Type-specific decay λ: concept=0.0 (no decay), strategy=0.014, anti-pattern=0.010.

**Lifecycle:** Provisional → Active (access_count ≥ 3) → Dropped
(archived when score < threshold).

**Memory lifecycle** (Observe → Write → Store → Retrieve → Inject → Forget):

1. **Observe** — sources: conversations, tool results, traces, evals, user feedback.
2. **Decide to write** — only high-confidence, reusable, source-attributed info.
3. **Store** — write to the appropriate bucket by type.
4. **Retrieve** — scope first (workspace → topic → goal → time), then keyword search.
5. **Inject** — layered, stable-first for KV Cache, with source labels.
6. **Update/Forget** — mark stale/superseded, re-score, archive dropped.

**Recall paths** (`recall.py`):

- `recall_episodic()` — searches `raw/` by keyword + freshness, excluding
  `raw/executions/` (provenance, not memory).
- `recall_knowledge()` — scores `wiki/` pages by relevance + curve.
- `recall()` — combines both layers.

### A2: Six-type memory model and injection constraints

The platform's memory system spans six types, each with distinct storage,
recall, scope, and decay:

| Type | Storage | Recall | Decay | Scope |
|------|---------|--------|-------|-------|
| User Memory | `profiles/users/{id}.md` | Direct read | None | `user_id` |
| Project Memory | `profiles/projects/{slug}.md` | Direct read | None | `project_slug` |
| Episodic Memory | `raw/{YYYY}/{MM}/{DD}/{source}/` | Keyword + freshness | None | `source`, `date` |
| Semantic Memory | `wiki/{domain}/{type}/{slug}.md` | 6+1-factor relevance + curve | Type-specific λ | `domain` |
| Procedural Memory | `.claude/skills/{slug}/` | Keyword trigger | None | — |
| Draft Memory | `drafts/{slug}.md` | N/A | None | N/A |

**Bucket mapping:** The six types map to the four cognitive buckets + Claude Code skills
(`settings/` and `_meta/` are infrastructure, not memory types):
- User/Project Memory → `profiles/` (also includes `recipes/` and `goals/`)
- Episodic Memory → `raw/` (date-based: `{YYYY}/{MM}/{DD}/{source}/`)
- Semantic Memory → `wiki/`
- Draft Memory → `drafts/`
- Procedural Memory → `.claude/skills/` (managed by Claude Code)

`raw/executions/` is **not** a memory type: it is provenance, excluded from
recall and reached only through evidence links.

**Recipes** (`profiles/recipes/`): Executable automation patterns with triggers,
steps, tools, and schedules. Not cognitive knowledge (wiki/ strategy) —
recipes are "how to do" playbooks the agent can follow.

**Goals** (`profiles/goals/`): Team/user objectives with status and period.
Active goals influence recall relevance — wiki pages matching an active
goal's domain/keywords receive a relevance boost.

**Injection order** (stable first for KV Cache, mutable last):

1. System Prompt + Bot Identity (stable)
2. Team Profile + North Star (stable, profiles/)
3. Project Memory (stable, profiles/)
4. Tool Schema + Skills (semi-stable, .claude/skills/)
   ─── KV Cache break point ───
5. Recalled Semantic Memory (mutable, per-query, wiki/)
6. Recalled Episodic Memory (mutable, per-query, raw/)
7. User Preferences (mutable, profiles/)

**Source labels:** Injected knowledge must carry a source/confidence tag:
- `[verified]` — tool-confirmed (has traces) or human-reviewed
- `[user-stated]` — user explicitly stated
- `[inferred]` — AI-distilled, not yet verified
- `[stale]` — may be outdated, pending re-verification

**Scope filtering:** Profiles must be filtered before injection:
- User Memory: only the current user's profile
- Project Memory: only the current project's profile
- Episodic: filter by `source` and `date` when available
- Goals: active goals boost recall relevance for matching domains/keywords

**Do not** inject another user's preferences or another project's facts
into the current context.

**Conflict priority** (when memories disagree):
```
current user instruction > tool-verified fact > recent user preference
> older memory > model inference
```

### A3: Dreaming — human-reviewed knowledge evolution

Knowledge evolves through **human-reviewed draft proposals** —
the system never auto-promotes raw content into `wiki/`.

This process is the platform's **Dreaming** — periodic memory
consolidation that distills raw experiences into structured
wiki knowledge, like sleep consolidation in human memory.

**Dream cycle:**

1. **Collect** — traces and discussions accumulate in `raw/`.
2. **AI dream** — scan `raw/` to surface patterns and generate candidates.
3. **Write drafts** — candidate wiki pages written to `drafts/{slug}.md`.
4. **Human review** — accept (promote to `wiki/{domain}/{type}/`), revise, or reject.
5. **Apply decay** — `wiki/` pages re-scored; low-score pages archived.
6. **Git commit** — all changes (wiki pages, drafts) committed.

**Do not** auto-promote raw content to `wiki/` without human review.

### A4: Knowledge evolution and supersession

When new wiki content relates to existing knowledge, four relationships
are tracked. The system never silently overwrites old knowledge.

**Relationship types:**

| Relationship | Meaning | Effect on old page | New page fields |
|--------------|---------|---------------------|-----------------|
| `supersedes` | New page replaces the old one | `status: superseded`, `superseded_by: {slug}`. Excluded from recall. | `relates_to`, `relationship: supersedes` |
| `enriches` | New page adds to the old one | Both stay `active`. `enriched_by: {slug}` added. | `relates_to`, `relationship: enriches` |
| `confirms` | New page validates the old one | `confidence` boosted by +0.1 (max 1.0). `confirmed_by: {slug}` added. | `relates_to`, `relationship: confirms` |
| `challenges` | New page contradicts the old one | `status: stale`, `challenged_by: {slug}`. Still in recall but carries `[stale]` label. | `relates_to`, `relationship: challenges` |

`write_wiki_page()` accepts `relates_to` (slug of existing page) and
`relationship` (`supersedes` | `enriches` | `confirms` | `challenges`).
The `supersedes` parameter is kept for backward compatibility — it's
merged into `relates_to` + `relationship` internally. When set, the old
page's frontmatter is updated before the new page is written.

**Superseded pages** are excluded from recall and `get_top_wiki()` but
retained on disk for audit history. Git history is the safety net, but
explicit `superseded` status is the runtime signal for recall exclusion.

**Challenged pages** remain in recall but carry the `[stale]` source label
so injected knowledge warns the consumer that it may be outdated.

**Do not** overwrite or delete old `wiki/` pages without marking the
relationship first. Every knowledge change must leave a traceable link
to what came before.

### A5: Atomic file writes

All persistent writes use the `mkstemp + fsync + os.replace` pattern.
`store.py`'s atomic write is the reference implementation. Directory
fsync after replace is required for crash safety.

**Do not** write wiki pages or config with bare `open(path, 'w')`.

---

## Revision history

Invariant-level changes must be recorded here so they are traceable without
archaeology through 20k-line diffs.

- **2026-07-31 — P5 reversed** (oks-connector integration): P5 previously
  forbade `oks ingest <input>` internal dispatch and in-CLI modality
  detection. It now defines `oks ingest` as the orchestration entry point
  routing to Level-1 extractors. Rationale: suffix-based routing is format
  dispatch, not knowledge judgment; the surviving invariant is that ingest
  **never summarizes, grades, or promotes**, and L1 extractors remain
  directly callable by the Agent. Accepted by the maintainer during review
  of the connector merge.
- **2026-07-31 — traces defined as provenance** (P3/A1): `raw/executions/`
  registered in A1; traces excluded from recall and reachable only through
  wiki evidence links.
- **2026-07-31 — A2 scope filtering enforced in code**: `recall_episodic`
  previously walked all of `profiles/`, returning other users' and other
  projects' profiles at the highest weight. Private profiles are now opt-in
  via `--user` / `--project` (`OKS_USER` / `OKS_PROJECT`); unnamed identities
  are excluded rather than leaked.
- **2026-07-31 — P3 exclusion widened to `raw/.logs/`**: AI-written digests
  were being recalled as if they were human-collected material. `raw/.logs/`
  now joins `raw/executions/` outside recall.
- **2026-07-31 — A4 relationships reachable**: `promote_draft` dropped
  `relates_to` / `relationship`, so no production path could mark a page
  superseded. Promotion now carries them through.
