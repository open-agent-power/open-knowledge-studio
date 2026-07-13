---
title: Performance Conventions
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

# Performance Conventions

> Auto-promoted from 55 learnings. Source: 20260626-high-volatility-in-execution-iterations, 20260626-extreme-variance-in-execution-iterations, 20260626-high-variance-in-execution-iterations-2, 20260626-excessive-iteration-counts-in-goal-execution, 20260626-excessive-iterations-in-complex-goals.

## Execution Iteration Anomalies
Goals completing in thousands of iterations strongly suggest the agent is trapped in a retry loop, facing persistent unhandled errors, or lacking a clear termination condition. Implementing iteration caps and early-exit heuristics is crucial to prevent resource waste.

## Excessive Iteration Counts in Execution
Some goals took over 1000 to 2700 iterations to complete, which strongly suggests inefficiencies, looping behaviors, or getting stuck in retry cycles. Monitoring and capping iteration counts is crucial for optimizing agent runtime and preventing resource exhaustion.

## Excessive Iteration Counts in Execution
Certain goal executions required thousands of iterations to complete, with some exceeding 2700 iterations. This highlights a significant inefficiency or potential infinite loop risk in the execution engine that needs performance profiling and optimization.

## Excessive Iteration Counts in Goal Execution
Certain goals required thousands of iterations to complete, suggesting inefficiencies, infinite loops, or poorly defined goals that cause the agent to struggle and retry excessively.

## 部分任务迭代次数异常过高
部分目标执行需要超过一千至两千多次迭代才能完成。这暗示执行引擎可能存在效率瓶颈、Agent陷入了低效的推理循环或任务拆解粒度不够合理。
