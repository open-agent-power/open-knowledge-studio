"""Canonical list of sensitive field patterns for credential redaction.

This is the SINGLE source of truth for what constitutes a sensitive field.
Providers may declare ADDITIONAL fields via their provider.yaml, but they
must not re-implement the base redaction logic.
"""

from __future__ import annotations

import re
from typing import FrozenSet

# ── Header names (case-insensitive match) ──────────────────────

SENSITIVE_HEADERS: FrozenSet[str] = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-session-id",
    "www-authenticate",
})

# ── JSON / dict key patterns (exact match, case-sensitive) ─────

SENSITIVE_KEYS: FrozenSet[str] = frozenset({
    "api_key",
    "apikey",
    "apiKey",
    "access_token",
    "accessToken",
    "refresh_token",
    "refreshToken",
    "client_secret",
    "clientSecret",
    "secret",
    "password",
    "passwd",
    "token",
    "session",
    "session_id",
    "sessionId",
    "auth",
    "credential",
    "credentials",
    "private_key",
    "privateKey",
    "signing_key",
    "signingKey",
})

# ── Regex patterns for free-text scanning ──────────────────────

# Compiled patterns that match credential-bearing strings in free text.
# Each pattern is anchored to common credential formats.
SENSITIVE_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in [
        # Bearer tokens
        # (?<![a-zA-Z0-9_]) replaces \b — Python 3 \w includes CJK chars,
        # so \b does NOT match at CJK→ASCII transitions (both are \w).
        # Explicit ASCII boundary check prevents credential leakage when
        # Chinese/Unicode text is adjacent without a space.
        r'(?<![a-zA-Z0-9_])Bearer\s+[A-Za-z0-9\-._~+/]+=*(?![a-zA-Z0-9_])',
        # Basic auth
        r'(?<![a-zA-Z0-9_])Basic\s+[A-Za-z0-9+/]+=*(?![a-zA-Z0-9_])',
        # API keys in key=value form (also matches "api key" with space)
        r'(?<![a-zA-Z0-9_])(?:api[ _-]?key|apikey|access[ _-]?token|secret)\s*[:=]\s*\S+',
        # JWT tokens (header.payload.signature)
        r'(?<![a-zA-Z0-9_])eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+',
        # OpenAI / DashScope / LLM provider API keys (sk- prefix)
        r'(?<![a-zA-Z0-9_])sk-[A-Za-z0-9_-]{20,}(?![a-zA-Z0-9_])',
        # AWS-style access keys
        r'(?<![a-zA-Z0-9_])AKIA[0-9A-Z]{16}(?![a-zA-Z0-9_])',
        # Generic hex-encoded secrets (32+ hex chars after key=)
        r'(?<![a-zA-Z0-9_])(?:token|key|secret|password)\s*[:=]\s*[0-9a-fA-F]{32,}(?![a-zA-Z0-9_])',
        # session cookie values
        r'(?<![a-zA-Z0-9_])session\s*[:=]\s*[A-Za-z0-9+/=]{20,}',
    ]
)

# ── Replacement string ─────────────────────────────────────────

REDACTED = "***REDACTED***"


def is_sensitive_header(name: str) -> bool:
    """Check if an HTTP header name is sensitive (case-insensitive)."""
    return name.lower() in SENSITIVE_HEADERS


def is_sensitive_key(key: str) -> bool:
    """Check if a dict key is sensitive (case-sensitive exact match)."""
    return key in SENSITIVE_KEYS


def find_sensitive_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sensitive patterns in free text.

    Used by redact_text() to replace credential-bearing substrings.
    """
    spans: list[tuple[int, int]] = []
    for pattern in SENSITIVE_PATTERNS:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    # Sort and merge overlapping spans
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
