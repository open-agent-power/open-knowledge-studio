# open-knowledge-studio (`oks`)

File-based knowledge engineering CLI for Claude Code and coding agents.

`oks` is the command-line core of [Open Knowledge Studio](https://github.com/open-agent-power/open-knowledge-studio):
a file-based knowledge base that turns raw material into a recallable, self-decaying wiki.

## Install

```bash
pipx install "git+https://github.com/open-agent-power/open-knowledge-studio.git@main#subdirectory=cli" && pipx ensurepath
```

We recommend pipx because modern Linux (Ubuntu 24.04+) and macOS Homebrew Pythons are
PEP 668 externally-managed, so a bare `pip install` fails. If your mirror lags behind
PyPI, add `--pip-args="-i https://pypi.org/simple"`.

Optional multimodal ingest is included in the package, while its heavy
dependencies (PDF / audio / video / formula extraction) remain opt-in:

```bash
oks capability install watch
oks capability install document
oks capability install pdf
```

Add `--yes` to install a listed capability after reviewing its dependencies.

## What you get

- **6+1-factor recall engine** — token overlap, substring, topic trace, type boost,
  review penalty, memory curve, plus an optional goal boost that lifts on-scope pages.
- **Dreaming cycle** — distill raw materials into draft proposals; humans review and
  promote them to the wiki.
- **Decay system** — memory-curve scoring with type-specific λ and hot/warm/cold/evictable tiers.
- **`oks` CLI** — search, recall, offline evaluation, execution traces, wiki CRUD, drafts, distill, lint, status, metrics.

The CLI core is dependency-light and calls no external network APIs; agents and humans
orchestrate the pipeline around it.

## Quick start

```bash
pipx install "git+https://github.com/open-agent-power/open-knowledge-studio.git@main#subdirectory=cli" && pipx ensurepath   # 1. install the CLI
oks init my-knowledge-base          # 2. scaffold an instance (skills + buckets)
cd my-knowledge-base
oks status                          # 3. use it
oks recall "git branch" --knowledge-only
oks recall "deployment" --knowledge-only --type strategy --format json
oks recall "git branch" --goal none --format json --explain
oks eval recall eval/datasets/team-v1.yaml --output eval/runs/baseline.json
oks trace start memory-goal --run-id demo-001
```

Use `--goal active` (default) to merge active goals, `--goal <slug>` for one
reproducible goal, or `--goal none` for a no-goal baseline. `--explain` exposes
score components without changing ranking.

Machine-readable output uses `recall-response/v1` for `oks recall` and
`recall-hit/v1` for individual hits. `--type` filtering happens before ranking
and `--limit`; `--knowledge-only` drops the episodic path.

`oks eval` is offline and read-only. `oks trace` writes append-only execution
events under `raw/executions/`; generated Wiki/Skill proposals stay under
`drafts/proposals/` until a human explicitly promotes them.

`oks init` creates a git-tracked memory instance, missing default settings and host Skill entries. Schemas remain bundled with OKS and templates belong to their Skills; existing settings and profiles survive upgrades. No repo clone required.

## Documentation

- Design docs: https://open-agent-power.github.io/open-knowledge-studio/
- Source & issues: https://github.com/open-agent-power/open-knowledge-studio

## License

MIT
