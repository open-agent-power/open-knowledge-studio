# Architecture

## Five-Bucket Memory Architecture

| Bucket | Purpose | Decay | Recall |
|--------|---------|-------|--------|
| `profiles/` | Team, user, project profiles | None | Direct read |
| `raw/` | Raw materials | None | Keyword + freshness |
| `wiki/` | Curated knowledge | Type-specific λ | 6-factor recall |
| `drafts/` | Dreaming candidates | None | N/A (human review) |
| `settings/` | System config | None | Direct read |

## Directory Structure

```
open-knowledge-studio/
├── profiles/          # ① Profiles
│   ├── team.md
│   ├── users/{id}.md
│   └── projects/{slug}.md
├── raw/               # ② Raw materials
│   ├── articles/  papers/  repos/  misc/
├── wiki/              # ③ Curated knowledge
│   └── {domain}/{type}/{slug}.md
├── drafts/            # ④ Dreaming candidates
└── settings/          # ⑤ System config
```

## 22 Knowledge Domains

management, transport, finance, production, computing, repair, engineering, construction, science, agriculture, social, administration, legal, sales, education, personal, media, healthcare, care, maintenance, food, security

Each domain: `concepts/`, `strategies/`, `anti-patterns/`.

## Memory Lifecycle

```
Observe → Write → Store → Retrieve → Inject → Forget
```

1. **Observe** — conversations, tool results, traces, feedback
2. **Decide to write** — high-confidence, reusable, source-annotated
3. **Store** — write to appropriate bucket by type
4. **Retrieve** — scope first, then keyword search
5. **Inject** — layered, stable first (KV Cache), with source labels
6. **Update/Forget** — mark stale, re-score, archive

## Wiki Page Lifecycle

```
Provisional → Active (access_count ≥ 3) → Dropped (score < threshold)
```
