"""Security credential leak tests — formal pytest suite (v0.4.0 RC).

Tests migrated from tmp/security_leak_test.py.
Each test proves one category of credential redaction works.
"""

import json

from knowledge_studio.security.redaction import (
    redact_headers,
    redact_mapping,
    redact_text,
    sanitize_remote_artifact,
)
from knowledge_studio.security.sensitive_fields import REDACTED


def test_redact_headers_all_sensitive():
    """All sensitive header names are redacted case-insensitively."""
    headers = {
        "Authorization": "Bearer sk-test123",
        "authorization": "Bearer sk-lowercase",
        "Proxy-Authorization": "Basic dXNlcjpwYXNz",
        "Cookie": "session=abc123",
        "Set-Cookie": "session=def456",
        "X-API-Key": "key-789",
        "x-api-key": "key-lower",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "oks-test/1.0",
    }
    redacted = redact_headers(headers)
    assert redacted["Authorization"] == REDACTED
    assert redacted["authorization"] == REDACTED
    assert redacted["Cookie"] == REDACTED
    assert redacted["Set-Cookie"] == REDACTED
    assert redacted["X-API-Key"] == REDACTED
    assert redacted["x-api-key"] == REDACTED
    assert redacted["Content-Type"] == "application/json"
    assert redacted["Accept"] == "application/json"
    assert redacted["User-Agent"] == "oks-test/1.0"


def test_redact_mapping_recursive():
    """Sensitive JSON keys are redacted recursively."""
    data = {
        "api_key": "sk-12345",
        "access_token": "eyJhbGciOi...",
        "client_secret": "abc123def456",
        "credentials": {"client_secret": "nested-secret"},
        "session": "sess-xyz",
        "normal_field": "keep-me",
        "nested": {"deep_key": "keep"},
    }
    redacted = redact_mapping(data)
    assert redacted["api_key"] == REDACTED
    assert redacted["access_token"] == REDACTED
    assert redacted["client_secret"] == REDACTED
    assert redacted["credentials"]["client_secret"] == REDACTED
    assert redacted["session"] == REDACTED
    assert redacted["normal_field"] == "keep-me"
    assert redacted["nested"]["deep_key"] == "keep"


def test_redact_text_patterns():
    """Bearer tokens, Basic auth, JWT, and AWS keys are caught in free text."""
    text = (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        " Basic dXNlcjpwYXNzd29yZA== ..."
        " AKIAIOSFODNN7EXAMPLE ..."
    )
    redacted = redact_text(text)
    assert "Bearer" not in redacted
    assert "Basic" not in redacted
    assert "AKIA" not in redacted
    assert REDACTED in redacted


def test_sanitize_json_artifact():
    """JSON API responses have credentials stripped."""
    api_response = json.dumps({
        "status": "ok",
        "api_key": "sk-secret-123",
        "data": {"name": "test"},
    }).encode("utf-8")
    cleaned = sanitize_remote_artifact(api_response, content_type="application/json")
    cleaned_data = json.loads(cleaned)
    assert cleaned_data["api_key"] == REDACTED
    assert cleaned_data["status"] == "ok"


def test_sanitize_binary_passthrough():
    """Binary data passes through unchanged."""
    binary = b"\x00\x01\x02\xff\xfe"
    result = sanitize_remote_artifact(binary, content_type="application/octet-stream")
    assert result == binary


def test_e2e_no_leak_pipeline():
    """Full pipeline: no credentials survive into artifact data."""
    # Headers
    sensitive_headers = {"Authorization": "Bearer token-value", "X-API-Key": "key-value"}
    rh = redact_headers(sensitive_headers)
    for k in ("Authorization", "X-API-Key"):
        assert rh[k] == REDACTED

    # JSON body
    api_body = {"access_token": "secret-token", "refresh_token": "refresh-secret", "normal": "ok"}
    rb = redact_mapping(api_body)
    assert rb["access_token"] == REDACTED
    assert rb["refresh_token"] == REDACTED
    assert rb["normal"] == "ok"

    # Free text
    free_text = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature and AKIAIOSFODNN7EXAMPLE"
    rt = redact_text(free_text)
    assert "eyJhbGci" not in rt
    assert "AKIA" not in rt
