"""Normalize FFmpeg probe/keyframe output into an EvidenceFragment.

Pure function — input is metadata JSON or keyframe file list from ffmpeg.
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
    """Convert FFmpeg output into an EvidenceFragment.

    Args:
        source_id: SourceEnvelope.source_id.
        raw_output: Dict with optional keys:
            ``probe`` — media probe dict (duration, codec, resolution, fps, ...)
            ``keyframes`` — list of keyframe file paths
            ``audio_track`` — path to extracted audio file
        provider_version: FFmpeg version.
        cost: Always 0 for local processing.

    Returns:
        EvidenceFragment dict.
    """
    if not isinstance(raw_output, dict):
        raise ValueError("raw_output must be a dict with probe/keyframes keys")

    probe = raw_output.get("probe", {}) if isinstance(raw_output.get("probe"), dict) else {}
    keyframes = raw_output.get("keyframes")
    audio_path = raw_output.get("audio_track")

    evidence_records: list[dict[str, Any]] = []
    all_text: list[str] = []

    # Probe metadata
    if probe:
        metadata_text = ", ".join(
            f"{k}={v}" for k, v in probe.items() if v is not None
        )
        all_text.append(f"Media: {metadata_text}")
        evidence_records.append({
            "evidence_id": f"ev-probe-{source_id[:8]}",
            "artifact_id": "metadata",
            "kind": "text",
            "method": "ffprobe",
            "locator": {"kind": "custom", "custom_label": "media-probe"},
            "text": metadata_text,
            "confidence": 1.0,
            "agent_judgment": "mechanical",
        })

    # Keyframes
    if isinstance(keyframes, list) and keyframes:
        all_text.append(f"{len(keyframes)} keyframes extracted")
        evidence_records.append({
            "evidence_id": f"ev-keyframe-{source_id[:8]}",
            "artifact_id": "keyframes",
            "kind": "text",
            "method": "scene_detection",
            "locator": {"kind": "custom", "custom_label": "keyframe-list"},
            "text": f"{len(keyframes)} keyframes extracted",
            "confidence": 1.0,
            "agent_judgment": "mechanical",
        })

    # Audio track
    if audio_path:
        all_text.append(f"Audio track extracted to {audio_path}")
        evidence_records.append({
            "evidence_id": f"ev-audio-{source_id[:8]}",
            "artifact_id": "audio",
            "kind": "text",
            "method": "ffmpeg_audio_extract",
            "locator": {"kind": "custom", "custom_label": "audio-extract"},
            "text": f"Audio extracted to {audio_path}",
            "confidence": 1.0,
            "agent_judgment": "mechanical",
        })

    content_md = "\n".join(all_text) if all_text else "# No media data"
    content_bytes = content_md.encode("utf-8")
    content_hash = sha256(content_bytes).hexdigest()

    warnings: list[str] = []
    if not probe:
        warnings.append("No media probe data — ffprobe may have failed or been skipped.")
    if not keyframes and not audio_path:
        warnings.append("No keyframes or audio track extracted. Visual/audio analysis is limited.")

    return {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": f"frag-{content_hash[:12]}",
        "source_id": source_id,
        "producer": "ffmpeg",
        "producer_version": provider_version,
        "status": "succeeded" if evidence_records else "partial",
        "artifacts": [
            {
                "artifact_id": "metadata",
                "kind": "other",
                "path": "probe.json",
                "sha256": content_hash,
                "locator_kind": "custom",
            }
        ],
        "evidence": evidence_records,
        "modalities": {
            "text": {
                "modality": "text",
                "status": "succeeded" if evidence_records else "partial",
                "evidence_count": len(evidence_records),
            }
        },
        "warnings": warnings,
        "provenance": {
            "tool": "ffmpeg",
            "tool_version": provider_version,
        },
    }
