# Open Knowledge Studio

> A knowledge engineering workspace for Claude Code — raw → wiki → recall.

## What is this?

Open Knowledge Studio is a file-based knowledge base system designed for use with Claude Code. It provides:

- **4 cognitive buckets + 2 infrastructure layers**: profiles/, raw/, wiki/, drafts/ (cognitive), settings/ (config), _meta/ (schema)
- **Agent-Native ingestion pipeline**: Source → Provider → EvidenceFragment → EvidenceManifest → `oks raw-commit` → Raw Bundle v0.2 → Candidate → Human Review → Wiki
- **6+1-factor recall engine**: token overlap + substring + topic trace + type boost + review bonus (failure lessons rank higher) + memory curve + optional goal boost (active goals lift on-scope pages; no-op without goals)
- **16 Providers** across 4 execution tiers: agent_native (2), managed (8), external (4), human (1), blocked/experimental (2)
- **18 capability actions**: source.fetch, web.fetch, document.text.extract, image.ocr, speech.transcribe, etc.
- **Dreaming cycle**: raw → AI distill → drafts → human review → wiki
- **Decay system**: memory curve scoring with type-specific λ, tier classification (hot/warm/cold/evictable)
- **CLI tool (`oks`)**: 46 commands across 8 Typer groups — search, recall, raw-commit, ingest, init, skills-install, wiki CRUD, drafts, distill, lint, status, metrics, capability, feishu, trace, eval, hook, config

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
pipx install open-knowledge-studio && pipx ensurepath   # PyPI
# Developers: pipx install ./cli --force
oks init my-knowledge-base
cd my-knowledge-base
oks status
oks search "git branch"
```

## Core Pipeline

```
raw/ (human-collected or tool-processed materials)
  ↓ /ingest skill — Agent-native evidence ingestion
  ↓ Source → Providers → EvidenceFragment → EvidenceManifest
  ↓ oks raw-commit → Raw Bundle v0.2
drafts/ (intermediate proposals)
  ↓ /promote skill — human review
wiki/ (curated knowledge, with decay)
  ↓ oks search / /query skill — 6+1-factor recall
injected into Claude Code context
```

## Memory Architecture

See `CONSTITUTION.md` for the full memory design (A1-A5):

- **A1**: Four cognitive buckets + two infrastructure layers + memory lifecycle (Observe→Write→Store→Retrieve→Inject→Forget)
- **A2**: Six-type memory model + injection order + source labels + conflict priority
- **A3**: Dreaming — human-reviewed knowledge evolution
- **A4**: Knowledge evolution — supersedes, enriches, confirms, challenges
- **A5**: Atomic file writes

## Directory Structure

```
open-knowledge-studio/
├── .claude/          # Claude Code skills (10) + hooks (4) + rules (2)
├── .codex/           # Codex local config, hooks
├── .agents/          # Agent skill replicas (10 Claude + 10 Agents)
├── profiles/         # ① Portraits — team, users, projects, recipes, goals
├── raw/              # ② Raw materials — date-based: {YYYY}/{MM}/{DD}/{source}/
├── wiki/             # ③ Curated knowledge — 22 domains × 3 types
├── drafts/           # ④ Dreaming candidates
├── settings/         # ⑤ Config layer — decay, tool registry, input sources
├── _meta/            # ⑥ Schema layer — raw evidence, recall case, trace event
├── templates/        # concept, strategy, anti-pattern, draft
├── capabilities/     # Capability action catalog (actions.yaml)
├── recipes/          # Modality recipes (text, pdf, office, image, web, audio, video)
├── providers/        # 16 Provider definitions (provider.yaml + SKILL.md)
├── security/         # Credential redaction + sensitive field detection
├── cli/              # Python CLI tool (oks) + skill_templates/ (canonical skill source)
├── docs/             # GitHub Pages design documentation
├── CONSTITUTION.md   # Memory architecture design
├── CLAUDE.md         # Claude Code project instructions
├── CHANGELOG.md      # Release history
└── README.md
```

## Claude Code Skills

| Skill | Purpose |
|-------|---------|
| `/start` | First-time setup: choose domain, build structure, scan raw/ |
| `/ingest` | Agent-native evidence ingestion (Source → Provider → Fragment → Manifest → raw-commit) |
| `/query` | 6+1-factor recall → inject into context → AI answers with citations |
| `/lint` | Scan wiki/: frontmatter, orphans, broken links, stale |
| `/compile` | Re-compile concept pages from sources → drafts/ |
| `/status` | Overview: wiki count, tier distribution, drafts, quality |
| `/archive` | Extract conversation Q&A → AI summarize → drafts/ (never writes wiki directly) |
| `/promote` | Review drafts/ → promote/reject/edit |
| `/accept` | Evidence-first isolated capability acceptance (wheel install, ingest, promote, recall) |
| `/media-ingest` | Experimental video intake adapter (currently unavailable — scripts not yet packaged) |

Agents skills mirror Claude skills with identical content. 4 dev-only skills
(`review-upstream-pr`, `upstream-pr-remediation`, `triad-engineering-closure`,
`claude-code-vision-skill`) are excluded from the Wheel via `_DEV_ONLY_ASSET_NAMES`.

## CLI Commands

```bash
# Instance scaffold
oks init <path> [--set-default|--no-set-default] [--git|--no-git] [--upgrade] [--force]
oks skills-install [--force]

# Raw ingestion
oks raw-commit <manifest-dir> [--output/-o <dir>] [--overwrite] [--json/--text]

# Search & recall
oks search <query> [--limit 5] [--domain computing] [--type strategy] [--goal active|none|SLUG] [--format table|json] [--explain]
oks recall <query> [--topic-id ID] [--limit 5] [--goal active|none|SLUG] [--format table|json] [--explain]

# Wiki
oks wiki list [--domain] [--type] [--status active]
oks wiki get <slug>
oks wiki create --title "..." --type concept --area computing --importance 0.7
oks wiki pin <slug> | archive <slug>
oks wiki use <slug>   # explicit "this page was used" signal

# Drafts
oks drafts list | promote <slug> | reject <slug>
oks distill [--dry-run]

# Maintenance
oks lint | status | metrics | decay

# Capability
oks capability list
oks capability install <name> [--yes]
oks capability catalog [--json/--text] [--verbose]
oks capability doctor [--json/--text] [--verbose]

# Feishu
oks feishu auth | form --url <url> | submit <content> | run-once | listen
oks feishu setup [--base-token] [--table-id] [--base-name] [--table-name] [--repair-schema] [--yes]

# Hooks (opt-in auto-recall)
oks hook install [--editor claude|qoder|both] [--path DIR]
oks hook status

# Evaluation
oks eval recall <dataset.yaml> --output <run.json>
oks eval compare <baseline.json> <candidate.json> [--output <comparison.json>]

# Execution traces
oks trace start <goal-id> [--run-id ID]
oks trace append <run-id> --type <event> --actor <actor> --payload '<json>'
oks trace judge <run-id> --outcome pass --comment "..."
oks trace feedback <run-id> --outcome accepted --comment "..."
oks trace blocker <run-id> --reason "..." --needed "..."
oks trace propose <run-id> --kind wiki|skill --title "..." --summary "..."
oks trace finish <run-id> --result '{"outcome":"success"}'
oks trace validate <run-id> [--completed]
oks trace show <run-id>

# Config
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
- Every `git push`, Pull Request create/update/close, Merge, Pages/Release publication, deployment, remote setting change, or external message requires the user's explicit authorization for that exact action. A general "continue" or authorization for a different action does not count.
- Without that authorization, stop after local editing, validation, diff review, and read-only remote inspection. A Draft PR is still an external action.
- Context compaction is controlled by the client or runtime; this file cannot set an automatic threshold or reveal an unexposed usage percentage. If the client explicitly reports 80% usage, or at major milestones and around unusually large tool output, preserve a structured checkpoint before invoking an actually available compaction mechanism.
- Preserve `partial`, `failed`, and `skipped` states exactly. Mechanical extraction, AI interpretation, human review, and Wiki promotion are separate layers and must remain traceable.
