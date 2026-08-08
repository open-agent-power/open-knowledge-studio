"""Source-type detection.

Protocol v0.1: ``describe_source(source) -> SourceDescriptor`` is the canonical
entry point.  It describes *what* the source is without deciding *how* to
capture it.

Legacy ``route_plan()`` was removed in v0.4.0 along with ``network.py``,
``scripts/extractors/``, and ``scripts/experiments/``.
New providers MUST use describe_source → EvidenceFragment → EvidenceManifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"})
SUPPORTED_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"})
SUPPORTED_OFFICE_SUFFIXES = frozenset({".pptx", ".docx", ".xlsx", ".html", ".htm", ".txt", ".csv", ".md"})
SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"})

CONTENT_EXPECTATIONS: dict[str, dict[str, str]] = {
    ("video", "bilibili"): "transcript",
    ("video", "douyin"): "transcript",
    ("video", "youtube"): "transcript",
    ("video", "local"): "media_metadata",
    ("audio", "local"): "transcript",
    ("document", "local"): "article",
    ("image", "local"): "ocr_text",
}


@dataclass(frozen=True)
class SourceDescriptor:
    """Pure source description — no extractor or route decisions baked in."""

    source_modality: str  # pdf, office, image, video, audio, web, text, unknown
    access_mode: str       # local_file, public_url, authenticated_remote, user_browser, feishu_form
    platform: str | None   # bilibili, douyin, weibo, zhihu, github, ... or None
    mime_type: str | None
    content_expectation: str  # transcript, article, metadata, ocr_text, ...
    network_policy: tuple[str, ...]  # ["platform_api", "user_authenticated_browser"]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_modality": self.source_modality,
            "access_mode": self.access_mode,
            "platform": self.platform,
            "mime_type": self.mime_type,
            "content_expectation": self.content_expectation,
            "network_policy": list(self.network_policy),
            "diagnostics": dict(self.diagnostics),
        }


def is_url(value: str) -> bool:
    return urlparse(value).scheme.lower() in {"http", "https"}


def platform_for(source: str) -> str:
    if not is_url(source):
        return "local"
    host = (urlparse(source).hostname or "").lower()
    if host == "bilibili.com" or host.endswith(".bilibili.com") or host == "b23.tv":
        return "bilibili"
    if host == "douyin.com" or host.endswith(".douyin.com"):
        return "douyin"
    if host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        return "youtube"
    return host or "web"


def _suffix_for(source: str) -> str:
    if is_url(source):
        return Path(urlparse(source).path).suffix.lower()
    return Path(source).suffix.lower()


def describe_source(source: str) -> SourceDescriptor:
    """Return a pure source description without choosing an extractor.

    This is the canonical entry point for the unified capture protocol.
    Callers that still need the legacy extractor/route fields should use
    ``route_plan()`` instead.
    """
    suffix = _suffix_for(source)
    platform = platform_for(source)
    is_local = not is_url(source)
    access_mode = "local_file" if is_local else _access_mode_for(platform)
    network_policy: tuple[str, ...] = _network_policy_for(platform, is_local)
    modality = _classify_modality(suffix, platform, is_local)
    expectation = CONTENT_EXPECTATIONS.get((modality, platform if not is_local else "local"), "article")

    diag: dict[str, Any] = {
        "detected_extension": suffix or None,
        "detected_source": source,
        "is_url": not is_local,
        "url_platform": platform if not is_local else None,
    }
    if modality == "unknown":
        diag["supported_extensions"] = {
            "video": sorted(SUPPORTED_VIDEO_SUFFIXES),
            "audio": sorted(SUPPORTED_AUDIO_SUFFIXES),
            "document": sorted(SUPPORTED_OFFICE_SUFFIXES) + [".pdf"],
            "image": sorted(SUPPORTED_IMAGE_SUFFIXES),
        }
        diag["suggestion"] = (
            "supported local files: "
            + str(sorted(SUPPORTED_VIDEO_SUFFIXES | SUPPORTED_AUDIO_SUFFIXES
                         | SUPPORTED_OFFICE_SUFFIXES | {".pdf"} | SUPPORTED_IMAGE_SUFFIXES))
            if is_local else
            "platform URLs: YouTube, Bilibili, Douyin. "
            "For web pages, save as local file first."
        )

    return SourceDescriptor(
        source_modality=modality,
        access_mode=access_mode,
        platform=platform if not is_local else None,
        mime_type=None,
        content_expectation=expectation,
        network_policy=network_policy,
        diagnostics=diag,
    )


def _access_mode_for(platform: str) -> str:
    """Derive access mode from platform identity, not extractor choice."""
    if platform in {"bilibili", "douyin"}:
        return "authenticated_remote"
    if platform in {"youtube"}:
        return "public_url"
    return "public_url"


def _network_policy_for(platform: str, is_local: bool) -> tuple[str, ...]:
    if is_local:
        return ("offline",)
    if platform in {"bilibili", "douyin"}:
        return ("platform_api", "user_authenticated_browser")
    if platform in {"youtube"}:
        return ("public_http",)
    return ("public_http",)


def _classify_modality(suffix: str, platform: str, is_local: bool) -> str:
    """Classify source into a stable modality without extractor coupling."""
    if not is_local and platform in {"bilibili", "douyin", "youtube"}:
        return "video"
    if suffix in SUPPORTED_VIDEO_SUFFIXES:
        return "video"
    if suffix in SUPPORTED_AUDIO_SUFFIXES:
        return "audio"
    if suffix == ".pdf":
        return "pdf"
    if suffix in SUPPORTED_OFFICE_SUFFIXES:
        if suffix in {".md", ".txt"}:
            return "text"
        if suffix in {".html", ".htm"}:
            return "web"
        return "office"
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return "image"
    return "unknown"


# ── Legacy route_plan — removed in v0.4.0 (network.py was its only consumer). ──
# describe_source() and SourceDescriptor above are the canonical entry points.

