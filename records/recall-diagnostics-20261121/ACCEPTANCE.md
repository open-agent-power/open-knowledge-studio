# W8 Acceptance Scorecard

One line per acceptance item; evidence is a real command with its exit code,
or an artifact that can be opened directly. WARN is an honest limitation, not
a failure. Unchecked items are not scored.

| Item | Status | Evidence |
|---|---|---|
| Archive integrity re-verified | PASS | `python verify-archive.py` -> exit 0, `Verified 303 files` |
| Five misses surfaced with checkable fields | PASS | `python scripts/w8_surface_misses.py` -> exit 0, `W8_STATUS: pass checks=15/15` |
| All five are rank-2 gold with R@5=1 | PASS | `evidence/w8-verdict.json`: `all_five_gold_at_rank2`, `all_five_R5_equals_1` |
| B 4 / C 1 arm-divergence classification | PASS | same verdict `classification_4_B_1_C=true` |
| v2.0 corpus byte-identical to v1.0 | PASS | live probe: manifest sha equal, 19 file shas equal, `actual corpus byte diffs = []` |
| BM25 calibrated on all 32 queries | PASS | `evidence/w8-v2-calibration.json`: 303 scores, max abs error `3.553e-15` |
| Calibration assertion is discriminating | PASS | mutation probe `k1=1.3` -> `8.915e-02`, `assertion_flips=true` |
| Baseline reproduces real B predictions | PASS | `b=0.75` top-5 == `B-bigram-v2-01` on 32/32; `B_repeat_identical=true` |
| Eight b/k1 variants fully recorded | PASS | `evidence/w8-variant-sweep-v2.json` |
| Sweep fixes only 1 of 4 B misses | PASS | `b0.10`/`b0.25`: R@1 `0.875`, fix `{e1-013}`, `new_rank1_miss=[]`; `b0.00` adds `e1-004` |
| Attribution independently predicts fix set | PASS | `python scripts/w8_attribution.py` -> exit 0, 13/13 checks; predicted == measured == `['e1-013']` |
| Decomposition matches SQLite | PASS | `all_decompositions_match_sqlite=true` (< 1e-9 per doc) |
| Control self-comparison corrected | PASS | `b000_control_self_comparison_flagged=true`, `b000_control_gold_drops_to_rank2=true` |
| C-arm miss not over-claimed | PASS | `C_arm_miss_scope`: B gold rank 1, C gold rank 2, `out_of_scope_for_b_sweep=true` |
| Product `bm25()` cannot tune b | PASS | live grep `cli/knowledge_studio/search/fts5.py:535` -> `bm25(0, 0, w_title, w_body, ...)` column weights only |
| forbidden / no-answer boundaries | PASS | `all_variants_forbidden_zero=true`, `all_variants_no_answer_top5_nonempty_8=true` |
| No subject artifact rewritten | PASS | 17 frozen/scoring/report artifacts byte-identical by sha256 before/after |
| Remote PR states read-only verified | PASS | `gh api .../pulls/116` `/117` -> exit 0: `state=open, merged=false, base=main` |
| Replay scripts portable | WARN | Not submitted: they hard-reference absolute local paths outside this repository |
| Semantic gold re-labelling | WARN | Unchecked (carried over from run-05) |
| Real `pip install` wheel state | WARN | Unchecked (carried over from run-05) |
| External code review | WARN | Unchecked: `gh api` was read-only |
| merge / release | WARN | Not executed; separate authorisation required |
| C-class environment blockers (Docker / swebench) | WARN | Deferred by the user; historical `blocked_environment` state preserved |

**FAIL rows: none.** WARN rows are unchecked paths, known limits or
unauthorised actions; no historical `failed` / `partial` /
`blocked_environment` state is rewritten.
