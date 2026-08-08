"""Normalize MarkItDown output into an EvidenceFragment.

Pure function — input is the Markdown text and metadata from MarkItDown.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def normalize(
    source_id: str,
    raw_output: str | dict[str, Any],
    *,
    provider_version: str | None = None,
    cost: dict[str, Any] | None = None,
    filename: str = "document",
) -> dict[str, Any]:
    """Convert MarkItDown output into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: Markdown string from MarkItDown conversion, or a dict
            with 'text' and optional 'metadata' keys.
        provider_version: MarkItDown version.
        cost: Always 0 for local conversion.
        filename: Original filename for locator.

    Returns:
        EvidenceFragment dict.
    """
    if isinstance(raw_output, dict):
        text = str(raw_output.get("text", "") or "")
    else:
        text = str(raw_output or "")

    content_bytes = text.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()
    has_text = len(text.strip()) > 0

    warnings: list[str] = []
    if not has_text:
        warnings.append("MarkItDown produced empty output — source may be unreadable.")
    else:
        warnings.append(
            "MarkItDown evidence is document-level only. "
            "Structural elements (tables, headings) may be preserved "
            "but formula cells and embedded media may be missing. "
            "Complex layouts may need agent-runtime visual supplement."
        )

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "markitdown",
        "producer_version": provider_version,
        "status": "succeeded" if has_text else "partial",
        "artifacts": [
            {
                "artifact_id": "content",
                "kind": "primary_text",
                "path": "content.md",
                "sha256": content_hash,
                "locator_kind": "document",
            }
        ],
        "evidence": [
            {
                "evidence_id": f"ev-{content_hash[:12]}",
                "artifact_id": "content",
                "kind": "text",
                "method": "markitdown",
                "locator": {
                    "kind": "document",
                    "document_section": filename,
                },
                "text": text[:2000] if len(text) > 2000 else text,
                "confidence": 0.85,
                "agent_judgment": "mechanical",
            }
        ],
        "modalities": {
            "text": {
                "modality": "text",
                "status": "succeeded" if has_text else "partial",
                "evidence_count": 1 if has_text else 0,
            }
        },
        "warnings": warnings,
        "provenance": {
            "tool": "markitdown",
            "tool_version": provider_version,
        },
    }
