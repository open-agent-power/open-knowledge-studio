"""Normalize Firecrawl API response into an EvidenceFragment.

Pure function — input is the JSON response from Firecrawl /scrape or /parse.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def normalize(
    source_id: str,
    raw_output: dict[str, Any],
    *,
    provider_version: str | None = None,
    cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert Firecrawl API response into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: Firecrawl response dict with ``data.markdown``,
            ``data.metadata.title``, ``data.metadata.statusCode``.
        provider_version: Firecrawl API version.
        cost: Credit cost dict (e.g., {"amount": 1, "unit": "credit"}).

    Returns:
        EvidenceFragment dict.
    """
    if not isinstance(raw_output, dict):
        raise ValueError("raw_output must be a Firecrawl API response dict")

    data = raw_output.get("data", {}) if isinstance(raw_output.get("data"), dict) else {}
    markdown = str(data.get("markdown", "") or "")
    title = str(data.get("metadata", {}).get("title", "") or "") if isinstance(data.get("metadata"), dict) else ""
    status_code = data.get("metadata", {}).get("statusCode") if isinstance(data.get("metadata"), dict) else None

    content_bytes = markdown.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()
    has_content = len(markdown.strip()) > 0

    # Determine status
    if status_code is not None and status_code >= 400:
        fragment_status = "failed"
        warnings_list = [f"Firecrawl returned HTTP {status_code}"]
    elif not has_content:
        fragment_status = "failed"
        warnings_list = ["Firecrawl returned empty content"]
    elif len(markdown.strip()) < 100:
        fragment_status = "partial"
        warnings_list = [
            "Content < 100 characters — may be an anti-bot challenge page. "
            "Do not claim this as a successful extraction."
        ]
    else:
        fragment_status = "succeeded"
        warnings_list = []

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "firecrawl",
        "producer_version": provider_version,
        "status": fragment_status,
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
                "method": "firecrawl_scrape",
                "locator": {"kind": "document", "document_section": title or "webpage"},
                "text": markdown[:2000] if len(markdown) > 2000 else markdown,
                "confidence": None,
                "agent_judgment": "mechanical",
            }
        ],
        "modalities": {
            "text": {
                "modality": "text",
                "status": (
                    "succeeded" if fragment_status == "succeeded"
                    else "partial" if fragment_status == "partial"
                    else "failed"
                ),
                "evidence_count": 1 if has_content else 0,
            }
        },
        "warnings": warnings_list,
        "cost": cost,
        "provenance": {
            "tool": "firecrawl",
            "tool_version": provider_version,
            "endpoint": raw_output.get("_endpoint"),
        },
    }
