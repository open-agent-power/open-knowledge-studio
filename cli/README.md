# open-knowledge-studio (`oks`)

File-based knowledge engineering CLI for Claude Code and coding agents.

`oks` is the command-line core of [Open Knowledge Studio](https://github.com/open-agent-power/open-knowledge-studio):
a file-based knowledge base that turns raw material into a recallable, self-decaying wiki.

## Install

```bash
pip install open-knowledge-studio
```

Optional multimodal ingest (PDF / audio / video / formula extraction) lives in a
separate, heavier package that you can pull in on demand:

```bash
pip install "open-knowledge-studio[connector]"
```

## What you get

- **6+1-factor recall engine** — token overlap, substring, topic trace, type boost,
  review penalty, memory curve, plus an optional goal boost that lifts on-scope pages.
- **Dreaming cycle** — distill raw materials into draft proposals; humans review and
  promote them to the wiki.
- **Decay system** — memory-curve scoring with type-specific λ and hot/warm/cold/evictable tiers.
- **`oks` CLI** — search, recall, wiki CRUD, drafts, distill, lint, status, metrics.

The CLI core is dependency-light and calls no external network APIs; agents and humans
orchestrate the pipeline around it.

## Quick start

```bash
pip install open-knowledge-studio   # 1. install the CLI
oks init my-knowledge-base          # 2. scaffold an instance (skills + buckets)
cd my-knowledge-base
oks status                          # 3. use it
oks search "git branch"
```

`oks init` materializes the shareable layer (Claude Code skills, templates, schema,
settings) and a git-tracked memory instance. No repo clone required.

## Documentation

- Design docs: https://open-agent-power.github.io/open-knowledge-studio/
- Source & issues: https://github.com/open-agent-power/open-knowledge-studio

## License

MIT
