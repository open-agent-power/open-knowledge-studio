---
title: Daemon-Runtime Conventions
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

# Daemon-Runtime Conventions

> Auto-promoted from 5 learnings. Source: 20260627-daemon-runtime-dispatch-flow-verification-2, 20260627-remote-dispatch-flow-verification-1, 20260627-daemon-runtime-dispatch-flow-verification, 20260627-daemon-runtime-dispatch-flow-verification-1, 20260627-remote-dispatch-flow-verification.

## Daemon Runtime Dispatch Flow Verification
Testing confirmed that the AssembleStage correctly identifies the target field to flag remote execution, successfully routing tasks to the RemoteStage. This validates the core dispatch logic and configuration of the hybrid execution pipeline.

## Daemon Runtime Dispatch Flow Verification
Testing confirmed the daemon runtime's dispatch flow, specifically how the AssembleStage correctly identifies remote targets and routes them to the RemoteStage. This validates the architectural design for remote goal execution pipelines.

## Daemon Runtime Dispatch Flow Verification
A successful test confirmed that the AssembleStage correctly identifies the target field and sets the remote execution flag. This validates the reliability of the dispatch flow for routing tasks to the RemoteStage in the daemon runtime.

## Remote Dispatch Flow Verification
The daemon runtime successfully routes remote goals by detecting the 'target' field in the AssembleStage and setting 'is_remote = true'. This confirms the reliability of the dispatch pipeline for distinguishing and handling remote versus local executions.

## Remote Dispatch Flow Verification
The daemon runtime successfully routes remote tasks by using the AssembleStage to detect the 'target' field and set the 'is_remote' flag to true. This pattern confirms the correct dispatch flow and routing logic for remote goal execution.
