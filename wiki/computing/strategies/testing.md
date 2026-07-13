---
title: Testing Conventions
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

# Testing Conventions

> Auto-promoted from 7 learnings. Source: 20260626-standardized-test-report-generation, 20260627-test-ai-identity-via-system-prompt, 20260627-validate-daemon-dispatch-flow-1, 20260625-stable-artifact-generation-for-scheduled-tests, 20260625-consistent-generation-of-scheduled-test-reports-1.

## Test AI identity by asserting build_system_prompt output
# Test AI identity via `build_system_prompt()`

## When to use

When verifying that the Discuss AI knows its company identity (team name, app name, core philosophy), test `build_system_prompt()` directly rather than mocking the full discuss/chat flow.

## Pattern

```python
from app.services.discuss

## Validate Daemon Dispatch Flow
Daemon runtime tests successfully verify the dispatch flow, such as the AssembleStage correctly detecting target fields and setting remote execution flags. These tests are crucial for ensuring the underlying pipeline routing logic functions as expected.

## Consistent Generation of Scheduled Test Reports
Several executions successfully and consistently produced a scheduled goal test report artifact. This demonstrates that the artifact generation pipeline is reliable when the goal is explicitly designed for test reporting.

## Standardized Test Report Generation
Successful scheduled goal tests consistently produce a specific artifact, 'scheduled-goal-test-report.md'. This predictable output serves as a reliable baseline for verifying the health and functionality of the scheduling and execution daemon.

## Stable Artifact Generation for Scheduled Tests
Scheduled goal tests consistently succeed in generating the expected markdown report artifacts when the execution pipeline functions correctly. This provides a reliable baseline for verifying artifact tracking and successful execution paths.
