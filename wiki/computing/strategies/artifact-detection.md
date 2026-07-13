---
title: Artifact-Detection Conventions
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

# Artifact-Detection Conventions

> Auto-promoted from 3 learnings. Source: 20260627-artifact-detection-false-negatives, 20260627-false-completion-detection, 20260627-silent-failures-in-artifact-detection.

## Artifact Detection False Negatives
The system frequently reports successful execution but fails to detect generated artifacts like files, PRs, or branches. This indicates a flaw in the post-execution verification mechanism or silent failures during the generation process that require manual log inspection.

## False Completion Detection
Multiple executions reported completion without generating any detectable artifacts like files, PRs, or branches. The system needs robust artifact verification to prevent false positives and ensure goals are genuinely achieved.

## Silent Failures in Artifact Detection
Multiple executions reported completion but failed to detect any artifacts like files, PRs, or branches. This pattern indicates a potential flaw in the artifact detection logic or silent failures during the execution phase that require log verification.
