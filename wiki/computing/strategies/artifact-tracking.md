---
title: Artifact-Tracking Conventions
area: computing
source: auto-promote
last_verified: '2026-06-28'
type: strategy
status: active
importance: 0.7
confidence: 0.8542
created: '2026-06-28'
pinned: false
archived: false
access_count: 0
---




# Artifact-Tracking Conventions

> Auto-promoted from 3 learnings. Source: 20260628-handle-executions-with-no-detectable-artifacts, 20260627-handling-missing-execution-artifacts, 20260625-artifact-detection-blindspots.

## Handling Missing Execution Artifacts
Several executions completed without generating expected artifacts such as files, PRs, or branches, resulting in automated warnings. This highlights a recurring issue of silent failures or inadequate validation, requiring log inspection to confirm actual task completion.

## Handle Executions with No Detectable Artifacts
Multiple goal executions completed without generating any detectable artifacts like files, PRs, or branches. This indicates a need for better verification mechanisms to ensure tasks actually produce the expected side effects before marking them as complete.

## Artifact Detection Blindspots
The system frequently flags executions as having no artifacts (files, PRs, branches) even when they might have successfully completed non-code tasks. This indicates a reliance on rigid artifact types, necessitating custom success criteria or log-based verification for diverse goal types.
