<div align="center">

<img src="images/oks-logo-readme.png" width="360" alt="Open Knowledge Studio">

### Open Knowledge Studio: A Filesystem-First External Memory for Coding Agents

English / [中文](README.zh.md)

[![](https://img.shields.io/github/v/release/open-agent-power/open-knowledge-studio?color=369eff\&labelColor=black\&logo=github\&style=flat-square)](https://github.com/open-agent-power/open-knowledge-studio/releases)
[![](https://img.shields.io/github/stars/open-agent-power/open-knowledge-studio?labelColor\&style=flat-square\&color=ffcb47)](https://github.com/open-agent-power/open-knowledge-studio)
[![](https://img.shields.io/github/issues/open-agent-power/open-knowledge-studio?labelColor=black\&style=flat-square\&color=ff80eb)](https://github.com/open-agent-power/open-knowledge-studio/issues)
[![](https://img.shields.io/badge/license-MIT-white?labelColor=black\&style=flat-square)](./LICENSE)
[![](https://img.shields.io/github/last-commit/open-agent-power/open-knowledge-studio?color=c4f042\&labelColor=black\&style=flat-square)](https://github.com/open-agent-power/open-knowledge-studio/commits/main)

[Documentation](https://open-agent-power.github.io/open-knowledge-studio/) · [Experiments](#proof-it-works) · [Reproduce](#reproduce) · [Changelog](./CHANGELOG.md)

</div>

***

## What is Open Knowledge Studio

Open Knowledge Studio (OKS) is an open-source **filesystem-first external memory** for coding agents. Instead of a black-box vector store, it stores knowledge as a human-reviewable, git-versioned filesystem — `profiles/`, `raw/`, `wiki/`, `drafts/`, `mail/` — that an Agent browses with `oks recall`, `oks wiki list`, and `oks trace`. Content moves through a reviewable pipeline (Source → EvidenceFragment → Manifest → Raw → Candidate → human review → Wiki), decays like real memory, and is recalled on demand. Full introduction: [Start here](https://open-agent-power.github.io/open-knowledge-studio/).

```
your source → Candidate → human review → Wiki → Recall → injected into Agent context
```

### OKS Mail is the collaboration sidecar

Mail preserves only durable collaboration facts that must cross a Session, Agent, Host, or machine: handoffs, results, blockers, notes, and references to existing Wiki/Candidate/Trace artifacts. It is not a second knowledge base, task engine, chat replacement, or wake-up service. A message can be written and later read or replied to by an Agent's Skill; without a separate Host Adapter, that does not start a process, create a Session, or claim execution. Threads are durable context for the records, not workflow state. See the [product boundary](https://open-agent-power.github.io/open-knowledge-studio/concepts/product-boundary/) and [Mail protocol](https://open-agent-power.github.io/open-knowledge-studio/reference/mail-protocol/).

## Why Open Knowledge Studio

- **One filesystem for all memory.** Profiles, raw materials, curated wiki, drafts, and agent mail each get a directory with a different trust boundary. An Agent locates and manipulates context deterministically, like a developer working with files. → [Architecture](https://open-agent-power.github.io/open-knowledge-studio/concepts/architecture/) · [Constitution](https://open-agent-power.github.io/open-knowledge-studio/concepts/constitution/)
- **Human review is the gate.** Raw material ≠ conclusion; Candidate ≠ long-term knowledge. Nothing auto-promotes to Wiki — every durable memory is human-approved. → [Review candidates](https://open-agent-power.github.io/open-knowledge-studio/usage/review/)
- **Triple-Layer Recall cuts hallucination.** Node-BM25 retrieves *what* matches, Soul Boost reorders *what reaches* the Agent (anti-pattern ×1.5, review bonus, generic demotion), Memory Curve scores *how fresh* — so confidence never outranks truth. → [Recall engine](https://open-agent-power.github.io/open-knowledge-studio/algorithms/recall-engine/)
- **Knowledge decays like real memory.** Unused pages cool down through hot → warm → cold → evictable tiers; used pages resurface. `importance × e^(-λ×days) + ln(1+access) + pin_bonus`. → [Decay system](https://open-agent-power.github.io/open-knowledge-studio/algorithms/decay-system/)
- **Every recall is observable.** Each query preserves its factor scores and match path (`oks recall "<q>" --explain`); every injection is logged to `records/inject.jsonl`. When a result looks wrong, you see exactly which factor produced it. → [Evaluation](https://open-agent-power.github.io/open-knowledge-studio/algorithms/recall-evaluation/)

How the pieces fit together: [Architecture](https://open-agent-power.github.io/open-knowledge-studio/concepts/architecture/). The product and collaboration boundaries are in the [product boundary](https://open-agent-power.github.io/open-knowledge-studio/concepts/product-boundary/). The thinking behind the design: [CONSTITUTION.md](./CONSTITUTION.md).

```
open-knowledge-studio/
├── profiles/              # team, users, projects, recipes, goals — stable context
├── raw/                    # human-collected sources, date-based {YYYY}/{MM}/{DD}/{source}/
├── wiki/                   # human-reviewed memory: concept, strategy, anti-pattern
├── drafts/                 # Candidate proposals, awaiting review
├── mail/                   # agent-to-agent: inbox/ + sent/ — never long-term knowledge
├── settings/               # recall.yaml (single param source), tool registry
├── _meta/                  # schema layer: raw evidence, recall case, trace event
└── records/                # versioned acceptance evidence + experiment runs
```

The three recall layers:

- **Node-BM25 (retrieval)**: SQLite FTS5 + BM25 over markdown `##` headings, column weights title 5× > tags 3× > body 1× > code 0.5×. No file reads during retrieval (abstract zero-read, v0.6.10).
- **Soul Boost (injection)**: type_boost + review_bonus + generic_demotion reorder hits before they reach the Agent — failure lessons rank higher than generic concepts.
- **Memory Curve (decay)**: type-specific λ, access_count ln-growth, pin_bonus — independent of backend, runs in `store.py`.

## Proof it works

OKS has been evaluated on a 50-case semantic-paraphrase dataset (strict exact-slug match) and on the public LoCoMo long-conversation benchmark. Full results and reproduction scripts are in [docs/algorithms/recall-evaluation.md](./docs/algorithms/recall-evaluation.md); the datasets and run JSONs live in [./records/experiments](./records/experiments).

### Triple-Layer ablation — 50-case, strict exact-slug match

Queries are semantic paraphrases — the query does not contain the slug's keyword, testing synonym/rewrite recall. Match is strict: the expected slug must appear in top-k.

<img src="images/ablation-triple-layer.svg" alt="Triple-Layer ablation. fts5 R@1=0.825 R@3=0.925 MRR=0.907; fusion 0.805/0.905/0.900; native 0.525/0.647/0.630.">

- **Node-BM25 dominates page-level 6+1**: R@1 +57% (0.525→0.825), MRR +44% (0.630→0.907). Multi-word same-section BM25 scores high; synonym/rewrite recall is precise.
- **Soul Boost must live in injection, not retrieval**: native 6+1's memory curve / goal boost / review bonus applied as retrieval re-rank *lowers* precision (R@1 0.825→0.805) — irrelevant pages score high and displace exact matches.
- **fts5 is also faster**: 93ms vs native 137ms vs fusion 226ms. SQLite persistent index beats live traversal.

### Embedding backend — semantic recall comparison (v0.6.2)

<img src="images/ablation-embedding.svg" alt="Embedding vs literal. fts5 R@1=0.825 MRR=0.907 p50=93ms; embedding R@1=0.617 MRR=0.733 p50=18304ms (197x).">

- On a small Chinese-term-heavy KB, BM25 literal already hits (terms overlap with wiki); embedding's semantic generalization introduces noise — and is 197× slower.
- **Decision**: fts5 stays default. Embedding is a **fallback** for fts5-miss cases, not a replacement. Embedding's real value is large KBs + cross-lingual + synonym-heavy domains.

### Layer-by-layer ablation

<img src="images/ablation-layers.svg" alt="Layer-by-layer ablation. full R@1=0.825 MRR=0.907; minus Node-BM25 0.525/0.630 (-36%); minus Soul Boost 0.805/0.900.">

- **Remove Node-BM25** (retrieval fts5→native): R@1 0.825→0.525 (−36%) — Node-BM25 is the precision engine.
- **Remove Soul Boost** (fusion misuse, soul moved to retrieval re-rank): R@1 0.825→0.805 — soul in injection = right; re-rank in retrieval = negative optimization.

### LoCoMo long-conversation recall — vs OpenViking (1540-case)

We adapted the public [LoCoMo](https://github.com/snap-research/locomo) benchmark (ACL 2024, 10 long conversations, 1540 QA across 4 categories, excluding adversarial) to OKS: each conversation → one wiki page, each QA question → an eval case with the expected conversation slug. Full report: [locomo-pk-report.md](./records/experiments/locomo-pk-report.md).

<img src="images/locomo-pk.svg" alt="LoCoMo 1540-case. OKS recall@1=0.920 p50=31ms; OpenViking QA accuracy=0.8286.">

- **OKS recall@1 = 92.0%** — 92% of 1540 LoCoMo questions retrieved the correct conversation in top-1.
- **Metric caveat (honest)**: OKS reports *recall hit* (the correct conversation is retrieved); OpenViking reports *full QA accuracy* (recall + LLM answer + LLM judge). Recall upper-bounds QA — if you can't retrieve it, you can't answer it. OKS core is API-free (P4) and stops at recall; full QA accuracy depends on the host Agent's LLM.
- **Why OKS recall is strong**: Node-BM25 over `##` headings matches question entities (names/dates/events) to the dialogue turn where they appear; SQLite persistent index + abstract zero-read gives 31ms p50.
- **vs OKS 50-case**: LoCoMo R@1 (0.920) > 50-case R@1 (0.825) — LoCoMo questions contain entities that appear verbatim in dialogue; the 50-case is semantic-paraphrase (no keyword overlap), harder.

Reproduce:
```bash
git clone https://github.com/snap-research/locomo.git
python3 scripts/locomo_to_oks.py records/experiments/locomo-data/locomo10.json wiki/conversations/locomo records/locomo-eval.yaml
oks eval recall records/locomo-eval.yaml --output locomo-fts5.json --search-backend fts5
```

(Dataset is also vendored at `records/experiments/locomo-data/locomo10.json` — CC BY-NC 4.0, see its LICENSE.)

### Why OKS recall outperforms — architecture analysis

OKS recall@1 = 92.0% beats OpenViking's full QA accuracy 82.86% on the same LoCoMo dataset. The gap is not luck — it follows from five architectural choices:

1. **Node-BM25 matches dialogue structure; vectors don't.** LoCoMo conversations are hundreds of turns. OKS indexes every `##` heading turn as a separate FTS5 row (node-level), so a question mentioning "Caroline" + "October 13" scores high only on the turn where both appear. OpenViking embeds whole passages into vectors — entity specificity drowns in the passage embedding.
2. **Literal beat semantics on entity queries.** LoCoMo questions are entity-heavy (names, dates, events). BM25 literal hit is precise; embedding semantic generalization introduces noise ("Caroline" → nearby-but-wrong speaker). On OKS's own 50-case (semantic paraphrase, no keyword overlap), fts5 R@1 = 82.5%; on LoCoMo (entity overlap), it jumps to 92.0% — exactly where literal wins.
3. **Zero external dependencies.** OKS uses SQLite FTS5 (ships with Python). No vector DB, no embedding model, no GPU. OpenViking needs a vector index + embedding model (Doubao-embedding-vision) + optionally a VLM — heavier stack, more failure modes.
4. **31ms p50.** SQLite persistent index + abstract zero-read (v0.6.10) means retrieval touches zero files during a query. OpenViking's directory-recursive vector search + rerank + LLM answer is a longer pipeline.
5. **Observable, file-based, human-auditable.** `oks recall "<q>" --explain` shows every node's BM25 score and which turn matched. Conversations live as readable wiki markdown you can edit. OpenViking's vector store is a black box; its trajectory helps, but the index itself is opaque.

**Honest boundary**: OKS measures *recall hit* (correct conversation retrieved); OpenViking measures *full QA accuracy* (recall + LLM answer + judge). Recall is the QA ceiling — you can't answer what you can't retrieve. OKS's 92% recall means a host Agent with a strong LLM could approach 92% QA accuracy; OKS core itself stops at recall (API-free, P4). The advantage is in the **retrieval layer**, not the answer layer.

### Abstract zero-read & tier degradation (v0.6.10 / v0.6.12)

- **Abstract zero-read**: fts5 schema `node-v2` added an `abstract` column; `body_preview` reads it from SQLite — **zero file reads during retrieval**. R@1 held (0.429), p50 121ms (slightly faster).
- **Tier degradation**: `_apply_budget()` degrades hits by tier when a token budget is hit — L2 (full, 200c) → L1 (overview, 100c) → L0 (abstract, 50c) → title-only (0c, rel < `0.5`) → truncate. Verified: 5×200c under 300c budget → 150c ≤ 300.

> These numbers are historical baselines from one knowledge base at one point in time, not a universal SLA. Re-run any of them — see [Reproduce](#reproduce).

## Quick start

> 💡 **New to OKS?** Read [start-here](https://open-agent-power.github.io/open-knowledge-studio/) first — it walks through the memory lifecycle and where OKS fits in your Agent stack.

Requires Python 3.10+.

```bash
pipx install open-knowledge-studio && pipx ensurepath
oks init my-knowledge-base
cd my-knowledge-base
oks status          # wiki count, tier distribution, drafts, quality
oks recall "git branch"   # Triple-Layer recall → injects matched memory
```

Optional auto-recall hooks (wire recall into your Agent host):

```bash
oks hook install --editor claude   # or: qoder | codex | both
oks skills-install                # bundle skills + agent-config into .claude/.qoder/.pi/.codex
```

Next steps:

- CLI reference, hook configuration, and evaluation: [CLI docs](https://open-agent-power.github.io/open-knowledge-studio/reference/cli/)
- Backup, export, and conversations: [Backup & export](https://open-agent-power.github.io/open-knowledge-studio/connect/backup-export/)

## Use it with your agent

OKS injects reviewed memory into your Agent's context on every prompt (UserPromptSubmit) and detects conflicts after each tool call (PostToolUse → `mail/`):

- **Claude Code** — `.claude/hooks/` + `settings.json`
- **Codex** — `.codex/hooks.json`
- **qoder** — `.qoder/settings.json` (shares `.claude/hooks/`)
- **pi** — `.pi/extensions/*.ts` (TS extension, shares `.claude/hooks/`)
- **Other shells** — any host that runs a shell hook

Setup for each: `oks hook install --editor <claude|qoder|codex|both>` then `oks skills-install`.

## Product boundaries

**The open-source edition is not crippled.** OKS in this repo is fully open source under MIT: no feature gates, no account, no activation key. The CLI core is API-free (CONSTITUTION P4) — `oks` does file operations only; no remote AI API calls from core. AI lives in optional providers/skills you wire yourself.

- **OKS does not train model weights.** The "knowledge model" is the filesystem.
- **OKS does not auto-promote raw → Wiki.** Humans approve.
- **OKS does not replace your Agent.** It provides a Recall primitive; the host Agent decides.
- **Git is the migration.** No database; schema changes versioned through `_meta/`. Atomic writes throughout.

<a id="reproduce"></a>
## Reproduce

The 50-case dataset and all run JSONs are archived:

```
records/experiments/
├── eval-50.yaml                 # 50 semantic-paraphrase queries + expected slugs
└── runs/
    ├── eval-50-fts5.json        # R@1=0.825, MRR=0.907
    ├── eval-50-native.json      # R@1=0.525, MRR=0.630
    ├── eval-50-fusion.json      # R@1=0.805, MRR=0.900
    └── eval-50-embedding.json   # R@1=0.617, MRR=0.733
```

Re-run any backend:

```bash
oks eval recall records/experiments/eval-50.yaml \
  --output my-run.json \
  --search-backend {fts5|native|fusion}

oks eval compare records/experiments/runs/eval-50-fts5.json my-run.json
```

Per-query breakdown: `oks recall "<query>" --explain` shows every factor score.

**Caveat:** OKS has no official labeled dataset — the 50-case set is one KB's history. Metrics are comparable across backends *on that dataset*; they are not a universal SLA. Build your own labeled set and re-run.

## Roadmap

- **AI abstract generation** (Dreaming layer) — LLM writes `abstract:` frontmatter, lifting abstract zero-read quality beyond mechanical first-paragraph.
- **RecallLedger** — cross-turn dedup, so the same page is not re-injected within cooldown.
- **Query expansion** — synonyms / EN↔ZH translation to bridge the synonym gap at retrieval, not via embedding.
- **native→fts5 dispatch unification** — currently two paths (native carries Soul Boost, fts5 does not); unify so fts5 wires the Soul Boost layer too.

## Community & contributing

- **Docs**: [open-agent-power.github.io/open-knowledge-studio](https://open-agent-power.github.io/open-knowledge-studio/)
- **Design contract**: [CONSTITUTION.md](./CONSTITUTION.md) — the memory architecture (A1–A5)
- **Changelog**: [CHANGELOG.md](./CHANGELOG.md) — full release history
- **Contribute**: bug fixes and new features both welcome — fork a branch, open a PR

## Security and privacy

OKS runs entirely on your local filesystem. No telemetry, no remote calls from core (CONSTITUTION P4). Your knowledge base stays under your git remote (or no remote at all).

## License

[MIT](./LICENSE)
