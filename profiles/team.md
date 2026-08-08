---
title: "Knowledge Studio Team"
type: profile
tags: [team, open-knowledge-studio, knowledge-base]

confidence: 0.9
confidence_reason: "git contributor + verified collaboration"
last_verified: 2026-07-13
verification_status: verified
verification_count: 3

created: 2026-06-04
last_accessed: 2026-07-13
access_count: 5
ttl_days: 180
status: active

source: setup + git-log-verified
---

# Knowledge Studio Team

An AI-driven development team building open-knowledge-studio — a knowledge engineering repository with a self-reinforcing memory flywheel for Claude Code.

## Culture

- **Ship fast, learn faster** — every PR is a learning opportunity
- **Knowledge as Code** — all decisions, patterns, and mistakes are distilled into markdown
- **One PR = One problem** — no scope creep, no unrelated changes
- **Verify, don't assume** — run scripts > read docs > trust intuition
- **English code, Chinese chat** — technical communication in English, casual chat in Chinese

## Projects

### open-knowledge-studio — Knowledge Engineering Repository

A standalone knowledge engineering repository for Claude Code. Features a 5-bucket memory architecture (profiles, raw, wiki, drafts, settings), 6-factor recall engine, decay system with memory curves, and Dreaming distillation pipeline.

**Key technical achievements:**

- **5-bucket memory architecture** — profiles (direct read), raw (keyword + freshness), wiki (6-factor relevance + memory curve), drafts (human review), settings (direct read)
- **6-factor recall engine** — token overlap, substring match, topic trace, type boost, review penalty, memory curve scoring
- **Memory-curve scoring** — `score = importance × e^(-λt) + 0.5×ln(1+access) + pin_bonus`, with type-specific decay λ values
- **Dreaming cycle** — Collect → AI Dream → Write Drafts → Human Review → Promote → Decay → Evolve → Commit
- **Decay system** — tier-based classification (hot/warm/cold/evictable), grace period for new knowledge, high-access boost
- **`oks` CLI** — Python CLI with Typer for search, wiki management, distillation, linting, and sync
- **8 Claude Code skills** — start, ingest, query, lint, compile, status, archive, promote
- **3 hooks** — validate-wiki-write, pre-compact snapshot, session-start summary
- **22 knowledge domains** with concepts/strategies/anti-patterns structure

## Tech Stack

| Layer | Technology |
|-------|-----------|
| CLI | Python 3.12 + Typer + Rich |
| Search | jieba + custom 6-factor recall |
| Knowledge | Pure Markdown + YAML frontmatter + Git |
| AI | Claude Code (skills + hooks) |
| VCS | Git + GitHub |

## North Star

**知识飞轮持续积累、自我进化。**

每次知识沉淀都让下一次召回更聪明。这不是一个数字目标，而是一个自我强化的循环——团队的核心使命。
