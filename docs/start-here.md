# 快速开始

Open Knowledge Studio 最容易理解的方式是一个循环：

* 保存一条有价值的东西
* 再找到它
* 让 Claude Code 用它

本页是这个循环的最短路径。如果还没安装，先运行 `./setup.sh`。

## Studio 是什么

简单来说，Studio 做三件事：

* 存储你的决策、洞察、来源和对话
* 让它们可搜索、可复用
* 让 Claude Code 从同样的记忆开始工作，而不是每次从零开始

你不需要理解整个系统就能开始用。

## 第一个循环

### Step 1: 保存一条真实知识

写一条你想保留的真实内容：一个决策、一个工作洞察、一个你反复使用的模式。放进 `raw/` 目录：

```bash
cat > raw/misc/my-first-note.md << 'EOF'
## Decision: Use Typer for CLI

We chose Typer over Click because Typer has native type hint support
and integrates with Rich for terminal formatting.
EOF
```

### Step 2: 蒸馏为草稿

用 Claude Code 的 `/ingest` 技能，或运行 CLI：

```bash
oks distill --dry-run  # 预览蒸馏结果（不写入）
```

系统扫描 `raw/`，按 A/B/C 分级，将 A 级材料写入 `drafts/`。

### Step 3: 提升到 wiki

审查草稿并提升：

```bash
oks drafts list           # 查看候选
oks drafts promote <slug> # 提升到 wiki/
```

或在 Claude Code 中用 `/promote` 技能交互式审查。

### Step 4: 确认搜索能找到它

```bash
oks search "CLI framework decision"
```

如果搜索结果反映了你刚保存的内容，循环就跑通了。

### Step 5: 连接 Claude Code

Claude Code 技能预配置在 `.claude/skills/`。核心技能：

| 技能 | 使用场景 |
|------|----------|
| `/query <问题>` | 提问 — Studio 召回相关 wiki 页面并注入上下文 |
| `/ingest` | 将新 raw/ 材料分诊为 drafts |
| `/promote` | 审查 drafts 并提升到 wiki |
| `/status` | 查看知识库概览 |

试一下：

```
/query What did we decide about CLI frameworks?
```

Claude Code 会召回你刚提升的 wiki 页面，并带引用回答。

## 验收标准

以下每一条你都应该能回答"是"：

* 我在 `raw/` 保存了一条原始材料
* 我把它蒸馏为 `drafts/` 中的草稿
* 我把草稿提升到了 `wiki/`
* 我用 `oks search` 搜索到了它
* 在 Claude Code 中，`/query` 召回了我的知识

如果任何一条是"否"，查看下面的验证步骤。

## 验证

### 搜索是否工作

```bash
oks search "your topic"
```

应该返回 `wiki/` 中的结果，带相关性分数。

### 召回是否工作

```bash
oks recall "your topic"
```

应该同时返回 episodic 结果（来自 `raw/`）和 knowledge 结果（来自 `wiki/`）。

### Claude Code 集成是否工作

在 Claude Code 会话中：

```
/query What do I know about <topic>?
```

应该将相关 wiki 页面注入上下文，并带来源标签如 `[verified]` 或 `[inferred]` 回答。

## 第一天少做

保存一条记忆。蒸馏一个草稿。提升一个 wiki 页面。跑一次搜索。停。

第一天的目标是验证循环跑通，不是配置所有域。

## 下一步

* [Memories](memories.md) — wiki 页面结构、类型和搜索
* [Raw Materials](raw-materials.md) — 原始材料、蒸馏工作流和导入格式
* [架构设计](architecture.md) — 五桶结构和记忆生命周期
* [召回引擎](recall-engine.md) — 6 因子评分算法
* [Dreaming 循环](dreaming-cycle.md) — 知识演化管线
