---
title: 导入已有对话
nav_order: 5
parent: 开始使用
---
# 导入已有对话

AI 对话（Claude Code / Cursor / Codex / ChatGPT 导出）在 OKS 里是一等公民的来源。用 `/archive` 把对话存入 `raw/conversations/`，提炼 Q&A 到 `drafts/`。

## 流程

1. 会话结束前跑 `/archive`
2. `/archive` 存对话原文到 `raw/conversations/{YYYY}/{MM}/{DD}/{source}/`（episodic 记录，`[untrusted-source]`）
3. `/archive` 提炼 Q&A 到 `drafts/`，等人审（`/promote`）→ `wiki/`

捕获与提炼是分开的两层——对话原文是材料，提炼出的结论走人审。详见 [对话](usage/conversations.md)。

## 手动导入外部对话

ChatGPT / DeepSeek 导出的 `.md`：`oks ingest run <file>`（text_ready 路径）→ Raw Bundle 落到 `raw/{date}/{source}/`。外部对话和 oks 内对话走同一条 episodic 路径。
