---
title: WorkBuddy 接入
nav_order: 7
parent: 参考手册
---

# WorkBuddy 接入

WorkBuddy 可通过本地 Agent Skill 查询 OKS 的已审核知识。调用顺序是：

```text
本地任务 → oks recall --knowledge-only → oks fs read <oks-uri> → 带引用的回答
```

## 准备 Skill

新实例由 `oks init` 物化 `.codebuddy/` 和 `.workbuddy/`。WorkBuddy 从 `.codebuddy/` 发现项目 Skill，`.workbuddy/` 保留为兼容目录。已有实例缺少 Skill 时，可添加而不覆盖现有文件：

```powershell
oks skills-install
```

Skill 位于 `.codebuddy/skills/oks-knowledge/SKILL.md`。确保 `oks` 在 `PATH` 中，且 `OKS_ROOT` 或当前 OKS 配置指向目标知识库。

## 查询与验证

Skill 先召回，再读取 canonical URI 对应的内容。`--knowledge-only` 排除 Raw 与会话材料，但仍可能返回 provisional Wiki，因此 Skill 只选择有 `human_reviewed_at` 的结果。

可以运行只读检查：

```powershell
oks workbuddy doctor --kb-root <知识库路径>
```

## 接入范围

此 Skill 只读，不授权写入 Wiki、Raw、Draft、配置、Hook 或 Mail。命令缺失或未命中时应报告缺口。查询使用本地 CLI，无需新增 MCP Server 或导入 WorkBuddy 原生 KnowledgeBase。
