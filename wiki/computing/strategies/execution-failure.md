---
title: Execution-Failure Conventions
area: autpilot
source: auto-promote
last_verified: '2026-06-28'
type: strategy
status: active
importance: 0.7
confidence: 0.8
created: '2026-06-28'
pinned: false
archived: false
access_count: 0
---

# Execution-Failure Conventions

> Auto-promoted from 3 learnings. Source: 20260628-phantom-executions-without-artifacts, 20260626-missing-artifacts-after-execution, 20260627-phantom-executions-without-artifacts.

## Phantom Executions Without Artifacts
Multiple goal executions completed but generated no detectable artifacts like files, PRs, or branches. This recurring warning indicates a pattern of silent failures or misaligned success criteria in the execution pipeline that requires log verification.

## Missing Artifacts After Execution
Multiple goal executions completed without generating any detectable artifacts like files, PRs, or branches. This indicates a recurring mistake where the agent fails to properly commit or output the expected results, triggering system warnings.

## Phantom Executions Without Artifacts
Multiple goal executions completed without generating any tangible artifacts such as files, PRs, or branches. This pattern indicates silent failures or misconfigured success criteria that require log verification.
