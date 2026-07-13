---
title: OSS Competition Strategy — 从开环提交到闭环数据驱动
tags:
- competition
- oss
- evolution
- strategy
area: computing
source: session/competition-2026
last_verified: '2026-07-06'
type: strategy
status: active
importance: 0.7
confidence: 0.9113
created: '2026-07-06'
pinned: false
archived: false
access_count: 0
---






# OSS Competition Strategy — 系统演进

How the open-source contribution approach evolved from **open-loop**
(submit blindly, hope for merge) to **closed-loop** (data-driven silent merge
pattern with hard gates). Each stage's problem, decision, and trade-off is
recorded so future iterations don't re-walk the same path.

The tactical shortcuts extracted from this evolution live in
`strategies/oss-competition/` — this file is the narrative that ties them
together.

---

## Stage 1 — Open-Loop: Naive Submission (2026-06)

**Initial state.** Saw 4 competition projects (agentUniverse, Higress, OSS
Compass, RocketMQ). Picked issues by gut feel, wrote fixes, pushed PRs.

**Problem.** 0/5 PRs merged after 2 weeks. Symptoms:
- 2 PRs had competing PRs already open → reviewer closed as duplicate
- 1 PR >100 lines → reviewer asked to split, never re-reviewed
- 1 PR hit Apache CLA `action_required` → waited 2 weeks for first response
- 1 PR had "顺手 cleanup" → reviewer rejected scope creep

**Decision.** Stop. Run a retrospective on all 12 PRs from the first batch.

**Trade-off.** Lost 2 weeks of submission time. Gained the data that drove
every later decision.

---

## Stage 2 — Closing the Loop: Data-Driven PR Sizing (2026-06-20)

**Problem.** No idea what made a PR mergeable. Was it the repo? The size? The
tone? The CI?

**Decision.** Categorize all 12 first-batch PRs by size, scope, tone, and
outcome. Look for the pattern.

**Finding — Silent Merge Pattern.** The 6 merged PRs shared one signature:

| Characteristic | Merged (6) | Rejected (6) |
|----------------|------------|--------------|
| Lines changed | ≤40 | 40-300 |
| Files touched | 1 | 2-5 |
| Scope | 1 issue | issue + cleanup |
| Title verb | `fix` matched diff | `refactor` / `improve` vague |
| Evidence | data or screenshot | prose claim |
| Tone | conversational | formal / defensive |

**≤40-line PRs merged at 75%. >100-line PRs merged at 0%.** This became the
north-star metric.

**Closure.** Encode the pattern as a checklist applied to every PR before
submit. See `strategies/oss-competition/pr-merge-patterns.md`.

**Trade-off.** Smaller PRs mean smaller fixes mean lower per-PR impact. We
traded "one impressive PR" for "many silent merges" — in a competition scored
by merged count, this is correct.

---

## Stage 3 — Hard Gates: Killing Duplicate-PR Waste (2026-06-25)

**Problem.** 2/12 PRs were rejected because someone else had already opened a
PR for the same issue. Wasted 2 days of coding.

**Decision.** Before touching any issue, run competing-PR check:

```bash
gh pr list --repo OWNER/REPO --search "ISSUE_NUMBER" --state all
```

**Closure.** This became **Gate 1** of the pre-submission checklist. If ANY
open PR exists → STOP, review the existing PR instead of writing a new one.

**Trade-off.** Sometimes the existing PR is stale (30+ days no activity). We
chose to comment-and-nudge rather than compete — costs a few days but avoids
"two PRs, neither merged" deadlock.

---

## Stage 4 — Risk Spreading: Don't Bet on One Repo (2026-07-01)

**Problem.** Put 70% effort into RocketMQ (Apache). Review cycle 1-4 weeks.
By the time feedback arrived, 2 weeks were gone with 0 merges.

**Decision.** Spread across all 4 projects by review speed:

| Project | Allocation | Rationale |
|---------|-----------|-----------|
| agentUniverse | 30% | Python, 1-2 week review, known gotchas |
| OSS Compass | 30% | Python/TS, 3 repos = more surface |
| Higress | 20% | Go/Java, CLA required, fewer easy issues |
| RocketMQ | 20% | Apache, 1-4 week review — submit early |

**Closure.** See `strategies/oss-competition/risk-spreading.md`.

**Trade-off.** Context-switching across 4 repos costs ~15% efficiency per
switch. We accept it because a single repo going stale no longer sinks the
whole competition.

---

## Stage 5 — Timing: Apache Lead Time (2026-07-04)

**Problem.** Apache first-time-contributor PRs sit in `action_required` for
1-3 days before a maintainer even approves CI. Reviewers respond in 1-2 weeks.
Merge happens 1-7 days after approval. Total: 2-4 weeks minimum.

**Decision.** For a 2026-09-20 deadline:
- Apache PRs: submit by **08-15** (5 weeks buffer)
- Non-Apache PRs: submit by **09-06** (2 weeks buffer)

**Closure.** See `strategies/oss-competition/timing-strategy.md`.

**Trade-off.** Submitting Apache PRs early means less time to find good
issues. We accept lower issue quality on Apache early submissions because
review speed matters more than issue fit.

---

## Stage 6 — Closed-Loop: 6 Hard Gates (2026-07-06)

**Final state.** Every PR now passes through 6 hard gates before submission:

| Gate | Check | Failure Action |
|------|-------|---------------|
| 1 | Competing PR exists? | STOP, review existing |
| 2 | Knowledge base consulted? | Read relevant strategy/fix |
| 3 | Co-author / AI attribution? | Add if applicable |
| 4 | Breaking change search + smoke? | `grep -rn OLD_ID` + instantiate |
| 5 | PR body matches template? | Rewrite |
| 6 | PR template applied? | Re-check repo `.github/` |

The loop is now closed:
```
scan issues (Gate 1)
  → score fixability (repo-selection.md)
  → write ≤40-line fix (pr-merge-patterns.md)
  → hard gates 2-6 (pre-submission-checklist.md)
  → submit (timing-strategy.md)
  → monitor CI (ci-triage.md)
  → respond to review within 24h
  → merged? → eval-contribution → learning → promote to domain
  → rejected? → learning → update strategy
```

**What changed from open-loop.**
- Submission is no longer "push and pray" — it's gated by data.
- Repo selection is no longer "what looks interesting" — it's scored.
- Timing is no longer "when I feel like it" — it's deadline-driven.
- Failure is no longer "try again differently" — it feeds a learning that
  updates the strategy.

---

## Stage 7 — Post-Submission Monitoring Gap (2026-07-07)

**Problem.** PR #10532 (RocketMQ) submitted 06-19, AI bot APPROVED. A
competing PR #10422 was submitted and merged 1 day later (06-20). We didn't
discover this until 07-07 — **17 days of waiting on a dead PR.**

**Root cause.** The Stage 6 loop diagram said "monitor CI" but:
- No monitoring frequency defined (when to check?)
- No competing-PR check post-submission (only pre-submission Gate 1)
- No issue-status check (issue #10421 was closed by #10422)

**Decision.** Add post-submission monitoring protocol:
- 1-3 days post-submit: daily check (CI, mergeable, competing PRs)
- 4-14 days: every 3 days (PR state, issue closed?, competing PRs)
- Alert signals: `CONFLICTING`, issue closed, new competing PR

**Trade-off.** Monitoring has overhead (~5 min/PR/day). We accept it because
the cost of waiting on a dead PR (wasted time, missed opportunities) is far
higher.

**Closure.** See `strategies/oss-competition/timing-strategy.md` → "Post-
Submission Monitoring" section. The loop now has enforcement at the tail:

```
submit
  → monitor (1-3d daily, 4-14d every 3d)
  → CI green? → wait for review
  → CI red? → ci-triage.md
  → CONFLICTING? → check competing PR → close if issue resolved
  → issue closed? → close PR immediately
  → review received? → respond 24h → fix 48h → re-push
  → merged? → eval-contribution → learning → promote
  → rejected/stale? → learning → update strategy → next issue
```

**What changed from Stage 6.** The loop now has a **tail closure** — every
submitted PR has a defined exit condition (merged, closed, or abandoned).
Nothing sits in limbo.

---

## Stage 8 — Repo Activity Gate (2026-07-07)

**Problem.** agentUniverse PRs #598 and #601 submitted 07-05. Two days later:
0 CI checks ran, 0 reviews. Investigation: repo last pushed 2026-04-24 —
**2.5 months stale**. Maintainer appears inactive.

**Root cause.** Repo-selection criteria checked stars, activity, PR count —
but "activity" was never quantified. "最近 7 天有 commit" was the rule, but
agentUniverse was last active 2.5 months ago when PRs were submitted.

**Decision.** Add **repo activity hard gate** to repo-selection.md:
- Last commit must be within 14 days
- If last commit > 30 days → SKIP, do not submit
- Check before EVERY submission, not just initial repo selection

**Trade-off.** Some legitimately good repos may be slow-moving (research
projects). We accept missing those because in a time-limited competition,
waiting on an inactive maintainer is worse than skipping a repo.

**Also discovered**: OSS Compass profile had wrong GitHub org name
(`ossf-compliance` → `oss-compass`). 3 active repos identified, 0 PRs
submitted. This is the biggest untapped opportunity.

---

A loop is closed only if **failure feeds back into the strategy**. Test:

- [ ] Every rejected PR has a `learnings/` entry? — Yes (12 entries so far)
- [ ] Every learning that recurred 2+ times was promoted to `strategies/`? — Yes
- [ ] Every strategy file cites the learning that produced it? — Yes (see `source:` frontmatter)
- [ ] Before each new PR, the relevant strategy is consulted? — Enforced by Gate 2

If any box is unchecked, the loop is still open.

---

## 关联

- Silent Merge 数据：`strategies/oss-competition/pr-merge-patterns.md`
- Repo 选择标准：`strategies/oss-competition/repo-selection.md`
- Timing 决策表：`strategies/oss-competition/timing-strategy.md`
- 风险分散：`strategies/oss-competition/risk-spreading.md`
- Pre-submission 6 gates：`plugins/autpilot-coding/skills/submit-pr/pre-submission-checklist.md`
- PR 失败模式分类：`plugins/autpilot-coding/skills/submit-pr/pr-failure-patterns.md`
