---
name: project-agentuniverse
description: 'agentUniverse — Python multi-agent framework. Competition project (¥50000).'
title: agentUniverse Project Profile
type: profile
status: active
tags: [project, competition, python]
---

# agentUniverse

## Repo Info

| Field | Value |
|-------|-------|
| GitHub | `antgroup/agentUniverse` (was `alibaba/agentUniverse`) |
| Language | Python |
| Framework | Multi-agent orchestration |
| Prize | ¥50000 |
| Competition Period | 2026-06-15 to 2026-09-20 |

## Technical Stack

- **Python version**: 3.8+ (check `setup.py` / `pyproject.toml` — use `Union[X, Y]` not `X | Y`)
- **Package manager**: Poetry (`pyproject.toml`, `poetry.lock`)
- **Test runner**: `pytest` — `poetry run pytest tests/test_agentuniverse/unit/`
- **Linting**: flake8 / ruff (check `setup.cfg` / `pyproject.toml`)
- **Type checking**: mypy (check if `--strict` is enabled)

## CI Rules

- Read `.github/workflows/` before pushing
- Check for Python version matrix (3.8, 3.9, 3.10, 3.11, 3.12)
- Codecov may fail on fork — only treat compilation errors and test failures as real

## ⚠️ Repo Activity Warning (2026-07-07)

- Last push: **2026-04-24** (2.5 months ago)
- Last 5 commits all merged on same day by same person (SeasonPilot)
- **PR #598 and #601 submitted 07-05, 0 CI checks ran, 0 reviews**
- Maintainer appears inactive — PRs may never be reviewed
- **Action**: Do NOT invest more effort here until maintainer responds.

## Contribution Guidelines

- Fork → feature branch → PR
- Target branch: `master` (NOT `main`)
- Check `CONTRIBUTING.md` for specific rules
- No CLA requirement confirmed (verify before each PR)

## Key Files

| File | Purpose |
|------|---------|
| `agentuniverse/llm/default/` | LLM implementations (HuggingFace, OpenAI, etc.) |
| `agentuniverse/agent/action/tool/` | Tool implementations |
| `tests/test_agentuniverse/unit/` | Unit tests |
| `pyproject.toml` | Dependencies and config |

## Known Gotchas

- `ApplicationConfigManager().app_configer` must be initialized in test setUp: `ApplicationConfigManager().app_configer = AppConfiger()`
- HuggingFace `InferenceClient` uses `chat_completion()` not `chat_completions.create()`
- `BaseInferenceType` extends `dict` but has no `model_dump()` — use `dict(obj)` fallback
- `AsyncInferenceClient` is a separate class, not the same as `InferenceClient`
- Abstract classes require `get_num_tokens()` implementation — check all abstract methods

## Previous PRs

| PR | Status | Description |
|----|--------|-------------|
| #598 | Open | HuggingFace LLM fix (wrong API, shared async client, missing abstract method) |
| #601 | Open | PythonREPLTool sandbox (blocked dangerous patterns) |
