---
title: 备份与导出
nav_order: 6
parent: 日常任务
---
# 备份与导出

## git（主机制）

独立知识库实例用 Git 保存材料、知识和修改历史。先检查本地变更并提交，需要远端备份或多设备交换时，再按你的仓库流程同步。知识库没有需要单独迁移的核心数据库，召回索引可从知识文件重建。

## OKF 导出

把 `wiki/` 导出成可移植的知识包，给其他工具读（Obsidian / Logseq / 任何 markdown reader）：

```bash
oks wiki export --format okf --output <dir>        # 开放标准，标准 markdown 链接
oks wiki export --format markdown --output <dir>  # Obsidian [[wikilink]]
```

- `okf` — 标准 markdown 链接 + OKF frontmatter（`type`, `concept-id`）
- `markdown` — Obsidian `[[wikilink]]` + 原始 frontmatter

A4 关系（`relates_to` + `relationship`）改写成正文链接。生成 per-type `index.md` + 顶层 `index.md` + `log.md`（OKF reserved files）。

导出结果是快照。外部工具的改动不会自动写回 OKS。
