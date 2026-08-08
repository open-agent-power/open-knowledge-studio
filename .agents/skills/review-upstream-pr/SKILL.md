---
name: review-upstream-pr
description: Independently review the remediation for upstream Open Knowledge Studio PR 4. Use after another agent implements the approved blocking fixes to inspect diffs, validate security and cross-platform behavior, run tests, and return a merge or rework verdict without editing code or writing to GitHub.
---

# Review upstream PR 4 remediation

Act only as reviewer. Do not edit product code, commit, push, create a PR,
resolve threads, or contact GitHub.

## Review gates

- `.oks/candidates/`, `.oks/runs/`, and `.oks/locks/` are ignored without
  excluding tracked source files.
- Feishu modules import without Lark installed. Runtime resolution honors
  `LARK_CLI_EXE`, Windows wrappers, and Unix `lark-cli`.
- Default setup output and failures never contain a fixture Base token; only
  `--show-credentials` may display it.
- Error text written back to Base has no Bearer/token value or user home path,
  and is truncated only after sanitization.
- Raw documentation preserves Raw/not-knowledge, no-silent-loss, and
  provenance invariants; it maps v0.1 readers to v0.2 schemas without inventing
  a second v0.2 authority.

## Evidence and verdict

Inspect the diff against the remediation base, run focused tests plus the full
suite and `git diff --check`, then report each gate as pass/fail with command
evidence. List non-blocking issues separately. End with exactly one verdict:
`ready_for_user_review` or `rework_required`.
