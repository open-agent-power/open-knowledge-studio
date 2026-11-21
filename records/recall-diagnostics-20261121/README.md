# E1 v2.0 rank-1 miss diagnostics — 2026-11-21

**Documentation / evidence only.** Product baseline
`0c6f791c3066c9bac8d76930012ec8d55b7e60ca`. Frozen dataset
`e1-zh-32-v2.0.yaml` sha256
`b685288b3f4f0a827692e3865f5c06909d2d0ad3472de20afdbf100c8688df53`;
corpus `zh-ops-19@handoff-20261119` with 17 allowed documents, byte-identical
to the v1.0 corpus. No product code, runtime behaviour, dependency or test
baseline is changed by this record.

## Summary

A reproducible diagnostics record for the E1 Chinese recall evaluation
(`e1-zh-32-v2.0`, 32 cases / 17 allowed documents). It surfaces the five
rank-1 misses from the run-05 B/C comparison, reproduces the run-02 BM25
`b`/`k1` sweep on the larger frozen dataset, and records why **no BM25
parameter change is a valid product fix**.

**Documentation / evidence only.** No product code, no runtime behaviour, no
dependency, no test-baseline change.

## Findings

**1. The five misses are arm divergences, not a shared defect.**

All five have the gold document at rank 2 with R@5 = 1 and MRR = 0.5, i.e. a
ranking-stage loss, not a retrieval-stage loss. Four are B-only (plain SQLite
FTS5 BM25); the product C chain already recovers rank 1 on all four.
`e1-001` is the reverse: B is rank 1 and C displaces the gold to rank 2.

| case | arm | gold | top-1 usurper | other arm |
|---|---|---|---|---|
| `e1-013` | B | `refund-policy-current` | `customer-tier-sla` | C rank 1 |
| `e1-015` | B | `cdn-cache-policy` | `api-rate-limit` | C rank 1 |
| `e1-019` | B | `sla-credit` | `customer-success-playbook` | C rank 1 |
| `e1-020` | B | `invoice-issuance` | `customer-success-playbook` | C rank 1 |
| `e1-001` | C | `refund-policy-current` | `expense-reimbursement` | B rank 1 |

**2. Calibration is proven on the 32-case dataset.**

An independently re-implemented BM25 model reproduces SQLite `bm25()` on all
303 (query, doc) scores with max abs error `3.553e-15` (threshold 1e-6). The
`b=0.75` variant reproduces the real `B-bigram-v2-01` top-5 on **32/32**
cases. A `k1=1.3` mutation probe breaks calibration (`8.915e-02`), so the
assertion has discriminating power rather than being self-confirming.

**3. The sweep narrows the run-02 (16-case) result.**

`b` in {0, 0.10, 0.25, 0.50, 0.75, 1.00}, `k1` in {0.5, 1.2, 2.0}:

| variant | R@1 | R@5 | MRR | B misses fixed | new rank-1 miss |
|---|---|---|---|---|---|
| `baseline_b0.75` | 0.833333 | 1.0 | 0.916667 | — | — |
| `b0.00` | 0.833333 | 1.0 | 0.916667 | `e1-013` | `e1-004` |
| `b0.10` | 0.875 | 1.0 | 0.9375 | `e1-013` | — |
| `b0.25` | 0.875 | 1.0 | 0.9375 | `e1-013` | — |
| `b0.50` / `b1.00` / both `k1` variants | 0.833333 | 1.0 | 0.916667 | — | — |

So on the 32-case dataset `b=0.10`/`0.25` fix **only 1 of 4** B misses, not
all of them. `forbidden_in_top5_total` stays 0 and all 8 no-answer cases keep
a non-empty top-5 under every variant.

**4. Strict per-token attribution explains why.**

Only `e1-013` is length-normalisation dominated (gold IDF advantage `+0.5733`,
top1/gold length-factor ratio `1.3389`, the `b=0` counterfactual flips the
winner). The other three are vocabulary/IDF dominated (gold IDF advantage
`-1.6720`, `-6.0951`, `-0.8961`), so lowering `b` cannot flip them. This
independently predicted fix set equals the measured fix set exactly.

**5. Product boundary.**

`cli/knowledge_studio/search/fts5.py:535` calls
`bm25(0, 0, w_title, w_body, w_tags, w_code_blocks)`. SQLite FTS5's `bm25()`
accepts **column weights only**; `k1` and `b` are compile-time defaults and
cannot be tuned from product SQL. These variants are a causal diagnosis, not
a config patch. Landing anything would require a rerank or a different
scoring implementation.

## Verification

| command | exit | result |
|---|---|---|
| `python -X utf8 scripts/w8_surface_misses.py` | 0 | 15/15 checks pass |
| `python -X utf8 scripts/w8_attribution.py` | 0 | 13/13 checks pass |
| `python -X utf8 verify-archive.py` | 0 | `Verified 303 files` |

The 17 subject frozen/scoring/report artifacts are byte-identical by sha256
before and after. No predictions, manifest or `comparison.json` was written
back. Product baseline: `0c6f791c3066c9bac8d76930012ec8d55b7e60ca`.

## Known boundaries

- Offline scoring-side simulation only; not applied to B/C predictions, not
  merged into `comparison.json`.
- `e1-001` (C-arm miss) is out of scope for any lexical `b`/`k1` change:
  plain BM25 already ranks its gold at 1.
- Archived documents never enter the index, so `forbidden_in_top5_total=0`
  validates archive isolation, not ranking quality.
- The 8 no-answer cases still return a non-empty top-5 and abstention stays
  `0/8`; `b=0.10`/`0.25` perturb top-5 on `e1-027`/`e1-028`.
- The replay scripts live in the archived local run directory and reference
  absolute local paths, so they are not submitted as portable artifacts. The
  five evidence JSON files here are self-contained.
- Semantic-level gold re-labelling and a real `pip install` wheel state are
  still unverified (carried over from run-05). No merge or release is
  requested by this PR.

## Evidence files in this record

| file | contents |
|---|---|
| `evidence/w8-miss-surface-v1.json` | five rank-1 misses, one structured record per (case, arm), with both arms' top-5 and classification |
| `evidence/w8-v2-calibration.json` | BM25 model vs SQLite `bm25()` over all 303 (query, doc) scores, plus the `k1=1.3` mutation probe |
| `evidence/w8-variant-sweep-v2.json` | eight `b`/`k1` variants over all 32 cases: metrics, per-miss gold rank, new misses, forbidden and no-answer impact |
| `evidence/w8-verdict.json` | 15/15 surfacing + reproducibility checks |
| `evidence/w8-attribution-v1.json` | strict per-token decomposition, counterfactuals, 13/13 attribution checks |
| `ACCEPTANCE.md` | acceptance scorecard with real commands and exit codes |

## Replaying

The scripts that produced these files (`w8_surface_misses.py`,
`w8_attribution.py`) live in the archived local run directory
`oks-next-stage-runs/20261121-run-05/scripts/` and reference absolute local
paths (frozen dataset, corpus KB and B/C prediction runs outside this
repository). They are intentionally **not** submitted as portable artifacts.
The five JSON files above are self-contained; the `score()` model and every
numeric claim can be recomputed from them plus the frozen corpus.

Relationship to open PRs: #116 (CLI output decoupling) and #117 (wiki page
cache) are product-code changes on the same baseline. This record is
orthogonal to both and can be merged independently.
