"""Normalize pymupdf4llm page-chunk output into an EvidenceFragment.

Pure function — no network, no filesystem writes, no tool calls.
Input is the return value of ``pymupdf4llm.to_markdown(doc, page_chunks=True)``.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def normalize(
    source_id: str,
    raw_output: list[dict[str, Any]],
    *,
    provider_version: str | None = None,
    cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert pymupdf4llm page-chunk list into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: List of page dicts from pymupdf4llm.to_markdown(page_chunks=True).
            Each dict has ``metadata`` (page number, title) and ``text``.
        provider_version: pymupdf4llm version string.
        cost: Always 0 for local extraction.

    Returns:
        EvidenceFragment dict (oks-evidence-fragment/v0.1).
    """
    if not isinstance(raw_output, list):
        raise ValueError("raw_output must be a list of page dicts from pymupdf4llm")

    sections: list[str] = []
    evidence_records: list[dict[str, Any]] = []
    title: str | None = None
    text_chars = 0
    total_pages = len(raw_output)

    for index, page in enumerate(raw_output, start=1):
        if not isinstance(page, dict):
            raise TypeError(f"page {index} must be a dict, got {type(page)}")
        meta = page.get("metadata", {}) if isinstance(page.get("metadata"), dict) else {}
        page_num = meta.get("page") or index
        title = title or (meta.get("title") or None)
        page_text = page.get("text", "") if isinstance(page.get("text"), str) else ""
        clean = page_text.strip()
        text_chars += len(clean)
        sections.append(f"<!-- Page {page_num} -->\n\n{clean}".rstrip())
        evidence_records.append({
            "evidence_id": f"ev-p{page_num}-{source_id[:8]}",
            "artifact_id": "content",
            "kind": "text",
            "method": "pdf_text_layer",
            "locator": {"kind": "page", "page": page_num, "total_pages": total_pages},
            "text": clean or None,
            "confidence": 1.0 if clean else None,
            "agent_judgment": "mechanical",
        })

    content_md = "\n\n".join(sections).rstrip()
    content_bytes = content_md.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()
    fragment_id = f"frag-{content_hash[:12]}"
    has_text = text_chars > 0

    warnings: list[str] = []
    if not has_text:
        warnings.append(
            "PDF text layer is empty; use remote OCR fallback and keep this result partial."
        )

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": fragment_id,
        "source_id": source_id,
        "producer": "pdf-lite",
        "producer_version": provider_version,
        "status": "succeeded" if has_text else "partial",
        "artifacts": [
            {
                "artifact_id": "content",
                "kind": "primary_text",
                "path": "content.md",
                "sha256": content_hash,
                "locator_kind": "page",
            }
        ],
        "evidence": evidence_records,
        "modalities": {
            "text": {
                "modality": "text",
                "status": "succeeded" if has_text else "partial",
                "evidence_count": len(evidence_records),
            }
        },
        "warnings": warnings,
        "provenance": {
            "tool": "pymupdf4llm",
            "tool_version": provider_version,
        },
    }
