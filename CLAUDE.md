# Open Knowledge Studio

> A knowledge engineering workspace for Claude Code — raw → wiki → recall.

## What is this?

Open Knowledge Studio is a file-based knowledge base system designed for use with Claude Code. It provides:

**OKS 不是一个要求用户长期坐在里面写作、整理页面的笔记软件。它不试图替代 Obsidian、Notion、Roam 或用户已有的编辑器。OKS 负责的是：把用户已有的文件、网页、媒体、平台内容和主动提交的信息，经 Agent 提取、人工审核后，沉淀成可召回的文件系统知识。**

- **5 cognitive buckets (profiles/, raw/, wiki/, drafts/, mail/) + 2 infrastructure layers (settings/, _meta/)**: profiles/ incl. recipes, goals; mail/ is short-lived coordination, not recallable knowledge
- **Agent-Native ingestion pipeline**: Source → Provider → EvidenceFragment → EvidenceManifest → `oks raw-commit` → Raw Bundle v0.2 → Candidate → Human Review → Wiki
- **6+1-factor recall engine**: token overlap + substring + topic trace + type boost + review bonus (failure lessons rank higher) + memory curve + optional goal boost (active goals lift on-scope pages; no-op without goals)
- **4 knowledge relationships**: supersedes, enriches, confirms, challenges (CONSTITUTION A4)
- **Recipes & goals**: executable automation recipes + goal-aware recall boosting
- **Dreaming cycle**: raw → AI distill → drafts → human review → wiki
- **Decay system**: memory curve scoring with type-specific λ, tier classification (hot/warm/cold/evictable)
- **Date-based raw/**: `raw/{YYYY}/{MM}/{DD}/{source}/` — auto-organized by intake date + source category
- **Global config**: `~/.oks/config.json` enables cross-project access from any directory
- **CLI tool (`oks`)**: recall, raw-commit, ingest, init, skills-install, wiki CRUD, drafts, distill, lint, status, metrics, capability, schema, security, mail, registry, trace, eval, hook, config (run `oks --help` for the authoritative list)

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
pipx install open-knowledge-studio && pipx ensurepath
oks init my-knowledge-base
cd my-knowledge-base
oks status
oks recall "git branch"
```

pipx avoids PEP 668 `externally-managed-environment` errors on Ubuntu 24.04+ and
macOS Homebrew Python (get pipx: `sudo apt install pipx` / `brew install pipx` /
Windows `py -m pip install --user pipx && py -m pipx ensurepath`).

Developers working from source: `pipx install ./cli --force` to install the
local checkout directly.

## Core Pipeline

```
raw/ (human-collected or tool-processed materials)
  ↓ /ingest skill — Agent-native evidence ingestion
  ↓ Source → Judge Modality → Select Providers → Execute
  ↓ EvidenceFragment × N → EvidenceManifest
  ↓ oks raw-commit → Raw Bundle v0.2
drafts/ (intermediate proposals)
  ↓ /promote skill — human review
wiki/ (curated knowledge, with decay)
  ↓ oks recall / /query skill — 6+1-factor recall
injected into Claude Code context
```

## Memory Architecture

See `CONSTITUTION.md` for the full memory design (A1-A5):

- **A1**: Five cognitive buckets — four knowledge-lifecycle (profiles/raw/wiki/drafts) + mandatory mail/ coordination — and two infrastructure layers (settings=config, _meta=schema)
- **A2**: Six-type memory model + injection order + source labels + conflict priority
- **A3**: Dreaming — human-reviewed knowledge evolution
- **A4**: Knowledge evolution — supersedes, enriches, confirms, challenges
- **A5**: Atomic file writes

## Directory Structure

```
open-knowledge-studio/
├── .claude/          # Claude Code development assets
├── .agents/          # Generic Agent skill replicas
├── .codex/           # Codex hooks config
├── profiles/         # ① Portraits — team, users, projects, recipes, goals
├── raw/              # ② Raw materials — date-based: {YYYY}/{MM}/{DD}/{source}/
├── wiki/             # ③ Curated, human-reviewed knowledge
├── drafts/           # ④ Dreaming candidates
├── mail/             # ⑤ Coordination and human-Agent evaluation evidence
├── settings/         # ⑥ Config layer — decay, tool registry, input sources
├── _meta/            # ⑦ Schema layer — raw evidence shape contract
├── templates/        # concept, strategy, anti-pattern, draft
├── capabilities/     # Capability action catalog (actions.yaml)
├── providers/        # Provider definitions
├── recipes/          # Modality recipes
├── security/         # Credential redaction + sensitive field detection
├── cli/              # Python CLI tool (oks); packaged assets come from assets/
├── docs/             # GitHub Pages site — every .md here is a published page
├── records/          # Versioned acceptance evidence — never in docs/
├── CONSTITUTION.md   # Memory architecture design
├── CHANGELOG.md      # Release history
└── CLAUDE.md         # This file
```

## Claude Code Skills

| Skill | Purpose |
|-------|---------|
| `/assess` | Q&A builds profile + active goals, verify recall boost (initial setup + tuning) |
| `/ingest` | Agent-native evidence ingestion (Source → Provider → Fragment → Manifest → raw-commit) |
| `/query` | 6+1-factor recall → inject into context → AI answers with citations |
| `/lint` | Scan wiki/: frontmatter, orphans, broken links, stale |
| `/compile` | Re-compile concept pages from sources → drafts/ |
| `/status` | Overview: wiki count, tier distribution, drafts, quality |
| `/archive` | Extract conversation Q&A → AI summarize → drafts/ (never writes wiki directly) |
| `/promote` | Review drafts/ → promote/reject/edit |
| `/accept` ⚙ | Evidence-first isolated capability acceptance (maintainer-only, not in wheel) |
| `/media-ingest` | Experimental video intake adapter (currently unavailable — scripts not yet packaged) |

Agents skills mirror Claude skills with identical content. 4 dev-only skills
are excluded from the Wheel via `_DEV_ONLY_ASSET_NAMES`.

## CLI Commands

```bash
# Instance scaffold
oks init <path> [--set-default|--no-set-default] [--git|--no-git] [--upgrade] [--force]
oks skills-install [--force]

# Raw ingestion
oks raw-commit <manifest-dir> [--output/-o <dir>] [--overwrite] [--json/--text]

# Recall (the single retrieval entry — Agent-facing, injected via hook)
oks recall <query> [--topic-id ID] [--limit 5] [--scope AREA] [--type strategy] [--knowledge-only] [--goal active|none|SLUG] [--format table|json] [--explain]
oks wiki list [--domain] [--type] [--status active]
oks wiki get <slug>
oks wiki create --title "..." --type concept --area computing --importance 0.7
oks wiki pin <slug> | archive <slug>
oks wiki use <slug>   # explicit "this page was used" signal (recall is read-only)
oks drafts list | promote <slug> | reject <slug>
oks distill [--dry-run]
oks lint | status | metrics | decay
oks capability list | status [--json/--text] | guide <provider-id>
oks capability install <name> [--yes]
oks hook install [--editor claude|qoder|both] [--path DIR]   # opt-in auto-recall on prompt
oks hook status
oks eval recall <dataset.yaml> --output <run.json>
oks eval compare <baseline.json> <candidate.json> [--output <comparison.json>]
oks trace start <goal-id> [--run-id ID]
oks trace append <run-id> --type <event> --actor <actor> --payload '<json>'
oks trace judge <run-id> --outcome pass --comment "..."
oks trace feedback <run-id> --outcome accepted --comment "..."
oks trace propose <run-id> --kind wiki|skill --title "..." --summary "..."
oks trace finish <run-id> --result '{"outcome":"success"}'
oks trace validate <run-id> [--completed]
oks config init | show | set <key> <value>
```

## Conventions

- **raw/** is human-collected or tool-processed. Tools preserve maximum fidelity — they convert format, not knowledge. LLM does not write knowledge to raw/.
- **wiki/** is LLM-written, human-approved via drafts/ review.
- **Intake is agent-direct** — OKS does not wrap tool calls. Agent checks tool availability via Bash (`which curl`, etc.).
- **Global config** (`~/.oks/config.json`) enables cross-project access — `oks recall` works from any directory (resolution: `OKS_ROOT` env → config `knowledge_base_path` → cwd).
- **Code repo vs instance repo** — THIS repo is the reusable tool/template: it ships clean (wiki/ & drafts/ gitignored) so others can use it. Your personal knowledge lives in a separate instance created by `oks init <path>`, which TRACKS memory in git. Practices proven in an instance flow back here as PRs.
- **Git IS the migration** — no database, schema changes versioned through _meta/.
- **Atomic writes** — all persistent writes use mkstemp + fsync + os.replace.
- **Never auto-promote** raw content to wiki/ without human review.

## Project-specific safety rules

- Personal knowledge lives in a separate instance created by `oks init <path>`; this repository is reusable Studio code and must not remain the long-term destination for personal Wiki or Raw state.
- Every `git push`, Pull Request create/update/close, Merge, Pages/Release publication, deployment, remote setting change, or external message requires the user's explicit authorization for that exact action. A general “continue” or authorization for a different action does not count.
- Without that authorization, stop after local editing, validation, diff review, and read-only remote inspection. A Draft PR is still an external action.
- Context compaction is controlled by the client or runtime; this file cannot set an automatic threshold or reveal an unexposed usage percentage. If the client explicitly reports 80% usage, or at major milestones and around unusually large tool output, preserve a structured checkpoint before invoking an actually available compaction mechanism.
- Preserve `partial`, `failed`, and `skipped` states exactly. Mechanical extraction, AI interpretation, human review, and Wiki promotion are separate layers and must remain traceable.
