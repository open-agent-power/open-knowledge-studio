"""Modality detection — determine what type of input we're dealing with.

Maps inputs to modality strings that handlers can match against.
This is a hint layer — handlers still have the final say via detect().
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXTENSIONS = {".pdf"}

VIDEO_HOSTS = {"youtube.com", "youtu.be", "www.youtube.com", "bilibili.com", "www.bilibili.com", "vimeo.com"}


def detect_modality(input_path: str) -> str:
    """Detect the modality of an input.

    Args:
        input_path: URL, file path, or directory path

    Returns:
        One of: 'web', 'pdf', 'video', 'audio', 'image', 'repo', 'markdown', 'unknown'
    """
    if input_path.startswith(("http://", "https://")):
        parsed = urlparse(input_path)
        host = parsed.hostname or ""

        if host in VIDEO_HOSTS:
            return "video"

        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in PDF_EXTENSIONS):
            return "pdf"
        if any(path_lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
            return "video"
        if any(path_lower.endswith(ext) for ext in AUDIO_EXTENSIONS):
            return "audio"
        if any(path_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
            return "image"

        return "web"

    path = Path(input_path)

    if path.is_dir():
        if (path / ".git").exists() or (path / "package.json").exists() or (path / "Cargo.toml").exists():
            return "repo"
        return "repo"

    suffix = path.suffix.lower()
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".txt"}:
        return "note"

    return "unknown"
