# Engineering Rounds 2-3

## Round 2 -- Reliability Hardening (Current)

### Scope

Narrow, surgical reliability improvements to the Feishu Base worker pipeline.
No new features. No Feishu API calls. No network.

### Success Checks

- [x] **A -- `lark_json` bounded exponential retry**
  - Retries transient structured errors (`RATE_LIMITED`, `UPSTREAM_UNAVAILABLE`, `NETWORK_ERROR`, `TIMEOUT`) detected from JSON response body.
  - Retries `subprocess.TimeoutExpired`.
  - Retries narrowly-intended transient `OSError` subclasses only (`ConnectionRefusedError`, `ConnectionResetError`, `BrokenPipeError`); non-transient `OSError` (e.g. `FileNotFoundError`) propagates immediately.
  - Does NOT retry malformed/non-JSON stdout -- raises immediately (matching `parse_json_output` error quality).
  - Does NOT retry non-object JSON values -- raises immediately.
  - Never retries auth/validation/permission codes (`AUTH_FAILED`, `PERMISSION_DENIED`, `ACCESS_DENIED`, `VALIDATION_ERROR`, `NOT_FOUND`, `INVALID_ARGUMENT`, `CHALLENGE_REQUIRED`).
  - Bounded to 3 retries with exponential backoff: 1s, 2s, 4s.
  - Exhausted transient-error final message includes attempt count and command context (first 3 arguments).
  - Deterministic unit tests via `monkeypatch` on `subprocess.run` and `time.sleep`.
  - Regression tests prove malformed output and non-object JSON receive exactly one attempt.

- [x] **B -- Aware-UTC lease / run-id time paths**
  - `datetime.now(timezone.utc)` used for all run-id timestamp generation and lease expiry calculation.
  - Lease expiry written to Base as human-readable `YYYY-MM-DD HH:MM:SS+00:00` format.
  - `parse_base_datetime` returns aware UTC datetimes; supports offset parsing (e.g. `+08:00`).
  - `naive_migration="reject"` (default) returns `None` for tz-naive timestamps.
  - `naive_migration="assume_utc"` treats naive timestamps as UTC (used in `is_candidate` for backward compatibility).

- [x] **C -- Public-web Raw extractor moved to production**
  - Supported public-web Raw behavior extracted from `scripts/experiments/web_raw_probe.py` into `scripts/extractors/web.py`.
  - `package_public_web()` in the worker calls the production module directly -- no subprocess to the experiment script.
  - Test asserts the production worker source has zero references to `experiments/`.

- [x] **D -- Lease locking documented as single-host serialization**
  - `local_claim_lock()` docstring states it is local filesystem serialization only, not distributed coordination.
  - Documents multi-host requirement: external coordination mechanism (database lease table, Redis Redlock, or Feishu Base record-level compare-and-swap).

- [x] **E -- Watch helper shadowing removed**
  - Removed local `format_media_time`, `order_ocr_blocks`, and `parse_ocr_roi` definitions from `scripts/extractors/watch.py` that shadowed the `_shared` imports.
  - Enhanced `_shared.format_media_time` to support hour durations (HH:MM:SS for >= 1 hour).
  - Renamed watch-specific `normalize_ocr_text` to `_normalize_ocr_strict` to avoid shadowing.
  - Fixed `extractors/image.py` comment: "parent module" changed to "sibling module".

- [x] **F -- `docs/engineering-rounds-2-3.md` ASCII-only and accurate**
  - All prose is valid UTF-8 ASCII-only; no non-ASCII characters.
  - All completed Round 2 items and success checks listed above.
  - Round 3 decomposition plan retained below.

### Test Plan

```bash
pytest scripts/tests/test_feishu_base_worker.py -v
```

Key test additions:
- `test_lark_json_retries_on_rate_limited` -- confirms 3 attempts with 1s/2s sleep on RATE_LIMITED.
- `test_lark_json_retries_on_subprocess_timeout` -- confirms retry on TimeoutExpired.
- `test_lark_json_retries_on_oserror` -- confirms retry on OSError.
- `test_lark_json_never_retries_auth_failed` -- confirms single attempt, no sleep on AUTH_FAILED.
- `test_lark_json_never_retries_permission_denied` -- confirms single attempt on PERMISSION_DENIED.
- `test_lark_json_exhausts_retries_with_command_context` -- confirms final error includes command info.
- `test_lark_json_no_retry_on_malformed_json` -- malformed output receives exactly 1 attempt.
- `test_lark_json_no_retry_on_non_object_json` -- non-object JSON raises immediately.
- `test_lark_json_no_retry_on_non_transient_oserror` -- FileNotFoundError propagates immediately.
- `test_lark_json_exhausted_oserror_includes_attempt_count_and_command` -- exhausted OSError reports context.
- `test_lark_json_transient_oserror_retries_connection_reset` -- ConnectionResetError is retried.
- `test_extract_lark_error_code_from_error_dict` -- covers both `error.code` and top-level `code` paths.
- `test_is_retryable_lark_error_detects_transient_codes` / `test_is_fatal_lark_error_blocks_retry`.
- `test_parse_base_datetime_offset_timestamp` -- parses `+00:00` offset.
- `test_parse_base_datetime_iso_format_with_z` -- parses `Z` suffix.
- `test_parse_base_datetime_rejects_naive_by_default` -- default `naive_migration="reject"` returns `None`.
- `test_parse_base_datetime_migrates_naive_with_assume_utc` -- `assume_utc` treats naive as UTC.
- `test_parse_base_datetime_offset_with_non_utc` -- `+08:00` converted to UTC correctly.
- `test_lease_format_roundtrips_through_parse` -- write/read round-trip verification.
- `test_claim_record_writes_aware_utc_lease` -- verifies `+00:00` in stored lease and future timestamp.
- `test_claim_record_run_id_contains_utc_timestamp` -- verifies run-id format.
- `test_production_web_extractor_has_no_experiment_import` -- production extractor has no experiment dependency.
- `test_package_public_web_uses_production_extractor_not_experiment` -- worker source has no experiment reference.

### Changed Files

| File | Change |
|------|--------|
| `scripts/feishu_base_worker.py` | `lark_json` retry logic narrowed: no retry on malformed JSON, narrow OSError retry to transient subclasses; `local_claim_lock` docstring documenting single-host scope; `package_public_web` calls production `extractors.web` module; new helpers `_extract_lark_error_code` / `_is_retryable_lark_error` / `_is_fatal_lark_error`, new constants; `parse_base_datetime` aware-UTC + `naive_migration` parameter; UTC time paths in `is_candidate` / `claim_next_record` / `claim_record` / `process_record`. |
| `scripts/extractors/web.py` | New production module: public-web article extraction with Trafilatura, extracted from `scripts/experiments/web_raw_probe.py`. |
| `scripts/extractors/watch.py` | Removed local `format_media_time`, `order_ocr_blocks`, `parse_ocr_roi` shadowing `_shared` imports; renamed `normalize_ocr_text` to `_normalize_ocr_strict`. |
| `scripts/extractors/image.py` | Fixed comment: "parent module" -> "sibling module". |
| `scripts/_shared.py` | Enhanced `format_media_time` to support hour durations (HH:MM:SS). |
| `scripts/tests/test_feishu_base_worker.py` | 23 new test functions for retry regression, UTC time handling, production extractor verification. |
| `docs/engineering-rounds-2-3.md` | This document. |

---

## Round 3 -- Worker Modularization (Planned)

### Objective

Split `scripts/feishu_base_worker.py` (~2400 lines) into bounded modules without changing external behavior or breaking the existing test suite.

### Module Boundaries (Proposed)

```
scripts/
  feishu_base_worker.py          # CLI entry point + main() orchestration (~200 lines)
  feishu_worker/
    __init__.py
    config.py                    # WorkerConfig, load_config, resolve_lark_cli, configured_knowledge_root
    protocol.py                  # lark_json (with retry), parse_json_output, update_record, create_record,
                                 #   list_records, get_record, list_review_records, base_args
    claim.py                     # claim_next_record, claim_record, release_lease, local_claim_lock,
                                 #   parse_base_datetime, is_candidate
    capture.py                   # capture_envelope, capture_content_hash, envelope_content_hash,
                                 #   extract_url, normalize_attachments, capture_user_note
    pipeline.py                  # process_record, probe_source, download_public_source,
                                 #   download_attachments, package_local_attachment, package_routed_source,
                                 #   package_public_web, finalize_raw_v2, complete_browser_snapshot
    candidate.py                 # publish_candidate, parse_candidate_document, render_candidate_document,
                                 #   candidate_state_path, load_candidate_state, candidate_review_fingerprint
    review.py                    # review_candidate, process_next_review, read_review_record_after_write,
                                 #   promote_candidate_document, apply_review_reply_event,
                                 #   apply_review_event_with_fallback, consume_review_events,
                                 #   reconcile_historical_review_reply
    notification.py              # send_candidate_review_notification, render_candidate_review_message,
                                 #   parse_review_reply, event_reviewed_at
    io_utils.py                  # atomic_write_json, atomic_write_text, _redact_error_text,
                                 #   sha256_file, scalar_cell, utc_now, content_type_extension,
                                 #   attachment_capability
```

### Compatibility Invariants

1. **Public API stability** -- every function currently called from `main()` or from tests must remain importable from `feishu_base_worker` (re-export shim).
2. **Test backward compatibility** -- `scripts/tests/test_feishu_base_worker.py` must pass without modification (imports `feishu_base_worker as worker` so `worker.lark_json`, `worker.claim_record`, etc. must still resolve).
3. **CLI compatibility** -- `python scripts/feishu_base_worker.py run-once` must work identically.
4. **No behavior changes** -- retry logic, UTC time handling, lease semantics unchanged.
5. **Import-time side effects** -- `resolve_lark_cli()` is lazy; keep it lazy after split.

### Phased Migration

**Phase 1A -- Extract config (COMPLETED)**
- Move `WorkerConfig`, `load_config`, `configured_knowledge_root`, `resolve_lark_cli` to `feishu_worker/config.py`.
- Re-export from `feishu_base_worker.py` via legacy one-argument wrappers that supply ROOT.
- Run full test suite; fix import issues.

**Phase 1B -- Extract io_utils (CURRENT)**
- Move `atomic_write_json`, `atomic_write_text`, `_redact_error_text`, `sha256_file`, `scalar_cell`, `utc_now`, `content_type_extension`, `attachment_capability` to `feishu_worker/io_utils.py`.
- Also move `HOME`, `BEARER_RE`, `_SECRET_ASSIGNMENT_RE` (the redaction regex constants are only used by `_redact_error_text`).
- Re-export every name from `feishu_base_worker.py`.
- Fix the two remaining Worker-local naive-local clock occurrences (`event_reviewed_at`, `review_candidate`) by using aware UTC internally while preserving local-time human-readable output.
- Remove unused `tempfile` and `dataclass` imports from the base worker after extraction.
- Run full test suite; add focused independence tests.

**Phase 1B Acceptance Checks**

- [ ] `feishu_worker/io_utils` imports cleanly in a fresh subprocess with zero modules from `feishu_base_worker` loaded in `sys.modules`.
- [ ] `feishu_worker/config` imports cleanly in a fresh subprocess with zero modules from `feishu_base_worker` loaded in `sys.modules`.
- [ ] Every extracted name (`utc_now`, `sha256_file`, `atomic_write_json`, `atomic_write_text`, `_redact_error_text`, `scalar_cell`, `content_type_extension`, `attachment_capability`, `HOME`) is still importable as `worker.<name>`.
- [ ] Full pytest: `pytest scripts/tests/test_feishu_base_worker.py -v` passes without modification.
- [ ] CLI smoke: `python scripts/feishu_base_worker.py --help` succeeds.
- [ ] Zero naive `datetime.now()` calls remain in `feishu_base_worker.py`.
- [ ] Diff review confirms no behavior change in any moved function.

**Phase 2 -- Extract protocol layer**
- Move `lark_json`, `parse_json_output`, `base_args`, `update_record`, `create_record`, `list_records`, `get_record`, `list_review_records` to `feishu_worker/protocol.py`.
- This is the most critical module -- all Base I/O flows through it.
- Must carry the retry constants and helpers along.
- Run full test suite.

**Phase 3 -- Extract claim, capture, pipeline**
- Independent subgraphs; each can be tested in isolation.
- `claim` depends on `protocol` + `config` + `io_utils`.
- `capture` depends on `io_utils` only.
- `pipeline` depends on `protocol`, `capture`, `claim`, `io_utils`.

**Phase 4 -- Extract candidate, review, notification**
- These form the "upper half" of the pipeline (human review loop).
- `notification` depends on `protocol`.
- `candidate` depends on `protocol` + `notification` + `io_utils`.
- `review` depends on `candidate` + `notification` + `protocol` + `io_utils`.

**Phase 5 -- Slim down entry point**
- `feishu_base_worker.py` becomes ~200 lines: imports, `parse_args()`, `main()`.

### Rollback Plan

Each phase is a single commit. If any phase fails tests:
1. `git checkout -- scripts/` to restore previous state.
2. Delete the new `feishu_worker/` subpackage.
3. Investigate test failures; re-attempt the phase.

No database migrations. No config changes. Pure file reorganization.

### Test Strategy

- Run `pytest scripts/tests/test_feishu_base_worker.py -v` after every phase.
- Cross-platform smoke test: `python scripts/feishu_base_worker.py --help` (no Base credentials needed).
- Import check: `python -c "import sys; sys.path.insert(0, 'scripts'); import feishu_base_worker as w; print(w.claim_record)"` must succeed.

### Risks

| Risk | Mitigation |
|------|-----------|
| Circular imports | Each module only imports "lower" layers; `config` and `io_utils` have zero internal dependencies. |
| Test brittleness from monkeypatch paths | Use `import feishu_base_worker as worker` in tests; monkeypatch targets on `worker.subprocess`, `worker.time`, etc. remain valid through re-exports. |
| Windows path handling in new modules | `io_utils` uses `pathlib.Path` exclusively; already cross-platform. |
| `ROOT` constant dependence | Keep `ROOT` in `feishu_base_worker.py`; pass it explicitly where needed, or use a shared `config` module reference. |

---

## Codex / Claude Collaboration Gate

The upstream PR remains changes-requested.  Round 3 is implemented under a
three-party collaboration gate designed to close ALL review suggestions
systematically across every layer (code, tests, docs, cross-platform).

### Gate Phases

1. **Claude implementation handoff** -- Claude implements each phase in
   isolation (1A, 1B, 2, 3, 4, 5), writes focused tests, updates docs, and
   reports exact files and acceptance results.  No commit, no push, no PR,
   no network, no Feishu calls.

2. **Codex independent evidence** -- After each phase, Codex runs an
   independent review: re-executes the acceptance checks from scratch, runs
   the full test suite on every supported platform, and captures
   screenshot / log evidence.  Codex does not modify code -- it only
   gathers evidence that the phase passes or flags regressions.

3. **Claude architecture review after all phases** -- After Phase 5, Claude
   performs a final architecture review across all extracted modules,
   verifying: no circular imports, all re-exports intact, test file still
   unmodified, and the five compatibility invariants (public API stability,
   test backward compatibility, CLI compatibility, no behavior changes,
   lazy import-time side effects) all hold.

### Phase Order

- Phase 1A: config extraction (complete in Round 3 base)
- Phase 1B: io_utils extraction + naive-clock fix + Python >=3.12 note
- Phase 2: protocol extraction (lark_json, parse_json_output, CRUD wrappers)
- Phase 3: claim + capture + pipeline extraction
- Phase 4: candidate + review + notification extraction
- Phase 5: slim entry point (feishu_base_worker.py ~200 lines)
