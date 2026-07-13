# Six-Type Memory Model

## Memory Types

| Type | Storage | Recall | Decay | Scope |
|------|---------|--------|-------|-------|
| User Memory | `profiles/users/{id}.md` | Direct read | None | `user_id` |
| Project Memory | `profiles/projects/{slug}.md` | Direct read | None | `project_slug` |
| Episodic Memory | `raw/{date}/{topic}/` | Keyword + freshness | None | `topic_id` |
| Semantic Memory | `wiki/{domain}/{type}/` | 6-factor + curve | Type λ | `domain` |
| Procedural Memory | `.claude/skills/` | Keyword trigger | None | — |
| Draft Memory | `drafts/{slug}.md` | N/A | None | N/A |

## Bucket Mapping

- User/Project → `profiles/`
- Episodic → `raw/`
- Semantic → `wiki/`
- Draft → `drafts/`
- Procedural → `.claude/skills/`

## Injection Order (stable first, KV Cache friendly)

1. System Prompt (stable)
2. Team Profile + North Star (stable)
3. Project Memory (stable)
4. Tool Schema + Skills (semi-stable)
   ─── KV Cache Break ───
5. Recalled Semantic Memory (per-query)
6. Recalled Episodic Memory (per-query)
7. User Preferences (variable)

## Source Labels

- `[verified]` — tool-confirmed or human-reviewed
- `[user-stated]` — user explicitly stated
- `[inferred]` — AI distilled, unverified
- `[stale]` — possibly outdated

## Conflict Priority

```
current user instruction > tool-verified > recent preference > older memory > model inference
```
