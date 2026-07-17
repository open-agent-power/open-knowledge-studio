---
title: Daily arXiv Paper Scan
type: recipe
trigger: scheduled
schedule: "0 9 * * *"
tools:
  - curl
  - pdftotext
domains:
  - computing
  - AI
keywords:
  - agent
  - self-evolving
  - knowledge management
status: active
---

# Daily arXiv Paper Scan

Scan arXiv for new papers matching team keywords, ingest to raw/,
and triage for drafting.

> **执行方式**：本配方是给 Agent 读的**自动化契约**。`trigger` / `schedule` 只是提示——
> 由**外部调度器**（如 Qoder 自带的定时任务）按 cron 触发，唤起一个 Agent 读本文件、
> 按 Steps 执行。OKS 核心**不内置调度器/执行器**（CONSTITUTION P5）。

## 订阅源

要扫哪些关键词/分类，声明在 `settings/input-sources.json`。其中每条 source 用
`"recipe": "daily-arxiv-scan"` 绑定到本配方——本配方执行时读取该清单里 `enabled: true`
的源作为输入，`raw_path_template` 决定落盘路径。改订阅只改 JSON，不改本配方。

## Steps

1. Query arXiv API for `cs.AI` and `cs.CL` categories with team keywords
2. Download PDFs via `curl`
3. Extract text via `pdftotext`
4. Write to `raw/{YYYY}/{MM}/{DD}/papers/{slug}.md`
5. Run A/B/C triage — A-grade to `drafts/`, B/C skip
6. Report summary: X scanned, Y drafted, Z skipped
