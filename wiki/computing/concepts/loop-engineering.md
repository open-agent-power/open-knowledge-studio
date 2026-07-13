---
title: Loop Engineering — Anthropic 方法论
date: 2026-06-28
category: foundation
type: foundation
tags: [loop-engineering, ai-native, architecture, methodology]
importance: 1.0
status: active
confidence: 0.95
confidence_reason: "Anthropic 官方工程师报告 + Stripe 生产案例验证"
ttl_days: 365
---

# Loop Engineering

> 替换你自己作为给 Agent 下指令的人，转而去设计一个能自动完成这件事的系统。

## 四层栈

Prompt → Context → Harness → **Loop**

Loop 层新增：定时运行、派生助手、自我喂养。

## 五步动作

1. **Discovery** — 自主发现本轮任务（Manager review）
2. **Handoff** — 隔离交给 Agent（workspace 隔离）
3. **Verification** — 独立 Agent 说"不"（TODO: 独立 Evaluator）
4. **Persistence** — 写到对话之外（learnings + domain + git）
5. **Scheduling** — 自动循环（定时 goal）

## 五种失败模式

| 跳过 | 失败 | autpilot 对策 |
|------|------|-------------|
| Verification | Nodding Loop | acceptance-review skill（需升级为独立模型） |
| Persistence | Amnesiac Loop | learnings 持久化 + domain 晋升 |
| Scheduling | Manual Loop | 定时 goal + scheduler |
| Discovery | Blind Loop | Manager review 自动分析差距 |
| Handoff | Tangled Loop | workspace 隔离 + CLAUDE.md 安全规则 |

## Generator/Evaluator 分离

Agent 不能评判自己的代码。需要独立 Evaluator：
- 默认怀疑
- 通过行动验证（非阅读判断）
- 全新模型执行裁决

## Stripe 案例

1,300 PR/周。确定性门控 + LLM 交错：
- 硬编码：编排器、linter、commit（不交给概率模型）
- LLM：只在写代码和修 lint 两个点
- "cattle not pets" — 千级 Agent 并行

## autpilot 现状对标

| 组件 | Loop Engineering | autpilot 实现 | 状态 |
|------|-----------------|-------------|------|
| Automations | 定时调度 | 定时 goal + scheduler | ✅ |
| Worktrees | 隔离目录 | workspace 隔离 | ✅ |
| Skills | 项目知识 | autpilot-coding/research | ✅ |
| Connectors | MCP 挂钩 | MCP tools + knowledge repo | ✅ |
| Sub-agents | 写/审分离 | acceptance-review（同模型） | ⚠️ |
| Memory | 持久状态 | learnings + domain + .logs | ✅ |

## 安全纪律

1. 每天抽样阅读一个输出
2. 上线前设 token 预算上限
3. 留一个人类检查点

## 来源

- Anthropic 工程师 Prithvi Rajasekaran 报告
- https://mp.weixin.qq.com/s/uTVEAxmfZb7mxCQoE5jLfQ
- Peter Steinberger (OpenClaw), Boris Cherny (Claude Code), Addy Osmani (Google)
