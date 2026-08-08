# Security Acceptance — v0.4.0 RC

**Date**: 2026-08-06
**Status**: FULL PASS (5/5 leak tests)

## Module

`knowledge_studio/security/` (shipped in Wheel):
- `sensitive_fields.py` — canonical credential patterns
- `redaction.py` — unified redaction functions
- `__init__.py` — public API exports

Also at repo root: `security/` (source of truth, identical content).

## Covered Credential Types

| Category | Count | Examples |
|----------|-------|----------|
| HTTP Headers (case-insensitive) | 9 | Authorization, Proxy-Authorization, Cookie, Set-Cookie, X-API-Key |
| JSON keys (exact match) | 24 | api_key, access_token, refresh_token, client_secret, session |
| JSON keys (header-aware) | 9 | Authorization, Proxy-Authorization (when appearing as JSON keys) |
| Free-text patterns (regex) | 7 | Bearer token, Basic auth, JWT, AWS keys (AKIA...), hex secrets, session cookies |

## Test Results

| Test | Result |
|------|--------|
| `redact_headers` | PASS — all 9 header types replaced, 3 non-sensitive preserved, case-insensitive |
| `redact_mapping` | PASS — 16 sensitive keys at various nesting depths, container recursion |
| `redact_text` | PASS — Bearer, Basic, JWT, AWS keys caught in free text |
| `sanitize_remote_artifact` | PASS — JSON cleaned, binary passthrough |
| E2E no leak | PASS — no credentials survive into simulated Raw Bundle artifacts |

## Design

- Unified module, not per-Provider
- 3-layer redaction: header (case-insensitive), JSON key (recursive + header-aware), free-text patterns
- Container-value recursion: dicts/lists under sensitive keys recurse (not wholesale-replaced)
- `sanitize_remote_artifact()`: single entry point → JSON detection → redact_mapping → fallback redact_text → binary passthrough

## Known Gaps

- MCP response real-time audit not yet automated (manual review recommended for first release)
- Provider-declared `extra_sensitive_keys` in provider.yaml are parsed but not yet enforced in redaction pipeline
