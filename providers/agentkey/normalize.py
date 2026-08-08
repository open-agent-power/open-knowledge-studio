"""Normalize AgentKey / TikHub response into an EvidenceFragment.

Pure function — input is the saved JSON response from an AgentKey MCP
execute_tool call.  Classifies results as full, partial, or metadata_only.
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
    platform: str = "",
    anchors: list[str] | None = None,
) -> dict[str, Any]:
    """Convert AgentKey API response into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: AgentKey response dict.  Structure varies by platform.
        provider_version: TikHub API version.
        cost: Credit cost dict.
        platform: Platform name (zhihu, wechat, bilibili) for classification.
        anchors: List of anchor strings to verify in content for 'full' status.

    Returns:
        EvidenceFragment dict.
    """
    if not isinstance(raw_output, dict):
        raise ValueError("raw_output must be an AgentKey API response dict")

    # Extract content — structure varies by platform
    data = raw_output.get("data", {}) if isinstance(raw_output.get("data"), dict) else {}
    content_text = str(
        data.get("content_text")
        or data.get("content")
        or data.get("text")
        or data.get("body")
        or ""
    ).strip()
    title = str(
        data.get("title")
        or raw_output.get("title", "")
    ).strip()

    bv_id = str(data.get("bv_id") or data.get("bvid") or "")
    aid = str(data.get("aid") or "")
    cid = str(data.get("cid") or "")

    content_bytes = content_text.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()

    # Classify status
    has_text = len(content_text) > 0
    has_metadata = bool(title or bv_id or aid)
    anchors_matched = False
    if anchors and has_text:
        anchors_matched = all(a in content_text for a in anchors)

    if has_text and (not anchors or anchors_matched):
        fragment_status = "succeeded"
    elif has_text and anchors and not anchors_matched:
        fragment_status = "partial"
    elif has_metadata:
        fragment_status = "partial"
    else:
        fragment_status = "failed"

    warnings: list[str] = []
    if fragment_status == "partial" and has_text and not anchors_matched:
        warnings.append(
            "Content text available but strict anchor verification failed. "
            "Title may be readable but hidden punctuation/normalization differs."
        )
    if fragment_status == "partial" and not has_text and has_metadata:
        warnings.append(
            "metadata_only — title and identifiers available, no content text. "
            "This is NOT a successful content extraction."
        )
    if platform in ("bilibili",) and not content_text:
        warnings.append(
            "AgentKey Bilibili endpoint returns metadata (title, BV, aid/cid) "
            "but no subtitle body.  Use yt-dlp for subtitle extraction."
        )

    evidence_records: list[dict[str, Any]] = []
    if has_text:
        evidence_records.append({
            "evidence_id": f"ev-{content_hash[:12]}",
            "artifact_id": "api-response",
            "kind": "text",
            "method": "agentkey_api",
            "locator": {"kind": "custom", "custom_label": f"{platform}-content"},
            "text": content_text[:2000] if len(content_text) > 2000 else content_text,
            "confidence": 1.0 if anchors_matched else None,
            "agent_judgment": "mechanical",
        })
    if has_metadata:
        evidence_records.append({
            "evidence_id": f"ev-meta-{content_hash[:8]}",
            "artifact_id": "api-response",
            "kind": "text",
            "method": "agentkey_api",
            "locator": {"kind": "custom", "custom_label": f"{platform}-metadata"},
            "text": f"title={title}, bv={bv_id}, aid={aid}, cid={cid}",
            "confidence": 1.0,
            "agent_judgment": "mechanical",
        })

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "agentkey",
        "producer_version": provider_version,
        "status": fragment_status,
        "artifacts": [
            {
                "artifact_id": "api-response",
                "kind": "api_response",
                "path": "api-response.json",
                "sha256": content_hash,
                "locator_kind": "custom",
            }
        ],
        "evidence": evidence_records,
        "modalities": {
            "text": {
                "modality": "text",
                "status": (
                    "succeeded" if fragment_status == "succeeded"
                    else "partial" if evidence_records
                    else "failed"
                ),
                "evidence_count": len(evidence_records),
            }
        },
        "warnings": warnings,
        "cost": cost,
        "provenance": {
            "tool": "agentkey",
            "tool_version": provider_version,
            "endpoint": f"{platform}.fetch",
        },
    }
