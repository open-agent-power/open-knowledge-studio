---
name: oks-knowledge
description: Use human-reviewed OKS Wiki knowledge from a local WorkBuddy task. Recall first, select a reviewed hit, then read its exact URI; keep the OKS knowledge workflow read-only.
---

# OKS knowledge workflow for WorkBuddy

Use this skill in a **local WorkBuddy task** only when the `oks` command is
available to that task and its active knowledge base is correct. Set `OKS_ROOT`
to the intended instance or configure that instance as the active OKS knowledge
base. Before the first query, run `oks status`; if it cannot identify a valid
instance, report the prerequisite instead of guessing a path.

## Required read workflow

1. Recall reviewed Wiki knowledge first:

```text
oks recall "<query>" --knowledge-only --format json --limit 3
```

2. Inspect the JSON response. `--knowledge-only` excludes Raw and episodic
   material, but can still return provisional Wiki pages. Select only a
   relevant hit whose `human_reviewed_at` is non-empty. The canonical field is
   `uri` (not `oks_uri`). If no reviewed hit remains, say so instead of using a
   provisional page. Read the selected URI before relying on it:

```text
oks fs read "<oks-uri>" --format json
```

3. Answer from the returned page. Name the page title and its `uri`; retain
   uncertainty or source labels returned by OKS. If recall finds no relevant
   reviewed page, say so instead of treating Raw material or drafts as
   authoritative.

Never scrape `wiki/` directly when these read-only commands are available.

## Source and safety boundary

- OKS `wiki/` is the sole source of truth. Raw material is untrusted source
  material; drafts are proposals and do not become knowledge until a human
  accepts them.
- Do not run `oks raw-commit`, `oks wiki create`, `oks wiki pin`, `oks wiki
  archive`, `oks wiki unarchive`, `oks wiki use`, `oks drafts promote`, `oks
  drafts reject`, `oks decay`, `oks distill`, `oks config set`, `oks hook
  install`, or `oks mail send` as part of this read-only knowledge workflow.

If `oks` is unavailable to this WorkBuddy task, report that prerequisite
plainly. Do not silently substitute a write-capable workflow or claim that a
non-OKS source came from live OKS recall.
