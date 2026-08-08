"""Unified credential redaction functions.

All provider redaction MUST go through these functions. Individual providers
SHOULD NOT copy or re-implement redaction logic — they declare extra sensitive
field names in their provider.yaml instead.

Usage:
    from security.redaction import redact_headers, redact_mapping, redact_text

    clean_headers = redact_headers(response_headers)
    clean_body    = redact_mapping(api_response_json)
    clean_text    = redact_text(log_output)
"""

from __future__ import annotations

from typing import Any

from .sensitive_fields import (
    REDACTED,
    SENSITIVE_HEADERS,
    SENSITIVE_KEYS,
    find_sensitive_spans,
)


def redact_headers(
    headers: dict[str, str],
    *,
    extra_sensitive: set[str] | None = None,
) -> dict[str, str]:
    """Redact sensitive HTTP headers.

    Replaces the VALUE of any header whose name matches a known sensitive
    header (case-insensitive) with REDACTED.  Keeps the header KEY visible
    so the response structure is preserved.

    Args:
        headers: HTTP headers dict (e.g. response.headers).
        extra_sensitive: Additional header names to treat as sensitive.

    Returns:
        A new dict with sensitive values replaced.
    """
    sensitive = SENSITIVE_HEADERS
    if extra_sensitive:
        sensitive = SENSITIVE_HEADERS | {h.lower() for h in extra_sensitive}

    return {
        k: REDACTED if k.lower() in sensitive else v
        for k, v in headers.items()
    }


def redact_mapping(
    obj: Any,
    *,
    extra_sensitive_keys: set[str] | None = None,
    max_depth: int = 20,
) -> Any:
    """Recursively redact sensitive keys in a dict/list structure.

    Walks nested dicts/lists and replaces values of any key whose name
    matches SENSITIVE_KEYS (exact, case-sensitive match).

    Args:
        obj: A dict, list, or scalar value (typically a parsed JSON response).
        extra_sensitive_keys: Additional key names to treat as sensitive.
        max_depth: Maximum nesting depth (safety limit).

    Returns:
        A copy with sensitive values replaced by REDACTED.
    """
    sensitive = set(SENSITIVE_KEYS)
    if extra_sensitive_keys:
        sensitive |= extra_sensitive_keys

    return _redact_mapping_impl(obj, frozenset(sensitive), max_depth, 0)


def _redact_mapping_impl(
    obj: Any,
    sensitive_keys: frozenset[str] | set[str],
    max_depth: int,
    depth: int,
) -> Any:
    # Leaf nodes: strings, numbers, bools, None — don't recurse into them
    if isinstance(obj, (str, int, float, bool, type(None), bytes)):
        return obj

    if depth > max_depth:
        return obj

    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if _is_redactable_key(k, sensitive_keys):
                # For container values under sensitive keys, recurse to redact
                # inner fields (e.g. credentials.client_secret).
                # For leaf values, replace wholesale.
                if isinstance(v, (dict, list)):
                    result[k] = _redact_mapping_impl(v, sensitive_keys, max_depth, depth + 1)
                else:
                    result[k] = REDACTED
            else:
                result[k] = _redact_mapping_impl(v, sensitive_keys, max_depth, depth + 1)
        return result
    elif isinstance(obj, list):
        return [
            _redact_mapping_impl(item, sensitive_keys, max_depth, depth + 1)
            for item in obj
        ]
    else:
        # Tuples, sets, etc. — treat as leaf
        return obj


def _is_redactable_key(key: str, extra_sensitive: frozenset[str] | set[str]) -> bool:
    """Check if a dict key should be redacted.

    Checks both:
      1. Exact case-sensitive match against SENSITIVE_KEYS
      2. Case-insensitive match against SENSITIVE_HEADERS (for header echo in JSON)
      3. Any extra_sensitive keys from the provider
    """
    if key in extra_sensitive:
        return True
    if key in SENSITIVE_KEYS:
        return True
    if key.lower() in SENSITIVE_HEADERS:
        return True
    return False


def redact_text(
    text: str,
    *,
    extra_patterns: list[str] | None = None,
) -> str:
    """Redact credential-bearing substrings in free text.

    Scans for known patterns (JWT, Bearer tokens, API keys, etc.) and
    replaces matches with REDACTED.

    Args:
        text: Free-text string (e.g. log output, error message, traceback).
        extra_patterns: Additional regex patterns to match.

    Returns:
        Text with sensitive spans replaced.
    """
    spans = find_sensitive_spans(text)
    if not spans:
        return text

    # Build redacted string from non-sensitive portions
    parts: list[str] = []
    pos = 0
    for start, end in spans:
        parts.append(text[pos:start])
        parts.append(REDACTED)
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


def sanitize_remote_artifact(
    raw_content: bytes | str,
    *,
    content_type: str = "application/json",
    extra_sensitive_keys: set[str] | None = None,
    extra_sensitive_headers: set[str] | None = None,
) -> bytes:
    """Full sanitization of a remote API response artifact.

    This is the single entry point for cleaning remote responses before
    they enter a Raw Bundle.  It handles:
      1. JSON responses: redact_mapping on parsed body
      2. Text responses: redact_text on raw string
      3. Binary responses: returned as-is (we can't inspect binary)

    Args:
        raw_content: Raw response bytes or string.
        content_type: MIME type hint (default: application/json).
        extra_sensitive_keys: Provider-specific sensitive key names.
        extra_sensitive_headers: Provider-specific sensitive header names.

    Returns:
        Sanitized content as UTF-8 bytes.
    """
    if isinstance(raw_content, bytes):
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            # Binary content — cannot inspect, return as-is
            return raw_content
    else:
        text = raw_content

    # JSON responses: structured redaction
    if "json" in content_type.lower():
        import json as _json
        try:
            parsed = _json.loads(text)
            cleaned = redact_mapping(parsed, extra_sensitive_keys=extra_sensitive_keys)
            return _json.dumps(cleaned, ensure_ascii=False, indent=2).encode("utf-8")
        except _json.JSONDecodeError:
            pass  # Fall through to text redaction

    # Text responses: pattern-based redaction
    cleaned_text = redact_text(text)
    return cleaned_text.encode("utf-8")
