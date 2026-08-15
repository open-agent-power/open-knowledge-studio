---
title: 飞书采集审核闭环
type: goal
owner: example
period: "2026-Q3"
status: draft
domains:
  - computing
keywords:
  - feishu
  - intake
  - review
  - candidate
---

# 示例 Goal：用飞书做日常采集与审核

> 这是一份**可复制的示例**，不是激活状态的 goal。想启用就复制到你实例的
> `profiles/goals/`，把 `status` 改成 `active`、`owner` 改成你自己。
>
> 完整操作步骤见同目录的 [`README.md`](README.md)。

## Objective

把「看到值得存的东西」到「知识进 wiki」的摩擦降到手机上几次点按：
用飞书表单提交来源，worker 自动采集成 Raw Bundle，Agent 起草候选，
人在飞书里回一句话决定接受还是退回。

## 为什么用飞书（而不是直接跑 CLI）

采集的瓶颈从来不是算力，是**人不在电脑前**。刷到一个视频、看到一篇论文，
当下不记就没了。飞书表单解决的正是这个：手机两下提交，剩下的异步跑。

审核环节留在 IM 里同理——碎片时间就能处理，不必打开终端。

## Key Results

- [ ] `python examples/oh-my-feishu/code/feishu_setup.py` 建好 Base，表单能在手机上提交
- [ ] `python examples/oh-my-feishu/code/feishu_base_worker.py run-once` 能把一条待办跑完（认领 → 采集 → Raw 就绪）
- [ ] 收到候选通知后能在飞书回复完成审核，wiki 里出现对应页面
- [ ] 一周内提交 10 条以上，其中 5 条以上晋升为 wiki 页
- [ ] 至少一次退回（`reject` 或 `edit`）——**能退回才说明审核是真的**

## Recall Influence

这个 goal 激活时，`computing` 域与 feishu/intake/review/candidate
相关的 wiki 页在召回中获得加权（宪章 A1 的第 7 因子）。

## 边界

- **人审不可跳过**：worker 只负责机械采集与状态流转，是否进 wiki 由人决定。
  这是宪章 A3 的硬约束，飞书路径不例外。
- **飞书是可选组件**：不配置飞书，`oks ingest` + `oks drafts promote` 的
  CLI 路径同样完整可用。
