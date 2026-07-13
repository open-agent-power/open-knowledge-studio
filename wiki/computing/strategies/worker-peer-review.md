---
title: Worker 同行评审 — Verification = 另一个 Worker
tags:
- verification
- peer-review
- worker
- pr
- loop-engineering
type: strategy
status: active
importance: 0.7
confidence: 0.919
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---



# Worker 同行评审

## 核心原则

**Verification 不需要换个模型，换一个 Worker 就行。**

同一个 Claude，但上下文不同（Worker B 看不到 Worker A 的推理过程），自然不会"自己批自己"。

## 流程

```
Worker A: 执行 goal → 写代码/知识 → 提 PR
Worker B: review PR → 查重、质量、准确性 → 同意/打回
Human:   最终确认（留一扇门）
```

## 两种场景

### 1. 代码 PR 评审

```
Manager 派发 goal → Worker A 执行 → 创建 PR
  → Manager 派发 review goal → Worker B 认领
  → Worker B: gh pr review + 检查 CI + 读代码
  → 同意 → auto-merge 或 human merge
  → 打回 → 反馈写到 PR comment → Worker A 修改
```

### 2. 知识库 PR 评审

```
Manager/Studio 产出 learning/domain → 提 PR 到 autpilot-knowledge
  → Manager 派发 review goal → Worker B 认领
  → Worker B: 查重（grep domain/）、质量评分、准确性验证
  → 同意 → merge PR
  → 打回 → 反馈 → 修改后重新提
```

## 为什么不需要不同模型

Loop Engineering 原文建议用"更快更小的独立模型"做 Evaluator。
但实际验证发现：

1. **同一模型 + 不同上下文 = 不同判断**
   - Worker A 上下文：执行过程的完整推理（容易自我说服）
   - Worker B 上下文：只看输出 + 验收标准（客观判断）
   
2. **Worker 天然隔离**
   - 不同 daemon 实例
   - 不同 workspace
   - 不同 session
   - 不共享执行日志

3. **简单 = 可靠**
   - 不需要维护两个模型配置
   - 不需要 Evaluator 专门的 API key
   - 复用现有 Worker daemon 架构

## autpilot 实现路径

1. Worker A 完成 goal → 创建 PR
2. Manager 检测到 PR 创建 → 自动创建 review goal
3. Review goal 派发给 Worker B（或空闲的 Worker）
4. Worker B 执行 review goal：
   - `gh pr diff <PR>`
   - `gh pr checks <PR>`（验证 CI）
   - 读 PR 代码
   - 输出：approve / request_changes + 具体反馈
5. Worker B 通过 `gh pr review --approve` 或 `--request-changes` 提交评审
6. 如果 approve → auto-merge（或等 human）
7. 如果 request_changes → Worker A 收到通知 → 修改 → 重新 push

## 与 GitHub 原生功能的结合

- GitHub PR review = 原生同行评审 UI
- GitHub CI checks = 硬编码验证（Stripe 模式）
- GitHub merge = 确定性操作
- autpilot Worker = LLM 评审（补充 CI 无法覆盖的语义问题）

三层验证：
```
Layer 1: CI checks（硬编码，确定性）
Layer 2: Worker B review（LLM，语义审查）
Layer 3: Human approval（最终确认）
```

## 来源

- Anthropic Loop Engineering 报告中的 Generator/Evaluator 分离概念
- 用户实践洞察："Verification 其实就是 worker，让某个 worker 作为评判官即可"
