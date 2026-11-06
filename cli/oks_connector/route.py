"""Source-type detection and extractor routing.

The single entry point is ``route_plan(source) -> dict``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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


def route_plan(source: str) -> dict[str, Any]:
    parsed = urlparse(source)
    suffix = Path(parsed.path if is_url(source) else source).suffix.lower()
    platform = platform_for(source)
    video_suffixes = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
    audio_suffixes = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
    office_suffixes = {".pptx", ".docx", ".xlsx", ".html", ".htm", ".txt", ".csv", ".md"}
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
    if is_url(source) and platform in {"bilibili", "douyin", "youtube"}:
        return {
            "source_type": "video", "platform": platform,
            "modalities": ["speech", "video", "on_screen_text"],
            "extractor": "watch",
            "route": ["platform_caption", "media_acquire", "asr", "keyframe", "ocr"],
        }
    if suffix in video_suffixes:
        return {
            "source_type": "video", "platform": platform,
            "modalities": ["speech", "video", "on_screen_text"],
            "extractor": "watch",
            "route": ["embedded_caption", "asr", "keyframe", "ocr"],
        }
    if suffix in audio_suffixes:
        return {
            "source_type": "audio", "platform": platform,
            "modalities": ["speech"], "extractor": "watch",
            "route": ["embedded_transcript", "asr"],
        }
    if suffix == ".pdf":
        return {
            "source_type": "document", "platform": platform,
            "modalities": ["text", "layout", "image", "formula"],
            "extractor": "mineru",
            "route": ["text_layer", "layout", "ocr", "formula", "asset_copy"],
        }
    if suffix in office_suffixes:
        return {
            "source_type": "document", "platform": platform,
            "modalities": ["text", "layout", "image"],
            "extractor": "markitdown",
            "route": ["native_structure", "markdown", "embedded_media"],
        }
    if suffix in image_suffixes:
        return {
            "source_type": "image", "platform": platform,
            "modalities": ["image", "on_screen_text"],
            "extractor": "rapidocr",
            "route": ["ocr", "bbox", "original_asset"],
        }
    return {
        "source_type": "unknown", "platform": platform,
        "modalities": [], "extractor": None,
        "route": ["human_fallback"], "implementation_status": "unsupported",
        "diagnostics": {
            "detected_extension": suffix or None,
            "detected_source": source,
            "is_url": is_url(source),
            "url_platform": platform if is_url(source) else None,
            "supported_extensions": {
                "视频": sorted(video_suffixes), "音频": sorted(audio_suffixes),
                "文档": sorted(office_suffixes) + [".pdf"], "图片": sorted(image_suffixes),
            },
            "suggestion": (
                "请输入平台视频链接 (YouTube/Bilibili/抖音)，或本地文件。支持的本地文件："
                + str(sorted(video_suffixes | audio_suffixes | office_suffixes | {".pdf"} | image_suffixes))
                if not is_url(source) else
                "仅支持 YouTube、Bilibili、抖音平台的视频链接。"
                " 普通网页请先用浏览器采集工具下载为本地文件再导入。"
            ),
        },
    }
