---
name: project-oss-compass
description: 'OSS Compass — Open source ecosystem analysis platform. Competition project (¥50000). 3 repos.'
title: OSS Compass Project Profile
type: profile
status: active
tags: [project, competition, python, typescript]
---

# OSS Compass

## Repo Info

| Field | Value |
|-------|-------|
| GitHub Org | `oss-compass` (NOT `ossf-compliance` — that was wrong) |
| Language | Python (backend), TypeScript (frontend) |
| Framework | Django + React |
| Prize | ¥50000 |
| Competition Period | 2026-06-15 to 2026-09-20 |

## Active Repos (3 key repos)

| Repo | Stars | Last Push | Open Issues | Tech |
|------|-------|-----------|-------------|------|
| `compass-web` | 21 | 2026-07-07 | 50 | React/TS frontend |
| `compass-metrics-model` | 17 | 2026-07-07 | 14 | Python metrics |
| `compass-projects-information` | 18 | 2026-07-06 | 15 | Python data |

## Issue Opportunities (identified 2026-07-07)

### compass-web (frontend, TS/React)
- #348: Depth insight contribution pie chart — UI fix
- #330: Deep insight search optimization — filter criteria
- #285: Depth insight page zero display — small fix
- #130: Migrate OAuth to backend — medium feature
- #73: Report download as PDF — feature

### compass-metrics-model (Python)
- #103: Contributor domain profiling — lines of code view
- #102: Project Deep Insight contributor org optimization
- #49: Code Review Ratio metric data abnormal — bug fix (Apache project data)
- #27: Performance tuning — backend optimization

## Technical Stack

- **Python version**: Check `setup.py` / `requirements.txt`
- **Node version**: Check `package.json` engines
- **Backend**: Django (check `manage.py`)
- **Frontend**: React or Vue (check `package.json`)
- **Database**: PostgreSQL or MySQL (check settings)

## CI Rules

- Read `.github/workflows/` before pushing
- Check for Django test runner: `python manage.py test`
- Frontend: `npm test` or `yarn test`
- Linting: eslint, flake8/black

## Contribution Guidelines

- Fork → feature branch → PR
- Target branch: `main`
- Check `CONTRIBUTING.md` for specific rules
- Check if CLA is required

## Key Areas for Contribution

| Area | Tech | Opportunities |
|------|------|---------------|
| Backend | Python/Django | API bugs, data processing |
| Frontend | TypeScript/React | UI fixes, accessibility |
| Analysis | Python | Metrics calculation, algorithm |
| Docs | Markdown | Documentation improvements |

## Known Gotchas

- 3 repos may share code — check cross-repo dependencies before changing shared interfaces
- Django models changes may require migrations — don't include migration files unless asked
- Frontend and backend may have separate CI pipelines
- Check which repo the issue is in before starting work

## Previous PRs

| PR | Status | Description |
|----|--------|-------------|
| #382 | Open | Fix #285: show analyzing status instead of 0 during analysis (7 lines, 1 file) |
