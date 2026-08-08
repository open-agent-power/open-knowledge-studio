# Remote Governance & Credential Security

Status: **implemented (module)** — pending live audit
Version: 0.4.0

## Purpose

OKS Providers may call external APIs (Firecrawl, AgentKey, remote ASR, etc.).
This document defines how those calls are governed and how credentials are
protected from leaking into Raw Bundles, logs, or EvidenceManifest provenance.

## 1. Credential Sources

Credentials for remote providers MUST come from exactly one of:

| Source | Example | How to Configure |
|--------|---------|-----------------|
| Environment variable | `FIRECRAWL_API_KEY`, `AGENTKEY_API_KEY` | `export` / `.env` |
| MCP session token | AgentKey OAuth | Configured in Claude Code MCP settings |
| OS keychain | (future) | Not yet implemented |

**Never**: hardcoded in source, committed to git, passed as CLI arguments, or
embedded in Recipe/provider.yaml.

## 2. User Policy Tiers

Every SourceEnvelope carries a `policy.remote_processing` field with one of:

| Value | Meaning | Default for |
|-------|---------|-------------|
| `deny` | No remote calls; local-only processing | `local_file` sources |
| `allow` | Remote calls permitted for public URLs | `public_url` sources |
| `ask` | Prompt user before each remote call | `authenticated_remote` sources |

Agent MUST respect this policy. A Provider's `probe.py` should check the policy
before attempting remote calls.

## 3. Redaction Pipeline

All remote API responses pass through `security/redaction.py` BEFORE entering
any Raw Bundle artifact.

```
Remote API response
  → sanitize_remote_artifact(raw_bytes, content_type)
    → redact_mapping() for JSON responses (structured key-based)
    → redact_text() for text responses (pattern-based)
    → redact_headers() for HTTP header metadata
  → cleaned artifact bytes
  → write to Raw Bundle artifacts/
```

### What gets redacted

| Category | Method | Examples |
|----------|--------|----------|
| HTTP headers | `redact_headers()` | Authorization, Cookie, X-API-Key, Set-Cookie |
| JSON keys (exact) | `redact_mapping()` | api_key, access_token, client_secret, password |
| JSON keys (header-like) | `redact_mapping()` | Authorization, Proxy-Authorization (case-insensitive) |
| Free text patterns | `redact_text()` | Bearer tokens, JWT, Basic auth, AWS keys, hex secrets |

### What does NOT get redacted

- Public metadata (title, URL, duration, file size)
- Content body (article text, PDF text, subtitle text)
- Cost and latency metrics
- Tool names and versions
- Non-sensitive HTTP headers (Content-Type, User-Agent)

## 4. Provider Responsibilities

Each Provider that makes remote calls:

1. **MUST** call `sanitize_remote_artifact()` on raw API responses before writing artifacts
2. **MAY** declare `extra_sensitive_keys` in `provider.yaml` for provider-specific fields
3. **MUST NOT** re-implement redaction logic (regex, string replace, etc.)
4. **MUST** document in `SKILL.md` what remote endpoints are called and with what credentials
5. **MUST** set `provenance.endpoint` and `provenance.cost` in the EvidenceFragment

Example `provider.yaml` addition:

```yaml
security:
  extra_sensitive_keys:
    - user_token       # Provider-specific sensitive field
    - refreshKey       # Provider-specific sensitive field
```

## 5. Run Workspace Isolation

All remote call artifacts live in `.oks/runs/{run_id}/work/{provider}/`.
Credentials MUST NOT appear in:

| Location | Risk | Mitigation |
|----------|------|------------|
| `work/{provider}/` raw output | Response echo | `sanitize_remote_artifact()` |
| `fragments/*.json` | Provenance field | `redact_headers()` on request metadata |
| `manifest/evidence-manifest.json` | Steps reason field | Agent MUST not include creds in reason strings |
| `logs/` | stdout/stderr from tools | `redact_text()` before writing |
| Final Raw Bundle | api-response.json artifact | Already sanitized by pipeline |

## 6. Retry & Error Handling

| Condition | Action |
|-----------|--------|
| HTTP 429 (rate limit) | Wait Retry-After seconds, max 2 retries |
| HTTP 401/403 (auth failure) | Record as `environment_limited`, suggest credential check |
| Timeout | Record as `partial`, note timeout in warnings |
| DNS/Connection failure | Record as `failed`, suggest network check |
| Empty/encrypted response | Record as `partial` with `needs_user_action` |

Do NOT silently retry auth failures — the user needs to know their credentials
are invalid.

## 7. Audit Trail

Every remote call records in the EvidenceManifest:

```yaml
provenance:
  endpoint: "https://api.example.com/v1/fetch"
  tool: "firecrawl"
  tool_version: "1.0.0"
  cost: { amount: 1, unit: "credit" }
  took_ms: 1234
  redaction_applied: true
```

The `redaction_applied: true` flag MUST be set whenever `sanitize_remote_artifact()`
was called. This provides a verifiable audit trail.

## 8. Verification

Run `python tmp/security_leak_test.py` to verify the redaction module catches all
known credential patterns. This test:

1. Validates all HTTP header redactions
2. Validates nested JSON key redactions
3. Validates free-text pattern matching (Bearer, JWT, Basic, AWS keys)
4. Validates full artifact sanitization pipeline
5. Validates end-to-end: no credentials survive into simulated Raw Bundle

**Passing this test is a release gate.** Any new Provider that makes remote calls
MUST add its credential patterns to the test suite.

## 9. Known Gaps

| Gap | Severity | Plan |
|-----|----------|------|
| Binary responses (images, audio) | Low | Cannot inspect — rely on API contract that these don't contain creds |
| Custom auth schemes | Medium | Providers declare `extra_sensitive_keys` in provider.yaml |
| Real MCP response audit | High | Pending: run sanitize on actual AgentKey/Firecrawl live responses |
| Credential in URL query params | Medium | `redact_text()` now catches `key=value` patterns |
| Response compression (gzip) | Low | Decompress before sanitizing |
