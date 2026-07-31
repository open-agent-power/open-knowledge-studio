# Raw Bundle Schemas

These JSON Schema files are **normative references** — they document the
contract emitted by connector extractors and consumed by the validator.

## Runtime status

- **Not auto-loaded or enforced at runtime.** The validator (`scripts/validator.py`)
  uses hardcoded version strings and field checks; no `jsonschema` dependency.
- **Not loaded by CI.** The publish workflow only builds the Python wheel.

## When to use

Consult these schemas when:
- Adding a new extractor that must produce compliant Raw Bundles
- Debugging validator mismatches between expected and actual fields
- Reviewing a connector protocol change

## Files

| Schema | Purpose |
|---|---|
| `capture-envelope.schema.json` | Per-run capture identity and metadata |
| `capability-manifest.schema.json` | Extractor capability declaration shape |
| `fetch-receipt.schema.json` | Network fetch provenance record |
| `processing-run.schema.json` | Run-level processing journal entry |
| `raw-bundle-v0.2.schema.json` | Raw Bundle v0.2 manifest and provenance graph |
