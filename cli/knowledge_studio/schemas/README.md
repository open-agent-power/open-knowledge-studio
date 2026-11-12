# Raw Bundle Schemas

These JSON Schema files are **normative references** — they document the
contract emitted by connector extractors and consumed by the validator.

## Runtime status

- `oks raw-commit` loads these package resources and validates evidence with `jsonschema`.
- Builds generate bundled reference schemas under `_assets/_meta/schemas/`
  from this directory. Edit the package source when changing a protocol.
- New knowledge instances keep these tool schemas in the installed package.
  Existing instance files are preserved during upgrades.

## When to use

Consult these schemas when:
- Adding a new extractor that must produce compliant Raw Bundles
- Debugging validator mismatches between expected and actual fields
- Reviewing a connector protocol change

## Files

| Schema | Purpose |
|---|---|
| `capture-envelope.schema.json` | Per-run capture identity and metadata |
| `capture-result-v0.1.schema.json` | Provider-neutral result returned by new Capture Adapters |
| `capability-manifest.schema.json` | Extractor capability declaration shape |
| `fetch-receipt.schema.json` | Network fetch provenance record |
| `processing-run.schema.json` | Run-level processing journal entry |
| `raw-bundle-v0.2.schema.json` | Raw Bundle v0.2 manifest and provenance graph |
| `agent-observation-v0.1.schema.json` | Agent 对 Evidence Bundle 的派生观察，必须引用 artifact 和 locator |
