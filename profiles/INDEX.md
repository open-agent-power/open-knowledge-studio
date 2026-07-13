# 画像索引

> **用途**：L0 profile 层（对所有 goal 始终可见）。
> **Updated**: 2026-07-13

## 目录结构

| 文件 | 用途 | 更新频率 | 加载方式 | Token 预算 |
|------|------|----------|----------|------------|
| `team.md` | 团队画像（技术栈、成员） | 每月 | 仅 frontmatter | ~200 |
| `users/<id>/profile.md` | 个人偏好 | 每季度 | 按需加载 | ~100 |
| `projects/<name>.md` | 项目 onboarding profile | 每次贡献前 | 按需加载 | ~200 |

## Frontmatter 字段规范

**完整 schema 见 `_meta/frontmatter-schema.md` §2.2 (team.md) + §2.3 (users/<id>.md)**。

本层差异（profile 层特定）：
- `type` 必须是 `profile`
- `tags` 必含 `team` 或 `user` 前缀
- 默认 `ttl_days: 180`
- `source` 通常是 `setup` 或 `session/<name>`
- profiles 不允许包含 PII / 敏感数据（见下方反模式）

参考现有 user profile 作样板：`users/itxaiohanglover/profile.md`

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
