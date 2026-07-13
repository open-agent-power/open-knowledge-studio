---
type: concept
status: active
importance: 0.7
confidence: 0.8
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# 共享领域知识索引

> **用途**：适用于所有 goal 的跨领域通用知识。
> **更新日期**：2026-07-06
> **加载方式**：始终加载（在任何业务领域知识之前）

## 结构

| 子目录 | 内容 | 存什么 |
|--------|------|--------|
| `foundations/` | 跨领域方法论 | 框架级思考（loop engineering、self-evolution） |
| `conventions/` | 跨领域系统演进 | 系统从开环到闭环的完整叙事 |

## 文件列表

### 方法论（Foundations）

> `foundations/` 目录暂无内容。待补充跨域方法论。

### 系统演进（Conventions）

| 文件 | 标题 | 信任度 | 更新日期 |
|------|------|--------|----------|
| `conventions/git-branch-naming.md` | Git 分支命名规范 | 0.9 | 2026-06-04 |
| `conventions/pr-review-protocol.md` | PR review 从无流程到 10 项 checklist | 0.85 | 2026-06-04 |
| `conventions/process-boundary-state.md` | 进程边界模块状态问题 | 0.8 | 2026-06-17 |
| `conventions/shared-constants.md` | 字符串漂移修复策略演进 | 0.8 | 2026-06-17 |
| `conventions/trace-call-chain.md` | 重复清理修复策略演进 | 0.8 | 2026-06-17 |

## 发现规则

**每次** goal 启动时加载 `_shared/` 下所有文件：

```
加载顺序：
1. _shared/foundations/*.md  （方法论框架）
2. _shared/conventions/*.md  （系统演进策略）
```

**预算**：约 500 tokens

## 蒸馏规则

### 何时写入 _shared vs. 业务领域

| 判断问题 | 目标路径 |
|---------|----------|
| 适用于所有业务领域的系统演进？ | `_shared/conventions/` |
| 适用于所有业务领域的方法论？ | `_shared/foundations/` |
| 仅适用于某个领域？ | `<area>/conventions/` 或 `<area>/foundations/` |
| 语言陷阱、how-to、参考表？ | `plugins/fixes/`（不属于 domain） |
| 项目状态、进度？ | `profiles/projects/`（不属于 domain） |
