# Open Knowledge Studio

> A knowledge engineering workspace for Claude Code — raw → wiki → recall.

## What is this?

Open Knowledge Studio is a file-based knowledge base system designed for use with Claude Code. It provides:

- **5-bucket architecture**: profiles/ (incl. recipes, goals), raw/, wiki/, drafts/, settings/
- **Three-level tool protocol**: agent-direct intake (L0 system tools, L1 OKS protocol CLIs, L2 independent tools)
- **6+1-factor recall engine**: token overlap + substring + topic trace + type boost + review penalty + memory curve + optional goal boost (active goals lift on-scope pages; no-op without goals)
- **4 knowledge relationships**: supersedes, enriches, confirms, challenges (CONSTITUTION A4)
- **Recipes & goals**: executable automation recipes + goal-aware recall boosting
- **Dreaming cycle**: raw → AI distill → drafts → human review → wiki
- **Decay system**: memory curve scoring with type-specific λ, tier classification (hot/warm/cold/evictable)
- **Date-based raw/**: `raw/{YYYY}/{MM}/{DD}/{source}/` — auto-organized by intake date + source category
- **Global config**: `~/.oks/config.json` enables cross-project access from any directory
- **CLI tool (`oks`)**: search, recall, wiki CRUD (incl. `wiki use` — the explicit usage signal), drafts, distill, lint, status, metrics, sync, config

## Raw Material vs Memory — The Core Distinction

| | Raw Material (raw/) | Memory (wiki/) |
|---|---|---|
| **What** | Original article, paper, repo note, or conversation | Durable takeaway, distilled and curated |
| **Who writes** | Human collects, LLM reads only | LLM writes via Dreaming, human approves |
| **Decay** | None | Type-specific λ |
| **Recall** | Keyword + freshness | 6+1-factor relevance + memory curve |
| **Advantage** | Date-based ({YYYY}/{MM}/{DD}/{source}/), A/B/C grading, fingerprint dedup | 22-domain structure, decay tiers, 4 relationships |

A strong workflow: save the source into `raw/`, then distill the parts worth keeping into `wiki/` memories.

## Quick Start

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "git branch"
```

## Core Pipeline

```
raw/ (human-collected or tool-processed materials)
  ↓ /ingest skill — 3-level routing → raw/, then AI triage A/B/C grade
drafts/ (intermediate proposals)
  ↓ /promote skill — human review
wiki/ (curated knowledge, with decay)
  ↓ oks search / /query skill — 6+1-factor recall
injected into Claude Code context
```

## Memory Architecture

See `CONSTITUTION.md` for the full memory design (A1-A5):

- **A1**: Four cognitive buckets (profiles/raw/wiki/drafts) + two infrastructure layers (settings=config, _meta=schema) + memory lifecycle (Observe→Write→Store→Retrieve→Inject→Forget)
- **A2**: Six-type memory model + injection order + source labels + conflict priority
- **A3**: Dreaming — human-reviewed knowledge evolution
- **A4**: Knowledge evolution — supersedes, enriches, confirms, challenges
- **A5**: Atomic file writes

## Directory Structure

```
open-knowledge-studio/
├── .claude/          # Claude Code skills (8) + hooks (3) + rules (2)
├── profiles/         # ① Portraits — team, users, projects, recipes, goals
├── raw/              # ② Raw materials — date-based: {YYYY}/{MM}/{DD}/{source}/
├── wiki/             # ③ Curated knowledge — 22 domains × 3 types
├── drafts/           # ④ Dreaming candidates
├── settings/         # ⑤ Config layer — decay, tool registry, input sources
├── _meta/            # ⑥ Schema layer — frontmatter/learning contracts (CI-enforced)
├── templates/        # concept, strategy, anti-pattern, draft
├── cli/              # Python CLI tool (oks) — API-free core
├── scripts/          # Repo maintenance/bootstrap helpers (not L1 tools)
├── docs/             # GitHub Pages design documentation
├── CONSTITUTION.md   # Memory architecture design
├── CLAUDE.md         # This file
└── setup.sh          # One-command setup
```

## Claude Code Skills

| Skill | Purpose |
|-------|---------|
| `/start` | First-time setup: choose domain, build structure, scan raw/ |
| `/ingest` | Multi-modal intake: 3-level routing → raw/, then A/B/C triage → drafts/ |
| `/query` | 6-factor recall → inject into context → AI answers with citations |
| `/lint` | Scan wiki/: frontmatter, orphans, broken links, stale |
| `/compile` | Re-compile concept pages from sources → drafts/ |
| `/status` | Overview: wiki count, tier distribution, drafts, quality |
| `/archive` | Extract conversation Q&A → AI summarize → wiki/queries/ |
| `/promote` | Review drafts/ → promote/reject/edit |

## CLI Commands

```bash
oks search <query> [--limit 5] [--domain computing] [--type strategy]
oks recall <query> [--topic-id ID] [--limit 5]
oks wiki list [--domain] [--type] [--status active]
oks wiki get <slug>
oks wiki create --title "..." --type concept --area computing --importance 0.7
oks wiki pin <slug> | archive <slug>
oks wiki use <slug>   # explicit "this page was used" signal (search/recall are read-only)
oks drafts list | promote <slug> | reject <slug>
oks distill [--dry-run]
oks lint | status | metrics | decay
oks sync [--pull]
oks config init | show | set <key> <value>
```

## Conventions

- **raw/** is human-collected or tool-processed. Tools preserve maximum fidelity — they convert format, not knowledge. LLM does not write knowledge to raw/.
- **wiki/** is LLM-written, human-approved via drafts/ review.
- **Intake is agent-direct** — OKS does not wrap tool calls. Agent checks tool availability via Bash (`which curl`, etc.).
- **Global config** (`~/.oks/config.json`) enables cross-project access — `oks recall` works from any directory.
- **Git IS the migration** — no database, schema changes versioned through _meta/.
- **Atomic writes** — all persistent writes use mkstemp + fsync + os.replace.
- **Never auto-promote** raw content to wiki/ without human review.
