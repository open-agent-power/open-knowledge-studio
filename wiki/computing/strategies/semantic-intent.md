---
title: Semantic Intent — 读 test 理解设计意图
tags:
- code-review
- test
- semantic
- strategy
area: computing
source: learnings/2026/06/26/20260626-pr-feedback-comprehensive-retrospective
type: strategy
status: active
importance: 0.7
confidence: 0.85
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# Semantic Intent

## 招式

变量名 / 函数名"听起来"像什么，不代表它"实际"做什么。
改之前先读 test — test 的 assert 和注释记录了真实设计意图。

## 执行步骤

```
1. 找到引用目标变量/函数的 test 文件
2. 读 test 名称和 assert — 它在验证什么？
3. 读 test 注释 — 有没有 "this is intentional because..." 之类的话？
4. 如果 test assert 当前行为 → 行为是 intentional → 不能改
```

## 实战案例

**browser-use #5106**：`step_interval` 听起来是"步与步之间的间隔"，但 test `test_step_interval_calculation` 注释写的是 "uses previous step's total duration (including LLM time)"。这是 replay 系统的设计，不是 bug。PR 改成了"间隔"，被关闭。

## 反模式

- 变量名"看起来有 typo"就改 → 可能是 intentional 命名
- "这个逻辑看起来不对"就改 → 先读 test
- test 只看 pass/fail 不看注释 → 错过设计意图

## 检查

```bash
# 找引用目标变量的 test
grep -rn "variable_name" tests/ --include="*.py" --include="*.ts" --include="*.java"
# 读 test 注释
grep -B5 -A5 "variable_name" tests/ --include="*.py" | grep -E "#|//|\"\"\""
```

## 关联

- Design Check：`design-check.md`
