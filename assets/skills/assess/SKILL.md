---
description: Assess your memory system — Q&A builds profile + active goals, then verify recall boost
---

# /assess — Memory System Assessment

## Purpose

One skill does double duty: **initial setup** and **tuning after use**. Both are the same thing — evaluate the user, generate parameters, verify recall works. Run it on a fresh instance to seed `profiles/` + `goals/`; run it again after a few weeks to tune.

## Why

OKS recall scores with a 6+1 factor engine. The "+1" is **goal boost**: pages whose `area` matches an active goal's `domains` get +0.8, keyword hits +0.4. Without an active goal, recall runs on raw token overlap alone — good enough for literal matches, weak for "what am I working on". A correctly set goal is the cheapest recall tuning lever, **no embedding needed** (see [召回引擎](../../docs/algorithms/recall-engine.md)).

Most users won't hand-write `profiles/goals/`. This skill asks 4 questions and generates the parameters — so recall is accurate from day one.

## Flow

```
Q&A (4 questions) → generate profiles/users/{user}.md + profiles/goals/{slug}.md
→ oks recall "<keyword from answers>" → verify goal boost → report + tuning advice
```

## Step 1: Q&A

Ask these 4 questions. Accept free-form answers; the agent extracts structured fields.

| # | Question | What it generates |
|---|----------|-------------------|
| 1 | **你的角色和主要技术栈是什么？**（如"技术负责人，Java / AI Coding / MCP / RAG"）| `profiles/users/{user}.md` — 身份 + 技术栈 |
| 2 | **你接下来 1-3 个月的主要目标是什么？**（如"求职 AI Coding 方向"或"给 RocketMQ 贡献 PR"）| `profiles/goals/{slug}.md` — active goal（domains + keywords 从目标提取）|
| 3 | **你偏好怎样的 AI 协作？**（如"简洁列表 > 长段落，关键逻辑才测试，先做再审"）| profile 的"AI 协作注意"段 |
| 4 | **你常用的项目有哪些？**（可选，如"open-knowledge-studio, RocketMQ"）| `profiles/projects/{slug}.md`（每个项目一页）|

### Extracting domains + keywords from a goal answer

From the user's goal text, extract:

- **domains**: map to the 22 OKS areas（`computing` / `engineering` / `personal` / `management` / ...）. E.g. "求职" → `personal`；"给 RocketMQ 贡献 PR" → `computing`, `engineering`.
- **keywords**: 3-5 salient terms from the goal text（e.g. "求职 AI Coding" → `简历`, `技术栈`, `AI Coding`）.

## Step 2: Generate parameters

### profiles/users/{github-user}.md

```yaml
---
title: "个人画像 - {user}"
type: profile
tags: [user, {user}, {role-tag}, {stack-tag}]
confidence: 0.9
confidence_reason: "self-reported via /assess"
last_verified: {today}
verification_status: verified
verification_count: 1
created: {today}
last_accessed: {today}
access_count: 0
ttl_days: 180
status: active
source: assess-qna
---

# 个人画像 - {user}

## 身份

- **GitHub**: [{user}](https://github.com/{user})   # if known; else leave placeholder
- **角色**: {role from Q1}

## 技术栈

{bullet list from Q1}

## 工作风格

{from Q3, parsed into bullets: 决策风格 / 测试方式 / 沟通风格}

## AI 协作时的注意

{from Q3, the preference portion}
```

### profiles/goals/{slug}.md

```yaml
---
title: {goal title from Q2}
type: goal
owner: {user}
period: "{today}..{today+90d}"
status: active
domains:
  - {domain 1}
  - {domain 2}
keywords:
  - {keyword 1}
  - {keyword 2}
  - {keyword 3}
---

# {goal title}

## Objective

{user's goal text verbatim from Q2}
```

## Step 3: Verify recall boost

Run a recall using a keyword from the user's answers (usually from Q1 技术栈 or Q2 目标):

```bash
oks recall "<keyword>" --knowledge-only --limit 3 --explain
```

Check the top hits' `score_components`:

- `goal_area` should be > 0 for pages whose `area` ∈ the goal's `domains`
- `goal_keyword` should be > 0 for pages matching the goal's `keywords`

### What "working" looks like

- A page on the user's topic ranks #1 with `goal_area + goal_keyword` visible in `--explain`
- If the user ingested their resume or a project doc, it should surface

### Tuning advice

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Top hits unrelated to user's work | No active goal, or goal `domains` wrong | Re-run `/assess`, fix domain extraction |
| Relevant page ranks low | `type=strategy` ×0.8 multiplier, or low `importance` | Set `importance: 0.9` on key pages; or pin with `oks wiki pin <slug>` |
| Too many false positives | `OKS_RECALL_FLOOR` too low (default 0.7) | Raise floor: `OKS_RECALL_FLOOR=1.0` in hook env |
| Goal boost not applied | `--goal none` was used, or no `profiles/goals/*.md` with `status: active` | Verify goal file exists + `status: active`; omit `--goal` to use default active |

## Step 3.5: Register terminal (bind agent+cwd -> profile/goals)

After generating profile + goals, bind the current terminal so the hook
fast-retrieves goals and skips the first-run guide on future sessions:

```bash
# agent_id from OKS_AGENT_ID env, or cwd basename; cwd is the current project dir
oks registry bind \
  --agent-id "${OKS_AGENT_ID:-$(basename "$(pwd)")}" \
  --cwd "$(pwd)" \
  --profile {user} \
  --goals {goal-slug-1},{goal-slug-2}
```

Writes `records/registry/terminals.jsonl` (git-shared). The hook reads it on next
prompt: matching entry skips the first-run guide.

## Step 4: Report

Tell the user:

1. **What was generated** — profile path + goal path + slug
2. **Recall check result** — top hit + rel score + whether goal boost applied
3. **Tuning advice** — any of the above table rows that apply
4. **Next steps** — `oks ingest <source>` to add raw material; `/ingest` to triage; `oks recall "<query>"` any time

## When to re-run

- **Goal changed**（new quarter, new project）→ re-run Q2, regenerate goal
- **Recall feels off** → re-run Step 3, check tuning advice
- **Stack shifted**（learned new tech）→ re-run Q1, update profile 技术栈

The profile + goals are plain markdown — hand-edit any time; `/assess` is just the bootstrap + verifier.

## Reference

- [召回引擎](../../docs/algorithms/recall-engine.md) — 6+1 factor scoring, goal boost mechanics
- [衰减系统](../../docs/algorithms/decay-system.md) — importance + access_count + decay
- [召回与注入](../../docs/usage/recall.md) — hook auto-inject + tunable env (FLOOR / TOPN / MINLEN / COOLDOWN)
