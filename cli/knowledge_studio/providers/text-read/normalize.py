"""Normalize text file content into an EvidenceFragment.

Pure function — no network, no filesystem writes, no tool calls.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def normalize(
    source_id: str,
    raw_output: bytes | str,
    *,
    provider_version: str | None = None,
    cost: dict[str, Any] | None = None,
    filename: str = "content.md",
) -> dict[str, Any]:
    """Convert raw text file content into an EvidenceFragment dict.

    Args:
        source_id: SourceEnvelope.source_id this fragment belongs to.
        raw_output: Raw file bytes or decoded string.
        provider_version: Not applicable for text-read.
        cost: Always 0 for local reads.
        filename: Original filename for locator reference.

    Returns:
        EvidenceFragment as a dict (oks-evidence-fragment/v0.1).
    """
    if isinstance(raw_output, str):
        content_bytes = raw_output.encode("utf-8")
    else:
        content_bytes = raw_output
        raw_output = content_bytes.decode("utf-8", errors="replace")

    content_hash = sha256(content_bytes).hexdigest()
    fragment_id = f"frag-{content_hash[:12]}"

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": fragment_id,
        "source_id": source_id,
        "producer": "agent-runtime",
        "producer_version": provider_version,
        "status": "succeeded" if len(content_bytes) > 0 else "failed",
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
                "method": "agent_direct_read",
                "locator": {
                    "kind": "document",
                    "document_section": filename,
                },
                "text": raw_output[:2000] if len(raw_output) > 2000 else raw_output,
                "confidence": 1.0,
                "agent_judgment": "agent_observed",
            }
        ],
        "modalities": {
            "text": {
                "modality": "text",
                "status": "succeeded" if len(content_bytes) > 0 else "failed",
                "evidence_count": 1,
            }
        },
        "warnings": [],
        "provenance": {
            "tool": "agent.direct_read",
            "tool_version": provider_version,
        },
    }
