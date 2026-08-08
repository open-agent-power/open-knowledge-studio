---
description: First-time onboarding — initialize knowledge base, select domains, scan raw/
---

# /start — Knowledge Studio Onboarding

## Purpose

First-time setup wizard for a new knowledge base.

## Steps

1. **Check initialization** — Run `oks status`. If wiki/ has pages, ask user if they want to re-onboard.
2. **Ask domains** — Present 22 pre-built domains. Ask which the user actively works in.
3. **Scan raw/** — List files in raw/articles/, raw/papers/, raw/repos/, raw/misc/. Report counts.
4. **Create team profile** — Ask team name. Write `profiles/team.md`.
5. **Health check** — Run `oks lint`. Report issues.
6. **Next steps** — Suggest `/ingest`, `/query`, `oks wiki create`.
