---
title: "JuanNiuMo Team"
type: profile
tags: [team, autpilot, knowledge-base]

confidence: 0.95
confidence_reason: "git contributor + verified collaboration"
last_verified: 2026-06-25
verification_status: verified
verification_count: 3

created: 2026-05-25
last_accessed: 2026-06-25
access_count: 20
ttl_days: 180
status: active

source: setup + git-log-verified
---

# JuanNiuMo Team

An AI-driven research and full-stack development team building autpilot — a goal-driven AI project management platform with a self-reinforcing knowledge flywheel.

The Manager AI (XiaoHang) is deployed on the server. Human members bind machine workers via CLI. Every goal execution produces learnings that compound into domain knowledge, making the next execution smarter.

## Culture

- **Ship fast, learn faster** — every PR is a learning opportunity
- **Knowledge as Code** — all decisions, patterns, and mistakes are distilled into markdown
- **One PR = One problem** — no scope creep, no unrelated changes
- **Verify, don't assume** — run scripts > read docs > trust intuition
- **English code, Chinese chat** — technical communication in English, casual chat in Chinese

## Projects

> All projects are currently closed-source. Open-source release is planned.

### autpilot-web — Platform (349 commits)

The core platform: FastAPI backend + React frontend + Python CLI. Provides Discuss (AI chat with knowledge recall), Goal (Kanban + 8-stage execution pipeline), and Learning (auto-distillation + domain promotion).

**Key technical achievements:**

- **8-stage goal pipeline** (Prepare→Assemble→Remote→Resolve→SetupEnv→RunAgent→Collect→Finalize) — modular stages with per-workspace locking, cancel/pause/resume, and post-execution hooks for distillation, review, and auto-evaluation
- **Knowledge flywheel** — Discuss→Goal→Learning→Recall loop with memory-curve scoring (`score = importance × e^(-λt) + 0.5×ln(1+access) + pin_bonus`), auto-decay, and domain promotion when 3+ same-tag learnings accumulate
- **Goal graph** — DAG-based context management with auto-edge detection (depends_on/refines/contradicts/reuses/supersedes), traverses 1-hop and 2-hop neighbors to inject related memories into execution context
- **Token-based context compression** — replaces message-count truncation with 8000-token budget, preserving recent context while compressing older messages
- **WebSocket real-time streaming** — EventBus with 20+ event types, 60-second replay buffer for reconnection, per-topic message serialization, and binary screenshot streaming for remote browser
- **Playwright browser automation** — CDP-based screencast, mouse/keyboard injection, tab lifecycle management with dynamic callback lookup
- **Multi-provider AI** — supports Anthropic Claude, Zhipu GLM, DeepSeek, Tongyi Qwen, and custom proxies via configurable base_url + API key injection
- **JSONL KnowledgeStore** — file-backed data store with in-memory cache, per-collection asyncio locks, atomic writes (tempfile + os.replace + fsync), replacing SQLite for business data
- **NeoBrutalism design system** — 16 reusable React components built on @base-ui/react + CVA, with CSS custom properties for theming and zero border-radius aesthetic

### autpilot-knowledge — Knowledge Base (453 commits)

The team's collective memory: learnings, domain knowledge, profiles, and extensions. Synced via git with auto-commit + 3-level retry (commit → stash+pull+pop → give up).

**Key technical achievements:**

- **Auto-distillation pipeline** — extracts learnings from goal executions and discussions every 6 hours using AI, with quality gates (skip < 50 chars, generic titles, importance < 0.3)
- **Memory-curve scoring** — time-decayed scoring with category-specific lambda values (decision: 0.030, pattern: 0.020, mistake: 0.025), access-count boost, and pin bonus
- **Domain promotion** — automatically promotes 3+ same-tag learnings into `domain/autpilot/conventions/` markdown files, merging insights and setting `promoted_to` field
- **Extension suggestions** — analyzes learning patterns to generate specific constraint prompts (e.g., "React components must have TypeScript interface for props"), stored in `extensions/config.jsonl`
- **Knowledge health check** — validates frontmatter correctness, promoted_to target existence, extension validity, and coverage metrics across domain branches
- **Current scale**: 96 learnings across 11 date folders, 21 domain pages, 4 profiles

### autpilot-plugins — Plugin Marketplace (49 commits)

Four Claude Code plugins with 32+ skills, 4 commands, 3 hooks, and 91 benchmark test cases.

**Key technical achievements:**

- **Full delivery chain** — `repo-explorer → coding → run-tests → debugger → visual-verify → acceptance-review → submit-pr → eval-contribution` with 5-gate pre-submission checklist (including competing PR check — #1 cause of closed PRs)
- **CI failure self-heal** — auto-growing `fixes/` directory with 9 distilled CI-failure patterns, bounded to 3 fix rounds to prevent runaway loops
- **91 benchmark cases** across 4 tracks: Conduit baseline (11), cross-repo code (5), web contract (4), app generalization (70). Diverse-20 at 100% pass rate, App-50 at 73%
- **autpilot-coding** (14 skills): repo-scout, github-ops, issue-triage, pr-review, coding, run-tests, debugger, visual-verify, changeset, acceptance-review, submit-pr, humanize, eval-contribution, code-context
- **autpilot-io** (9 skills): normalizes Feishu docs/sheets, Bilibili/Douyin videos, and exports PRD/PPT artifacts
- **autpilot-learning** (5 skills): scheduled distillation, workspace cleanup, knowledge archiving, and git sync
- **Extension contract** — adding a new capability = 1 SKILL.md file + 1 INDEX row. No edits to core orchestration needed.

### autpilot — Goal Execution Runtime

Lightweight Claude Agent SDK wrapper for goal execution on remote machines. Provides git workflow automation (branch→commit→push→PR) and daemon dispatch (register→heartbeat→claim→execute→report).

## By the Numbers

- **10.3B tokens** processed across 430+ AI coding sessions
- **112K+ AI messages** exchanged with Claude Code, Qoder, and autpilot
- **31 projects** developed with AI assistance + 60 Qoder sessions
- **154 distilled learnings** with memory-curve scoring and auto-decay
- **80+ goals executed** through the 8-stage pipeline
- **21 domain knowledge pages** covering architecture, coding discipline, conventions
- **4 plugins** with 32+ skills and 91 benchmark test cases
- **10+ merged PRs** to open-source repositories via the platform

## Milestones

| Date | Milestone |
|------|-----------|
| 2026-05-25 | Project bootstrap — monorepo scaffold with locked v1.0 design |
| 2026-05-27 | Backend MVP — Claude Agent SDK integration, goal runner, knowledge API |
| 2026-05-28 | Auth + UI — GitHub OAuth, RetroUI component library, NeoBrutalism style |
| 2026-05-29 | Knowledge + Plugins — initialized shared knowledge base and plugin marketplace |
| 2026-05-29 | W2 Complete — EventBus, execution engine, config API, streaming logs |
| 2026-05-31 | Infrastructure — auto-deploy on push, Playwright browser deps, secret management |
| 2026-06-20 | Knowledge flywheel — recall_learnings wired, access tracking, 7 context providers |
| 2026-06-22 | Goal graph — DAG-based context management with auto-edge detection |
| 2026-06-23 | CLI — streaming goal execution, discuss commands, init wizard |
| 2026-06-24 | Knowledge evolution — domain promotion + extension suggestions + health check |
| 2026-06-25 | Company dashboard — team.md rendering, north star metrics, apply-to-join flow |

## Recruitment

We're growing! Looking for:

- **Frontend Engineers** — React + TypeScript + Tailwind, interest in design systems
- **AI/ML Engineers** — Experience with Claude SDK, prompt engineering, agent pipelines
- **Backend Engineers** — Python + FastAPI, interest in knowledge graphs and distillation

How to join:
1. Be added as a collaborator on our GitHub repo
2. Or apply via the login page — we'll review your application
3. Once approved, bind your machine via `autpilot login` and start shipping

## North Star

**知识飞轮持续积累、自我进化。**

每次 Goal 执行都沉淀 learnings，让下一次更聪明。这不是一个数字目标，而是一个自我强化的循环——团队的核心使命。

## Team Goals

### 1. Open-Source autpilot-web

Prepare autpilot-web for public open-source release. Define the project's competitive advantages, polish documentation, and iterate through discussion. The platform's unique value: a goal-driven AI PM with a self-reinforcing knowledge flywheel — Discuss→Goal→Learning→Recall — where every execution makes the next one smarter.

### 2. Optimize coding-plugin PR Success Rate

Improve autpilot-coding plugin's PR submission success rate. The delivery chain (repo-scout→coding→tests→debug→acceptance-review→submit-pr) must produce PRs that get merged, not closed. Measure: PR merge rate, average iterations to merge, closed-PR root causes.

### 3. GitHub Achievement Flywheel

Open-source contributions are the flywheel's external metric — each PR merged validates the coding plugin and feeds learnings back into the knowledge base.

**Current Status (2026-06-28):**

| Metric | Value | Target | Progress |
|--------|-------|--------|----------|
| External merged PRs | 12 | 16+ (Pull Shark L4) | 75% |
| Co-authored merged PRs | 1 | 3+ (Pair Extraordinaire L2) | 33% |
| Top repo stars | 71 (offer-laolao-plugin) | 128+ (Starstruck L2) | 55% |
| PRs reviewed (total) | 118+ | 150+ | 79% |
| Repos engaged | 42+ | 50+ | 84% |
| Open PRs | 29 (external) | — | — |
| Knowledge learnings | 329 | — | — |
| Domain pages | 44 (22 行业域) | — | — |
| Plugin skills | 22 | — | — |
| Fix patterns | 13 | — | — |
| Strategy rules | 9 | — | — |

**Achievement ↔ Flywheel alignment:**

```
Pull Shark ↑    ←  coding plugin produces merged PRs  →  flywheel accumulates PR experience
Pair Extraord ↑ ←  co-author strategy executes         →  flywheel accumulates collaboration patterns
Starstruck ↑    ←  autpilot-web/plugins open-source      →  flywheel influence expands
```

**Key repos by merge responsiveness:**

| Repo | Stars | Merged | Open | Closed | Merge率 | Notes |
|------|-------|--------|------|--------|--------|-------|
| agentscope-ai/agentscope-java | 4K | 3 | 4 | 2 | 43% | Best overall, 1-3 day merge |
| remotion-dev/remotion | 16K | 2 | 0 | 1 | 67% | Fast merge for small fixes |
| lc2panda/wps-skills | — | 2 | 0 | 0 | 100% | Quick merge |
| alibaba/page-agent | 1K | 1 | 0 | 0 | 100% | Same-day merge |
| HoraDomu/Atheon | 0.5K | 1 | 0 | 0 | 100% | Quick merge |
| kedacore/keda | 10K | 0 | 1 | 0 | — | e2e passed (36/36), awaiting merge |
| open-webui/open-webui | 143K | 0 | 1 | 1 | — | New, dev branch + CLA |
| QuivrHQ/quivr | 39K | 0 | 1 | 0 | — | New, security fix |
| activepieces/activepieces | 23K | 0 | 1 | 0 | — | New, privacy fix |
| ChromeDevTools/chrome-devtools-mcp | 44K | 0 | 1 | 0 | — | CLA blocked |
| MoonshotAI/kimi-code | 5K | 0 | 7 | 0 | 0% | Fully silent, reduce investment |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + TypeScript + Vite + RetroUI |
| Backend | Python 3.12 + FastAPI + SQLAlchemy |
| AI | Anthropic Claude SDK / Zhipu GLM / Tongyi Qwen |
| Storage | JSONL (KnowledgeStore) + SQLite (secrets) |
| Knowledge | Pure Markdown + YAML frontmatter + Git |
| VCS | Git + GitHub |
| Package | uv (Python) + pnpm (frontend) |
