# Open Knowledge Studio

> 你的 AI 工具不会替你记住工作内容。Open Knowledge Studio 会。

它是你的 AI 工作记忆层。保存一个决策、一个洞察、一个有用的来源、或一段对话。Studio 让它可搜索，把它和你已有的知识连接起来，让 Claude Code 从同样的上下文开始工作。

你不需要一次性配置所有东西。先保存一条知识，再找到它，然后让 Claude Code 用它。一旦这个循环跑通，Studio 就变得容易理解了。

最短路径：

1. [搭建仓库](start-here.md)
2. [保存第一条知识](memories.md)
3. [连接 Claude Code](start-here.md#连接-claude-code)
4. [验证召回是否工作](start-here.md#验收标准)

## 核心管线

```
raw/（人类收集的原始材料）
  ↓ /ingest — AI 分级 A/B/C
drafts/（中间态草稿）
  ↓ /promote — 人工审查
wiki/（策展知识，带衰减）
  ↓ oks search / /query — 6 因子召回
注入 Claude Code 上下文
```

## 文档导航

| 页面 | 内容 |
|------|------|
| **[快速开始](start-here.md)** | 最短可用路径：保存一条 → 搜索到它 → 验证工作 |
| **[Memories](memories.md)** | wiki 页面结构、类型、创建路径和搜索模式 |
| **[Raw Materials](raw-materials.md)** | 原始材料层、A/B/C 分级、蒸馏工作流和导入格式 |
| **[架构设计](architecture.md)** | 五桶结构 + 记忆生命周期 |
| **[召回引擎](recall-engine.md)** | 6 因子评分：token overlap + substring + topic trace + type boost + review penalty + memory curve |
| **[记忆模型](memory-model.md)** | 六型记忆、注入顺序（稳定层在前）、来源标签、冲突优先级 |
| **[Dreaming 循环](dreaming-cycle.md)** | 知识演化：collect → dream → drafts → review → promote → decay → evolve |
| **[衰减系统](decay-system.md)** | 记忆曲线、类型特定 λ、tier 分级（hot/warm/cold/evictable） |
| **[Frontmatter Schema](frontmatter-schema.md)** | YAML 元数据规范 v0.7 |

## 快速开始

```bash
git clone <repo-url> open-knowledge-studio
cd open-knowledge-studio
./setup.sh
oks status
oks search "your query"
```

## 设计哲学

- **Raw Material vs Memory** — raw/ 有类型化入料（4 子目录）、A/B/C 分级、指纹去重；wiki/ 有 22 域结构、衰减 tier、Crystal 合成。模式重要时才蒸馏，不必每次都蒸馏。
- **人工审批** — 系统绝不在未经审查的情况下将 raw 内容提升到 wiki。
- **Knowledge as Code** — 所有知识以 Markdown + YAML frontmatter 存储，通过 Git 版本管理。
- **衰减是特性** — 知识随时间遗忘。常用的知识保持敏锐，被遗忘的知识淡入归档。
- **第一天少做** — 保存一条记忆，跑一次搜索，验证它工作。不要一次性配置所有东西。
