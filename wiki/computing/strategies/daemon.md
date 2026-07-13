---
title: Daemon Conventions
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

# Daemon Conventions

> Auto-promoted from 27 learnings. Source: 20260626-successful-remote-dispatch-flow-verification, 20260626-daemon-runtime-dispatch-verification, 20260626-successful-daemon-dispatch-flow-verification, 20260626-successful-daemon-runtime-dispatch-flow, 20260626-daemon-dispatch-flow-validation.

## Daemon Runtime Dispatch Validation
The daemon runtime successfully validated its dispatch flow, confirming that the AssembleStage correctly identifies the target field and sets the remote execution flag. This proves the core routing logic for remote goals is functioning exactly as designed.

## Daemon Remote Dispatch Mechanism
The daemon runtime handles remote goal dispatch by using the AssembleStage to detect a 'target' field, which subsequently sets 'is_remote = true'. Understanding this flow is crucial for debugging and configuring remote execution pipelines.

## Daemon Runtime Verification
The daemon runtime successfully handled a test goal, verifying that the dispatch flow correctly sets 'is_remote = true' when a target field is detected during the AssembleStage.

## Daemon Runtime Dispatch Flow Verification
The daemon runtime goal test successfully verified the dispatch flow, confirming that the AssembleStage correctly detects the target field and sets the remote execution flag. This insight validates the reliability of the remote task routing mechanism.

## Remote Dispatch Flow Validation
The daemon runtime test successfully verified the dispatch flow, confirming that the AssembleStage correctly detects the target field and sets the is_remote flag. This proves the foundational logic for routing remote goals is functioning as designed.
