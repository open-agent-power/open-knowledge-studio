---
title: Recall
nav_order: 3
parent: 使用 OKS
---
# Recall

`oks recall` 是唯一召回入口：默认合并 Raw episodic 与 Wiki knowledge 两条路径。

```bash
oks recall "查询"
oks recall "查询" --knowledge-only
oks recall "查询" --explain --format json
```

召回本身只读。真正使用某个 Wiki 页面后，可以显式记录：

```bash
oks wiki use <slug>
```

评分细节见[召回引擎](recall-engine.md)。

## 收录前也要 Recall

Recall 不只用于找回旧知识。Agent 在收录新来源前会先查同一主题，判断新 Candidate
是新增，还是对已有页面的 `enriches`、`supersedes`、`confirms`、`challenges`。
这样可以减少同一主题的平行页面。

## 导出 Wiki 快照

需要把人工批准的 Wiki 带到其他 Markdown 工具时，可以导出单向快照：

```bash
oks wiki export --output wiki-export --format okf
oks wiki export --output wiki-export --format markdown
```

`okf` 使用标准 Markdown 链接；`markdown` 使用 Obsidian 风格 wikilink。导出不是
双向同步，外部修改不会自动写回 OKS。
