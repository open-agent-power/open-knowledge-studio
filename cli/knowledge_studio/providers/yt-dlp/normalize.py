"""Normalize yt-dlp subtitle/metadata output into an EvidenceFragment.

Pure function — input is the raw subtitle text and/or metadata JSON from yt-dlp.
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
    """Convert yt-dlp output into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: Dict with optional keys:
            ``subtitle_text`` — raw subtitle content as string.
            ``subtitle_segments`` — list of {start_ms, end_ms, text}.
            ``metadata`` — dict with title, duration, upload_date, etc.
        provider_version: yt-dlp version.
        cost: Always 0 for local extraction (except platform API credits).

    Returns:
        EvidenceFragment dict.
    """
    if not isinstance(raw_output, dict):
        raise ValueError("raw_output must be a dict with subtitle/metadata keys")

    subtitle_text = str(raw_output.get("subtitle_text", "") or "")
    segments = raw_output.get("subtitle_segments")
    metadata = raw_output.get("metadata", {}) if isinstance(raw_output.get("metadata"), dict) else {}
    title = str(metadata.get("title", "") or "")

    evidence_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    # If structured segments available, use them for timestamped evidence
    if isinstance(segments, list) and segments:
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            evidence_records.append({
                "evidence_id": f"ev-sub-{i:04d}",
                "artifact_id": "subtitle",
                "kind": "text",
                "method": "platform_subtitle",
                "locator": {
                    "kind": "timestamp",
                    "start_ms": float(seg.get("start_ms", 0)),
                    "end_ms": float(seg.get("end_ms", 0)),
                },
                "text": str(seg.get("text", "")),
                "confidence": None,
                "agent_judgment": "mechanical",
            })
        content_md = subtitle_text
    elif subtitle_text.strip():
        evidence_records.append({
            "evidence_id": f"ev-sub-0000",
            "artifact_id": "subtitle",
            "kind": "text",
            "method": "platform_subtitle",
            "locator": {"kind": "custom", "custom_label": "subtitle-full"},
            "text": subtitle_text[:2000] if len(subtitle_text) > 2000 else subtitle_text,
            "confidence": None,
            "agent_judgment": "mechanical",
        })
        content_md = subtitle_text
        if len(subtitle_text) < 50:
            warnings.append("Subtitle text < 50 chars — may be incomplete or auto-generated.")
    else:
        content_md = "# No subtitle content\n"
        warnings.append("No subtitle content extracted.")

    # Metadata evidence
    if title:
        evidence_records.append({
            "evidence_id": "ev-meta-0000",
            "artifact_id": "metadata",
            "kind": "text",
            "method": "platform_metadata",
            "locator": {"kind": "custom", "custom_label": "video-metadata"},
            "text": f"title={title}",
            "confidence": 1.0,
            "agent_judgment": "mechanical",
        })

    content_bytes = content_md.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()
    has_subtitle = bool(subtitle_text.strip())

    if not has_subtitle:
        warnings.insert(0, "metadata_only — no subtitle content. Use ASR or human transcription.")

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "yt-dlp",
        "producer_version": provider_version,
        "status": "succeeded" if has_subtitle else "partial",
        "artifacts": [
            {
                "artifact_id": "subtitle",
                "kind": "subtitle",
                "path": "subtitle.srt",
                "sha256": content_hash,
                "locator_kind": "timestamp",
            }
        ],
        "evidence": evidence_records,
        "modalities": {
            "text": {
                "modality": "text",
                "status": "succeeded" if has_subtitle else "partial",
                "evidence_count": len([e for e in evidence_records if e["artifact_id"] == "subtitle"]),
            }
        },
        "warnings": warnings,
        "cost": cost,
        "provenance": {
            "tool": "yt-dlp",
            "tool_version": provider_version,
        },
    }
