---
title: Execution Conventions
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

# Execution Conventions

> Auto-promoted from 44 learnings. Source: 20260626-artifact-detection-blindspots, 20260626-missing-artifacts-detection-failure, 20260626-reliable-artifact-generation-for-specific-tasks, 20260626-missing-artifacts-in-goal-execution, 20260626-silent-failures-in-goal-execution.

## Silent Failures in Goal Execution
Multiple goal executions completed without generating any artifacts such as files, PRs, or branches. This highlights a critical need for better error handling and validation to ensure goals actually achieve their intended outcomes before being marked as complete.

## False Completions Due to Missing Artifacts
Multiple goal executions reported completion without generating any files, PRs, or branches. This indicates a flaw in the artifact tracking or validation mechanism, leading to false positives in task success.

## Missing Artifacts in Goal Execution
Multiple goal executions completed without generating detectable artifacts like files, PRs, or branches. This recurring issue indicates a potential flaw in the execution logic, artifact tracking, or goal definitions, requiring log analysis to verify actual completion.

## Silent Execution Failures with No Artifacts
Goal executions can complete without errors yet produce zero detectable artifacts (no files, PRs, or branches). This pattern of silent failure occurred repeatedly (executions #18, #19, #20), indicating that success reporting does not guarantee actual deliverables. Always verify outputs independently

## 目标执行必须验证实际产物
多次执行报告完成但未检测到任何文件、PR或分支，说明成功不能仅依赖过程状态，必须通过产物检查确认目标真正达成。
