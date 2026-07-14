---
title: 架构设计
nav_order: 11
parent: 内部机制
---
# Architecture（架构）

*五桶架构、记忆生命周期与设计原则。*

## Raw Material vs Memory — 核心区分

| | Raw Material（raw/） | Memory（wiki/） |
|---|---|---|
| **是什么** | 原始文章、论文、仓库笔记或对话 | 持久的结论，经过蒸馏和策划 |
| **谁写入** | 人类收集，LLM 只读 | LLM 通过 Dreaming 写入，人类审批 |
| **衰减** | 无 — raw materials 永久保留 | 类型特定 λ — 知识随时间衰减 |
| **召回** | 关键词 + 新鲜度 | 6 因子相关性 + 记忆曲线 |
| **优势** | 类型化入料（4 子目录）、A/B/C 分级、指纹去重 | 22 域结构、衰减 tier、Crystal 合成 |
| **何时用** | 需要完整历史或精确来源 | 需要模式、决策或教训 |

推荐工作流：将来源保存到 `raw/`，然后将有价值的部分蒸馏为 `wiki/` memory。

## 五桶记忆架构

| 桶 | 用途 | 衰减 | 召回 |
|------|------|------|------|
| `profiles/` | 团队、用户、项目画像 | 无 | 直接读取 |
| `raw/` | Raw materials（原始材料） | 无 | 关键词 + 新鲜度 |
| `wiki/` | 策划知识（memories） | 类型特定 λ | 6 因子召回 |
| `drafts/` | Dreaming 候选 | 无 | N/A（人工审查） |
| `settings/` | 系统配置 | 无 | 直接读取 |

## 目录结构

```
open-knowledge-studio/
├── profiles/          # ① 画像
│   ├── team.md
│   ├── users/{id}.md
│   └── projects/{slug}.md
├── raw/               # ② Raw materials（原始材料）
│   ├── articles/  papers/  repos/  misc/
├── wiki/              # ③ 策划知识（memories）
│   └── {domain}/{type}/{slug}.md
│       # types: concept | strategy | anti-pattern
├── drafts/            # ④ Dreaming 候选
└── settings/          # ⑤ 系统配置
    ├── decay-config.yaml
    └── input-sources.json
```

## 22 个知识域

management, transport, finance, production, computing, repair, engineering, construction, science, agriculture, social, administration, legal, sales, education, personal, media, healthcare, care, maintenance, food, security

每个域有三个子目录：`concepts/`、`strategies/`、`anti-patterns/`。

## 记忆生命周期

```
Observe → Write → Store → Retrieve → Inject → Forget
```

1. **Observe（观察）** — 对话、工具结果、trace、反馈
2. **Decide to write（决定写入）** — 高置信度、可复用、有来源标注
3. **Store（存储）** — 按类型写入对应桶
4. **Retrieve（检索）** — 先 scope（workspace → topic → goal → time），再关键词搜索
5. **Inject（注入）** — 分层注入，稳定层在前（KV Cache 友好），带来源标签
6. **Update/Forget（更新/遗忘）** — 标记 stale，重新评分，归档

## Wiki 页面生命周期

```
Provisional → Active（access_count ≥ 3）→ Dropped（score < threshold）
                                         → Superseded（被新页面替代）
```

### 知识演化关系

当新知识与已有知识产生关联时，系统追踪四种关系：

| 关系 | 含义 | 对旧页面的影响 |
|------|------|-----------------|
| `supersedes` | 新页面替代旧页面 | 标记 `superseded`，从召回中排除 |
| `enriches` | 新页面补充旧页面 | 两者保持 active，互相链接 |
| `confirms` | 新页面验证旧页面 | 旧页面 confidence 提升 |
| `challenges` | 新页面与旧页面矛盾 | 旧页面标记 `[stale]` 待复查 |

### Crystal — 合成参考文章

当 3+ 条 memory 共享同一标签且 score > 0.5 时，系统将它们合成为一篇参考文章 — **Crystal**。来源被引用。当后续保存相关信息时，Crystal 自动更新。

### Working Memory — 每日简报

每天，Studio 可以从近期和高重要性的 memories 中生成一份简报。这份工作记忆文件为 Claude Code 提供关于你当前工作的上下文 — 在你说任何话之前。

## 设计原则

- **Git IS the migration** — 无数据库，schema 变更通过 `_meta/` 版本化
- **Atomic writes** — 所有持久化写入使用 `mkstemp + fsync + os.replace`
- **Human-gated** — 系统绝不未经人工审查就将 raw 内容提升到 wiki
- **No AI configuration** — Claude Code 是 AI 引擎，CLI 只负责文件操作 + 召回评分

## 下一步

* **[召回引擎](recall-engine.md)**：6 因子评分算法
* **[记忆模型](memory-model.md)**：六型记忆与注入顺序
* **[Dreaming 循环](dreaming-cycle.md)**：知识演化管线
