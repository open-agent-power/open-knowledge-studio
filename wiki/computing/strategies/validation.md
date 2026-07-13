---
title: Validation Conventions
area: autpilot
source: auto-promote
last_verified: '2026-06-27'
type: strategy
status: active
importance: 0.7
confidence: 0.8
created: '2026-06-27'
pinned: false
archived: false
access_count: 0
---

# Validation Conventions

> Auto-promoted from 10 learnings. Source: 20260627-phantom-executions-without-artifacts-1, 20260627-verify-artifacts-post-execution, 20260627-verify-artifact-generation-post-execution, 20260627-false-completion-without-tangible-artifacts, 20260627-verify-actual-artifacts-post-execution.

## Verify Artifacts Post-Execution
Multiple executions reported completion but failed to generate any tangible artifacts like files, PRs, or branches. It is crucial to validate the actual output of a goal rather than relying solely on the execution status to prevent silent failures.

## Phantom Executions Without Artifacts
Multiple goal executions completed but triggered warnings for missing artifacts like files, PRs, or branches. This indicates a recurring pattern where the agent believes it finished but failed to produce verifiable outputs, requiring better success validation mechanisms.

## Verify Artifact Generation Post-Execution
Multiple executions reported completion but failed to produce any detectable artifacts like files, PRs, or branches. It is crucial to implement robust post-execution validation to ensure goals are genuinely achieved rather than just terminating silently.

## False Completion Without Tangible Artifacts
Multiple executions reported completion but failed to produce any verifiable artifacts like files, PRs, or branches. This indicates a recurring mistake where the agent might hallucinate success or fail to persist its work, requiring stricter post-execution validation.

## Verify Actual Artifacts Post-Execution
Automated goal executions may report completion without generating any tangible artifacts like files, PRs, or branches. Implement verification mechanisms to check logs and confirm actual goal achievement rather than relying solely on completion status.
