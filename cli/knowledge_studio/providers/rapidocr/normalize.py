"""Normalize RapidOCR block output into an EvidenceFragment.

Pure function — input is the OCR blocks list from RapidOCR engine.
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
    image_path: str = "source.jpg",
) -> dict[str, Any]:
    """Convert RapidOCR block list into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: List of OCR block dicts, each with ``text``, ``confidence``,
            and ``bbox`` [x1, y1, x2, y2].
        provider_version: RapidOCR version.
        cost: Always 0 for local OCR.
        image_path: Original image filename for locator.

    Returns:
        EvidenceFragment dict.
    """
    if not isinstance(raw_output, list):
        raise ValueError("raw_output must be a list of OCR block dicts")

    evidence_records: list[dict[str, Any]] = []
    all_text: list[str] = []

    for i, block in enumerate(raw_output):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", "")).strip()
        confidence = block.get("confidence")
        bbox = block.get("bbox")

        if confidence is not None:
            confidence = float(confidence)

        all_text.append(text)
        locator: dict[str, Any] = {"kind": "bbox"}
        if bbox and len(bbox) == 4:
            locator["bbox"] = [float(v) for v in bbox]
        evidence_records.append({
            "evidence_id": f"ev-ocr-{i:03d}",
            "artifact_id": "ocr-result",
            "kind": "text",
            "method": "rapidocr_engine",
            "locator": locator,
            "text": text or None,
            "confidence": confidence,
            "agent_judgment": "mechanical",
        })

    content_md = "\n".join(t for t in all_text if t)
    content_bytes = content_md.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()
    has_text = len(content_md.strip()) > 0

    warnings: list[str] = []
    if not has_text:
        warnings.append("OCR returned no text — image may be blank or unrecognizable.")
    else:
        warnings.append(
            "OCR provides bbox and character confidence only. "
            "Use agent-runtime (image.observe) for page-level semantics."
        )

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "rapidocr",
        "producer_version": provider_version,
        "status": "succeeded" if has_text else "partial",
        "artifacts": [
            {
                "artifact_id": "ocr-result",
                "kind": "ocr_result",
                "path": "ocr-result.json",
                "sha256": content_hash,
                "locator_kind": "bbox",
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
            "tool": "rapidocr",
            "tool_version": provider_version,
        },
    }
