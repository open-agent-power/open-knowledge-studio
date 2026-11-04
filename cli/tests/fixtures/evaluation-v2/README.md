# Recall evaluation v2 fixture contract

This CC0 synthetic fixture tests the evaluator, not retrieval quality. Tests materialize
four Wiki pages in a temporary instance. No real user data is included.

`recall-case/v1` remains unchanged: every case must have at least one relevant slug.
`recall-case/v2` requires explicit answerability, source/user split groups, timezone-aware
`as_of`, provenance, and a catalog keyed by the exact slug returned by Wiki recall.
The catalog records asset identity, version, user scope (`shared` means public to all
fixture users), source lineage, and earliest available time. Relevant gold must be
visible at that time and pin its expected version. Source groups and non-shared users
cannot span train/validation/test splits. Authors must correctly label derivative
documents with the same source group; this validator cannot discover hidden lineage.
Versions of the same asset identity also stay in one split, even if source-group
labels differ. A mixed-split dataset requires `oks eval recall ... --split test`
(or `train` / `validation`). Each run records and evaluates only the selected split;
a dataset with a single split selects that split automatically.

The evaluator audits **unaltered returned hits**, including ranks beyond five, for
forbidden slugs, other-user scope, future availability and mismatched pinned versions.
Unknown returned slugs fail the run rather than silently count as safe. No output run
is written on validation failure. Answerable cases contribute to recall/MRR/nDCG;
unanswerable cases contribute to `abstention_correct` (1 only for an empty result).
Missing cohorts produce null metrics, never a fabricated zero or perfect score.
`no_result` and all leakage rates cover all cases. Rates are fractions of cases with
at least one violation, not fractions of returned documents. Case counts are included.

v2 emits `recall-eval-run/v2` and comparisons emit `recall-eval-comparison/v2`; v1 and v2
runs cannot be directly compared. Dataset hashes include the catalog and provenance.
Comparisons still require identical KB/configuration and explicitly declared code or
backend experiments. Null deltas are listed under `unmeasured_metrics`.

The explicit mode `wiki-label-audit/v1` does **not** add user authorization, filter
future documents, freeze the engine's decay clock, or evaluate Skill routing. `as_of`
is a gold-label audit boundary only. Version checks apply to catalogued Wiki documents,
which may describe versions of a Skill; they do not establish which Skill was executed.
The current Wiki engine can return the deliberately forbidden pages: tests verify that
the evaluator reports those failures, not that the engine has passed isolation tests.
Label truth, full corpus coverage, dependency state and engine time remain external
controls. Cross-platform and installed-wheel execution need their own evidence.
