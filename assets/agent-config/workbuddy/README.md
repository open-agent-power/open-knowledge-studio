# WorkBuddy host adapter

`oks init` materializes this guidance in both `<knowledge-base>/.codebuddy/`
and `<knowledge-base>/.workbuddy/`. `oks skills-install` adds the dedicated
`oks-knowledge` Skill to `.codebuddy/` without installing the general
write-capable Skill set. WorkBuddy project Skills are discovered from
`.codebuddy/`; `.workbuddy/` is retained as a compatibility directory.

## Agent-native read workflow

`skills/oks-knowledge/SKILL.md` is the WorkBuddy adapter's primary surface. In
a local WorkBuddy task where `oks` is on `PATH` and the active OKS
configuration identifies the intended instance, it directs the Agent to:

```powershell
oks recall "<query>" --knowledge-only --format json --limit 3
oks fs read "<oks-uri>" --format json
```

The Agent recalls Wiki knowledge first, selects a hit with non-empty
`human_reviewed_at`, then reads its canonical URI before answering. It cites
the page title and URI, and does not authorize an OKS write operation. No
WorkBuddy-native knowledge-base import or MCP server is required for this
workflow.
