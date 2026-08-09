---
description: First-time onboarding — initialize knowledge base, pick domains, survey raw/
---

# /start — Knowledge Studio Onboarding

## Purpose

First-time setup for a new knowledge base instance.

## Steps

1. **Check initialization** — Run `oks status`. If wiki/ already has pages, ask
   whether the user wants to re-onboard.
2. **Ask domains** — The 22 knowledge domains are a *soft convention*, not a
   pre-built skeleton: directories are created on demand when the first page
   lands. Ask which areas the user actually works in, and use those as the
   `area` values from then on.
3. **Survey raw/** — Read `raw/index.json` for collected bundles (status,
   evidence counts, warnings). Raw material lives under
   `raw/{YYYY}/{MM}/{DD}/{source}/`, or `raw/<bundle-id>/` for connector output.
   Skip `raw/executions/` and `raw/.logs/` — those are provenance, not material.
4. **Create team profile** — Ask for a team name. Write `profiles/team.md`.
5. **Health check** — Run `oks lint`. Report issues.
6. **Next steps** — Suggest `oks ingest <source>`, then `/ingest` to triage,
   `/query` to recall, and `oks wiki create` for hand-written pages.
