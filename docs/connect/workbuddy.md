---
title: WorkBuddy Agent workflow
nav_order: 5
parent: 参考
---

# WorkBuddy Agent workflow

WorkBuddy can consume reviewed OKS Wiki knowledge as a local Agent. The
project-local Skill uses the same read-only recall boundary as other OKS hosts:

```text
WorkBuddy local task
  -> oks recall --knowledge-only
  -> oks fs read <oks-uri>
  -> answer with reviewed OKS knowledge and the canonical URI
```

## Install the project Skill

`oks init` materializes both `.codebuddy/` and `.workbuddy/` in a new instance.
WorkBuddy discovers its project Skill from `.codebuddy/`; `.workbuddy/` is
retained as a compatibility directory. Existing instances can add the missing
dedicated Skill without overwriting existing files:

```powershell
oks skills-install
```

The WorkBuddy host Skill is `.codebuddy/skills/oks-knowledge/SKILL.md`. In a
local task with `oks` on `PATH` and `OKS_ROOT` (or the active OKS config)
pointing to the intended instance, it requires reviewed-Wiki recall first and a
canonical URI read before answering.

`--knowledge-only` excludes Raw and episodic material, but can return
provisional Wiki pages. The Skill therefore selects only recall hits with a
non-empty `human_reviewed_at` field before reading their `uri`.

## Safety boundary

The Skill does not authorize Wiki, Raw, Draft, configuration, hook, or mail
writes. It treats Raw material and drafts as non-authoritative, and reports an
absent `oks` command or an empty recall result instead of guessing.

This integration deliberately uses the installed local CLI rather than adding
an MCP server. WorkBuddy-native KnowledgeBase import is not required for Agent
retrieval.
