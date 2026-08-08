---
name: upstream-pr-remediation
description: Implement only the approved blocking fixes for upstream Open Knowledge Studio PR 4. Use when addressing its Feishu safety, cross-platform CLI, git hygiene, and Raw protocol documentation review findings; do not push, create a PR, or call real Feishu.
---

# Upstream PR 4 remediation

Work only in the dedicated remediation worktree. Preserve unrelated uncommitted
work in the primary checkout. Do not push, open a PR, use Feishu credentials, or
call a real Base.

## Required changes

1. Keep `.oks/` ignored and add a regression test for candidate, run, and lock
   paths.
2. Provide one lazily called, shared Lark CLI resolver. Prefer `LARK_CLI_EXE`;
   support `lark-cli.cmd`/`.exe` on Windows and `lark-cli` on Linux/macOS.
   Importing either Feishu module must not require a CLI installation.
3. Make Feishu setup redact Base tokens by default. Add
   `--show-credentials` as the only opt-in full-display path. Default output and
   raised errors must not expose a Base token.
4. Redact token/Bearer material and home-directory paths before writing a failed
   record's error text to Base; truncate after redaction.
5. Restore a concise compatibility contract in the Raw protocol document:
   v0.1 invariants, v0.1-to-v0.2 mapping, reader compatibility, and migration
   route. Keep connector schemas and capability manifests as the v0.2 authority.

## Required evidence

Add focused tests for all five requirements, including Linux/Windows resolver
selection, missing-CLI lazy failure, default versus explicit credential display,
error redaction, and the ignore contract. Run the full test suite and
`git diff --check`.

## Handoff

Return a concise report with: changed files, each review item and its test,
full test command/result, unresolved non-blocking review suggestions, and
risks. Do not commit, push, reply to GitHub, or resolve review threads.
