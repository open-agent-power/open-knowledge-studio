"""Feishu worker I/O utilities -- atomic writes, hashing, redaction, helpers.

Extracted from feishu_base_worker.py (Round 3 Phase 1B).  TRUE leaf module:
zero imports from feishu_base_worker and zero imports from future worker modules.
The original module re-exports every name for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
# Match access_token / token / key / value assignments that carry a
# plausibly secret parameter (query-string or colon/equals style).
# Trigger only when the right-hand side is >= 8 base64-ish characters.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?:(?:access[_\-]?token|api[_\-]?key|app[_\-]?secret|secret[_\-]?key"
    r"|token|key|value)\s*[=:]\s*)"
    r"[A-Za-z0-9\-._~+/]{8,}",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    """Persist the rename itself, per CONSTITUTION A5."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _redact_error_text(text: str) -> str:
    """Remove Bearer tokens, credential assignments, and home-directory paths.

    Covers Bearer auth headers, ``access_token=...`` / ``token=...`` /
    ``key=...`` / ``value=...`` parameter assignments (>=8-char value),
    and home-directory file paths. Callers must truncate after redaction;
    this function only redacts.
    """
    if not text:
        return text
    result = BEARER_RE.sub("Bearer ***", text)
    result = _SECRET_ASSIGNMENT_RE.sub(
        lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0].rstrip() + "=***",
        result,
    )
    home_str = str(HOME)
    if home_str and len(home_str) > 4:
        result = result.replace(home_str, "~")
        alt = home_str.replace("\\", "/")
        if alt != home_str:
            result = result.replace(alt, "~")
    return result


def scalar_cell(value: object) -> object:
    """Normalize Base single-select reads without changing multi-value fields."""
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def content_type_extension(content_type: str | None) -> str:
    return {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }.get((content_type or "").split(";", 1)[0].strip().lower(), "")


def attachment_capability(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
        return "image.rapidocr", "ocr"
    if suffix == ".pdf":
        return "pdf.mineru", "text"
    if suffix in {".mp4", ".webm", ".mov", ".mkv", ".avi"}:
        return "video.watch", "asr"
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
        return "audio.faster-whisper", "asr"
    return "office.markitdown", "text"
