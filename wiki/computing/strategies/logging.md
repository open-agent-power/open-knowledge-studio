---
title: Logging Conventions
area: autpilot
source: auto-promote
last_verified: '2026-06-27'
type: strategy
status: active
importance: 0.7
confidence: 0.8542
created: '2026-06-27'
pinned: false
archived: false
access_count: 0
---




# Logging Conventions

> Auto-promoted from 6 learnings. Source: 20260627-avoid-redundant-artifact-logging-1, 20260627-redundant-artifact-url-logging, 20260627-redundant-artifact-url-logging-4, 20260627-avoid-redundant-artifact-logging, 20260627-detect-redundant-output-loops.

## Avoid Redundant Artifact Logging
Repeatedly outputting the exact same local artifact URL across multiple consecutive executions suggests a stuck retry loop or redundant state reporting. Pipelines should track state changes to prevent spamming identical logs.

## Redundant Artifact URL Logging
Several executions repeatedly output the exact same localhost artifact URL for the test report. This redundancy clutters the logs and suggests a need to optimize how artifact links are reported during continuous or scheduled runs.

## Redundant Artifact URL Logging
Several executions repeatedly output the exact same localhost artifact URL for the scheduled goal test report. This suggests a looping behavior or redundant logging mechanism that should be optimized to reduce noise.

## Avoid Redundant Artifact Logging
Repeatedly logging the same localhost artifact URL across multiple consecutive executions indicates redundant output. Consolidating or deduplicating these logs will improve readability and reduce noise in the execution history.

## Detect Redundant Output Loops
Repeatedly outputting the exact same local artifact URLs across multiple execution steps suggests a potential loop or redundant logging issue. Systems should detect and suppress duplicate outputs to keep logs clean and meaningful.
