# 画像索引

> **用途**：任务上下文，按身份与任务选择读取，不全量注入。
> **Updated**: 2026-07-13

## 目录结构

| 文件 | 用途 | 更新频率 | 加载方式 | Token 预算 |
|------|------|----------|----------|------------|
| `team.md` | 团队画像（技术栈、成员） | 每月 | 仅 frontmatter | ~200 |
| `users/<id>/profile.md` | 个人偏好 | 每季度 | 按需加载 | ~100 |
| `projects/<name>.md` | 项目 onboarding profile | 每次贡献前 | 按需加载 | ~200 |
| `agents/<id>.md` | 团队共享 Agent 角色 | 职责变化时 | 按需加载 | ~200 |

## 日常上下文与运行记录

- `agents/` 保存角色和协作约定；终端绑定位于 `records/registry/terminals.jsonl`。
- `recipes/` 保存场景化输入、步骤和验收配方。
- `goals/YYYY/MM/DD/` 与 `discuss/YYYY/MM/DD/` 保存当日目标和讨论。
- 可共享能力包统一放在根目录 `skills/`；宿主隐藏目录中的 Skill 是安装入口。
- 修订在 `records/timeline/`，三步引导状态在 `records/studio/onboarding.json`。

## Frontmatter 字段规范

**完整 schema 见 `_meta/frontmatter-schema.md` §2.2 (team.md) + §2.3 (users/<id>.md)**。
Agent 档案沿用 profile 层约束，字段见下方“Agent 档案”。

本层差异（profile 层特定）：
- `type` 必须是 `profile`
- `tags` 必含 `team` 或 `user` 前缀
- 默认 `ttl_days: 180`
- `source` 通常是 `setup` 或 `session/<name>`
- profiles 不允许包含 PII / 敏感数据（见下方反模式）

参考现有 user profile 作样板：`users/itxaiohanglover/profile.md`

### Agent 档案

`agents/<id>.md` 是团队共享的角色事实，不是运行时连接、权限授予或在线状态。
只有人或负责操纵 OKS 的 Agent 明确建立/审核后才写入；Mail/Session provenance
不能自动升级为档案。建议 frontmatter：

```yaml
id: reviewer
title: 审核助手
type: profile
profile_kind: agent
role: 候选知识初审
scope: [research, engineering]
status: active # proposed | active | retired
source: human-approved
```

正文补充稳定职责、输入输出和协作边界，不写 token、密钥或机器私有路径。
`agents/_template.md` 只是初始化样板，不能被识别为真实成员档案。

## Distill 规则

### team.md

- **When**: Tech stack changes, new member joins
- **How**: Update via PR
- **Source confidence**: 0.9 (user provided in /setup)

### users/<staff-id>/profile.md

**When to write** (via `/summary` or `/distill summary`):

| 信号 | 初始 confidence | 示例 |
|------|-----------------|------|
| User states preferences directly | 0.9 | "I prefer TypeScript over JavaScript" |
| AI infers from repeated behavior | 0.7 | "User consistently writes TDD style" |
| User corrects AI repeatedly | 0.9 | "No, use pnpm not npm" |

**Body template**:
```markdown
# <name>

## Role
<role>

## Preferences

### Communication
- Style: <concise/detailed>
- Language: <Chinese/English>

### Technical
- Languages: <Python/TypeScript>
- Frameworks: <FastAPI/React>

### Workflow
- Testing: <TDD/after>
- Review: <quick/detailed>
```

## 发现规则

At goal start:
1. Always read: `team.md` frontmatter (~200 tokens)
2. If user identified: Read `users/<id>/profile.md` frontmatter
3. Need details: Grep full file

## 反模式

- No personal info beyond work preferences (privacy)
- No sensitive data
- Max 100 lines per user file
