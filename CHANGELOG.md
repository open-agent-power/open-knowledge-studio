# Changelog

## v0.4.0 (Unreleased)

### Breaking Changes

- **`oks_connector` package permanently removed** from Wheel. Old entry points
  (`oks-connector`, `oks-connector.extractors`, `oks-connector.feishu_worker`) are
  gone. Two essential stdlib-only utilities (`capability_check`, `_lark_cli`) were
  inlined into `knowledge_studio/`. Git tag `v0.4.0-legacy-final` preserves the old code.
- **Legacy extractors deleted**: `scripts/extractors/`, `scripts/experiments/`,
  `scripts/network.py`, `route_plan()`. Replaced by Agent-Native Provider system.
- **Skill installation single source**: Skills live in `skill_templates/` only;
  `_assets/{claude,agents}/skills/` are stripped at build time and runtime.
  `_install_skills()` is the sole installation path — `oks init` and
  `oks skills-install` produce identical output (SHA256-verified).

### Agent-Native Ingestion Architecture

- **Raw Bundle v0.2 pipeline** (`oks raw-commit`): 12 JSON Schema validations,
  fail-closed strategy, atomic commit (staging → validate → `shutil.move`),
  path-traversal prevention, SHA-256 artifact hash verification.
  12 structured error codes for machine-readable rejection.
- **16 Providers** under `providers/<id>/` with `provider.yaml` + `SKILL.md` +
  optional `normalize.py`. 18 capability actions in `capabilities/actions.yaml`.
- **7 Recipes**: text, pdf, office, image, web, audio, video
- **3 core protocols**: SourceEnvelope v0.1, EvidenceFragment v0.1, EvidenceManifest v0.1
- **4 supplementary protocols**: AgentObservation v0.1, CaptureEnvelope v0.2,
  EvidencePlan v0.1, FetchReceipt v0.1

### Skill System

- **10 Claude Code skills + 10 Agents skills** from single `skill_templates/` source
- **Skill installation closure**: `_assets/{claude,agents}/` no longer contain `skills/`;
  triple stripping (build-time `_vendor_assets` + `bundle_assets` + runtime `_materialize_assets`)
- **`__pycache__` / `*.pyc` excluded** from skill installation
- **4 dev-only skills excluded** from Wheel (`_DEV_ONLY_ASSET_NAMES`)
- **`/accept` skill** runs from installed package path (not `.Codex/`)
- **`/ingest` skill** uses `importlib.resources` for schema access (not bare filesystem paths)
- **`/media-ingest`** marked experimental/unavailable until scripts are packaged

### Packaging

- **Single package**: Wheel contains only `knowledge_studio` (was `knowledge_studio` + `oks_connector`)
- **Single entry point**: `oks = knowledge_studio.cli:app`
- All resources accessed via `importlib.resources.files()` — no repo-relative path guessing
- **9 setuptools packages** declared in `pyproject.toml` with explicit `package-data`
- Nested `egg-info` directories purged at build time
- `twine check` PASSED

### CLI

- **46 registered commands** across 8 Typer groups
- `oks raw-commit` — validate and atomically write evidence bundles (12 error codes)
- `oks capability catalog --json` — machine-readable provider discovery
- `oks capability doctor` — 3-tier environment diagnostic
- `oks skills-install --force` — materialize skills from installed package
- `oks feishu setup / auth / submit / run-once / publish-candidate / review-once / listen`
- `oks trace start / append / judge / feedback / blocker / propose / finish / validate / show`

### Feishu Base Worker

- Retained as script asset in `_assets/scripts/`
- Old packaging bridges (`raw_assembler`, `evidence_plan`, `degradation`, etc.)
  deleted — marked `NotImplementedError` for legacy paths
- Source + Review planes operational; Acquisition/Perception/Knowledge planes
  moved to Agent-native ingest

### Security

- `knowledge_studio/security/redaction.py` — credential scrubbing for remote artifacts
- `knowledge_studio/security/sensitive_fields.py` — recursive JSON + text pattern detection
- SSRF protection for HTTP Provider (RFC 1918, loopback, link-local block)
- Path traversal prevention in `raw_commit.py` and `store.py`
- Schema validation fail-closed (raises `SCHEMA_VALIDATOR_UNAVAILABLE`)
- Atomic file writes: `mkstemp + fsync + os.replace`

### Tests

- **426 collected, 425 passed, 1 skipped**
- `cli/tests/`: 137 tests (12 files)
- `scripts/tests/`: 289 tests (11 files)
- **9 skill closure tests** including Wheel build + install + verify integration test
- **31 Raw Bundle protocol tests** covering artifact hashes, locator validation,
  path traversal, content-type detection, atomic commit
- **6 security tests**: header/mapping/text/artifact/binary/E2E credential leak

### Experimental / Unavailable

| Feature | Status | Reason |
|---------|--------|--------|
| `http-fetch` Provider | experimental | Requires Agent runtime HTTP tools |
| `media-ingest` Skill | experimental | Scripts not yet packaged |
| `browser` Provider | BLOCKED | Chrome extension unavailable |
| `remote-asr` Provider | experimental | Network-limited |

### Known Limitations

- Cold-start E2E deferred to Phase 3
- Provider completeness not required for this release
- Feishu E2E preserved but not fully verified in this cycle
- Windows GBK encoding: `subprocess` defaults to GBK, producing Unicode warnings
  on rich-text output (non-blocking)

---

## v0.3.0

- Base knowledge engineering CLI with search, recall, wiki CRUD, drafts, lint, metrics
- 6+1-factor recall engine with decay system
- Date-based raw/ organization
- Feishu worker integration (Source + Review planes)
- Global config (`~/.oks/config.json`)
