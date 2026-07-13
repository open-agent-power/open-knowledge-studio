# Start Here

Open Knowledge Studio is easiest to understand through one loop:

* save something that matters
* find it again
* let Claude Code use it

This page is the shortest path to that loop. If you have not installed yet, run `./setup.sh` first; everything below assumes the CLI is ready.

## What Studio Is

At its simplest, Studio does three things:

* it stores your decisions, insights, sources, and conversations
* it makes them searchable and reusable later
* it lets Claude Code work from the same memory instead of starting cold

You do not need to understand the whole system before it becomes useful.

## The First Loop

### Step 1: Save One Real Memory

Write one real thing you want to keep: a decision you made, an insight from work, a pattern you repeat. Drop it into `raw/` as a markdown file, or use the CLI:

```bash
cat > raw/misc/my-first-note.md << 'EOF'
## Decision: Use Typer for CLI

We chose Typer over Click because Typer has native type hint support
and integrates with Rich for terminal formatting.
EOF
```

### Step 2: Ingest It Into a Draft

Use the `/ingest` skill in Claude Code, or run:

```bash
oks distill --dry-run  # preview what would be distilled
```

The system scans `raw/`, identifies patterns, and writes candidate wiki pages to `drafts/`.

### Step 3: Promote to Wiki

Review the draft and promote it:

```bash
oks drafts list           # see candidates
oks drafts promote <slug> # promote to wiki/
```

Or use the `/promote` skill in Claude Code for interactive review.

### Step 4: Confirm Search Can Find It

```bash
oks search "CLI framework decision"
```

If the answer reflects what you just saved, you already have a working loop.

### Step 5: Connect Claude Code

Claude Code skills are pre-configured in `.claude/skills/`. The key ones:

| Skill | When to use |
|-------|-------------|
| `/query <question>` | Ask a question — Studio recalls relevant wiki/ pages and injects them |
| `/ingest` | Triage new raw/ materials into drafts |
| `/promote` | Review drafts and promote to wiki |
| `/status` | See knowledge base overview |

Try it:

```
/query What did we decide about CLI frameworks?
```

Claude Code will recall the wiki page you just promoted and answer with citations.

## Definition of Done

You should be able to answer yes to all of these:

* I saved one raw material in `raw/`
* I ingested it into a draft in `drafts/`
* I promoted the draft to `wiki/`
* I searched for it with `oks search` and got it back
* In Claude Code, `/query` recalled my knowledge

If any answer is no, see [Verification](#verification) below.

## Verification

### Search works

```bash
oks search "your topic"
```

Should return results from `wiki/` with relevance scores.

### Recall works

```bash
oks recall "your topic"
```

Should return both episodic results (from `raw/`) and knowledge results (from `wiki/`).

### Claude Code integration works

In a Claude Code session:

```
/query What do I know about <topic>?
```

Should inject relevant wiki/ pages into the context and answer with source labels like `[verified]` or `[inferred]`.

## Do Less on Day One

Save one memory. Ingest one draft. Promote one wiki page. Run one search. Stop.

The point on day one is to prove the loop, not to wire every domain at once.

## Next Steps

* [Memories](memories.md) — Wiki page anatomy, types, creation, and search
* [Threads](threads.md) — Raw materials, distillation workflow, and import paths
* [Architecture](architecture.md) — Five-bucket structure and memory lifecycle
* [Recall Engine](recall-engine.md) — 6-factor scoring algorithm
* [Dreaming Cycle](dreaming-cycle.md) — Knowledge evolution pipeline
