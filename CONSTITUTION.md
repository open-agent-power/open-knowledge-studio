# Open Knowledge Studio Constitution

> Engineering principles and architecture invariants for the knowledge base.
> Every contributor must read this before making non-trivial changes.

## Engineering Principles

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

### P4: CLI core is API-free, external tools may use AI APIs

The AI engine is Claude Code itself — it IS the orchestrator. The CLI core
(`oks`) handles only file system operations and recall scoring — it does
not call AI APIs and does not wrap tool calls.

External tools (Level 1/2) may use AI APIs (vision, STT) independently.
The agent calls these tools directly via Bash; OKS is not in the runtime path.

### P5: Agent-direct intake — three-level tool protocol

The intake pipeline is orchestrated by Claude Code itself, not by OKS.
OKS is a capability layer: it provides the routing table
(`settings/handlers.json`) and gets out of the way.

**Three-level tool protocol:**

| Level | Type | Example | Called by | Output |
|-------|------|---------|-----------|--------|
| 0 | System tool | curl, pdftotext | Agent via Bash | Raw stdout |
| 1 | OKS protocol CLI | oks-video | Agent via Bash | JSON to stdout |
| 2 | Independent tool | agent-reach, yt-dlp | Agent via Bash | Tool-specific |

**Level 1 JSON output protocol:**
```json
{"markdown": "...", "title": "...", "source": "...", "modality": "...", "metadata": {}}
```

Tools are registered in `settings/handlers.json` with `level`, `check_cmd`,
`install_hint`, `raw_subdir` fields. The agent checks availability by
running `check_cmd` via Bash — no CLI doctor command needed.

**Do not** build a runtime wrapper. The agent calls tools directly.

---

## Architecture Invariants

### A1: Five-bucket memory architecture

The knowledge base has **five buckets**. Each bucket has a clear purpose
and recall strategy.

| Bucket | Purpose | Decay | Recall |
|--------|---------|-------|--------|
| `profiles/` | Team/user/project portraits | None | Direct read |
| `raw/` | Original records (articles, papers, traces) | None | Keyword + freshness |
| `wiki/` | Curated knowledge (from raw via Dreaming) | Type-specific λ | 6-factor relevance + curve |
| `drafts/` | Dreaming candidates (raw → wiki intermediate) | None | N/A (human review) |
| `settings/` | System infrastructure (decay-config, input-sources) | None | Direct read |

**Directory structure:**

```
open-knowledge-studio/
├── profiles/                     # ① Portraits
│   ├── team.md
│   ├── users/{id}.md
│   └── projects/{slug}.md
├── raw/                          # ② Original records
│   └── {YYYY}/{MM}/{DD}/
│       └── {topic_id}/
│           ├── conversation.jsonl
│           └── summary.md
├── wiki/                         # ③ Curated knowledge
│   └── {domain}/{type}/{slug}.md  # concept | strategy | anti-pattern
├── drafts/                       # ④ Dreaming candidates
│   └── {slug}.md
└── settings/                     # ⑤ System config
    ├── decay-config.yaml
    └── input-sources.json
```

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

- `recall_episodic()` — searches `raw/` by keyword + freshness.
- `recall_knowledge()` — scores `wiki/` pages by relevance + curve.
- `recall()` — combines both layers.

### A2: Six-type memory model and injection constraints

The platform's memory system spans six types, each with distinct storage,
recall, scope, and decay:

| Type | Storage | Recall | Decay | Scope |
|------|---------|--------|-------|-------|
| User Memory | `profiles/users/{id}.md` | Direct read | None | `user_id` |
| Project Memory | `profiles/projects/{slug}.md` | Direct read | None | `project_slug` |
| Episodic Memory | `raw/{date}/{topic}/conversation.jsonl` | Keyword + freshness | None | `topic_id` |
| Semantic Memory | `wiki/{domain}/{type}/{slug}.md` | 6-factor relevance + curve | Type-specific λ | `domain` |
| Procedural Memory | `.claude/skills/{slug}/` | Keyword trigger | None | — |
| Draft Memory | `drafts/{slug}.md` | N/A | None | N/A |

**Bucket mapping:** The six types map to five buckets + Claude Code skills:
- User/Project Memory → `profiles/`
- Episodic Memory → `raw/`
- Semantic Memory → `wiki/`
- Draft Memory → `drafts/`
- Procedural Memory → `.claude/skills/` (managed by Claude Code)

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
- Episodic: filter by `topic_id` when available

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

| Relationship | Meaning | Effect on old page |
|--------------|---------|---------------------|
| `supersedes` | New page replaces the old one | Marked `status: superseded` with `superseded_by` field. Excluded from recall. Retained on disk for audit history. |
| `enriches` | New page adds to the old one | Both stay `active`. New page linked via `enriches` field. |
| `confirms` | New page validates the old one | Old page `confidence` boosted by +0.1 (max 1.0). New page linked via `confirms` field. |
| `challenges` | New page contradicts the old one | Old page marked `[stale]` source label, flagged for review. New page linked via `challenges` field. |

`write_wiki_page()` accepts a `relates_to` parameter (slug of the existing
page) and a `relationship` parameter (`supersedes` | `enriches` | `confirms` |
`challenges`). When set, the old page's frontmatter is updated before the new
page is written.

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
