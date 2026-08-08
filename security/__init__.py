"""OKS unified remote security module.

Provider-agnostic credential redaction.  Individual providers declare
extra sensitive fields in their provider.yaml — they do NOT copy or
re-implement redaction logic.

Exports:
    redact_headers()       — replace sensitive HTTP header values
    redact_mapping()       — recursively redact sensitive dict keys
    redact_text()          — pattern-based free-text credential scrubbing
    sanitize_remote_artifact() — full response artifact sanitization
"""

from .redaction import (
    redact_headers,
    redact_mapping,
    redact_text,
    sanitize_remote_artifact,
)

__all__ = [
    "redact_headers",
    "redact_mapping",
    "redact_text",
    "sanitize_remote_artifact",
]
