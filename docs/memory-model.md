# Six-Type Memory Model（六型记忆模型）

## 记忆类型

| 类型 | 存储 | 召回 | 衰减 | Scope |
|------|------|------|------|-------|
| User Memory | `profiles/users/{id}.md` | 直接读取 | 无 | `user_id` |
| Project Memory | `profiles/projects/{slug}.md` | 直接读取 | 无 | `project_slug` |
| Episodic Memory | `raw/{date}/{topic}/` | 关键词 + 新鲜度 | 无 | `topic_id` |
| Semantic Memory | `wiki/{domain}/{type}/` | 6 因子 + 曲线 | 类型 λ | `domain` |
| Procedural Memory | `.claude/skills/` | 关键词触发 | 无 | — |
| Draft Memory | `drafts/{slug}.md` | N/A | 无 | N/A |

## 桶映射

- User/Project → `profiles/`
- Episodic → `raw/`
- Semantic → `wiki/`
- Draft → `drafts/`
- Procedural → `.claude/skills/`（由 Claude Code 管理）

## 注入顺序（稳定层在前，KV Cache 友好）

1. System Prompt（稳定）
2. Team Profile + North Star（稳定，profiles/）
3. Project Memory（稳定，profiles/）
4. Tool Schema + Skills（半稳定，.claude/skills/）
   ─── KV Cache 断点 ───
5. Recalled Semantic Memory（每查询，wiki/）
6. Recalled Episodic Memory（每查询，raw/）
7. User Preferences（可变，profiles/）

## 来源标签

- `[verified]` — 工具确认或人工审查
- `[user-stated]` — 用户明确陈述
- `[inferred]` — AI 蒸馏，尚未验证
- `[stale]` — 可能过时

## 冲突优先级

```
当前用户指令 > 工具验证事实 > 近期用户偏好 > 旧记忆 > 模型推理
```

当记忆与记忆之间产生矛盾时，按此优先级决定信任谁。当前用户的直接指令始终最高，模型自己的推理最低 — 因为我们信任人类判断和工具确认的事实胜过 AI 的推断。
