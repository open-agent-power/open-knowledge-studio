"""Text file adapter — reads .md/.txt/.csv sources into CaptureResult.

This is the simplest adapter pattern.  It reads local text files directly
without any external extractor dependency.  Used as the primary capture
path for text-modality sources.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from capture_contract import (
    CapabilityStatus,
    CaptureEvidence,
    CaptureRequest,
    CaptureResult,
    ModalityResult,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_path(source_uri: str) -> Path:
    """Resolve a source URI (local path, file:// URI, or Windows path) to a Path."""
    import os as _os
    import re as _re
    from urllib.request import url2pathname
    from urllib.parse import unquote

    # Windows absolute paths (e.g. D:\foo or \\server\share)
    if _os.name == "nt" and (
        _re.match(r"^[A-Za-z]:[\\/]", source_uri) or source_uri.startswith("\\\\")
    ):
        return Path(source_uri).expanduser().resolve()

    parsed = urlparse(source_uri)
    if parsed.scheme == "file":
        raw = url2pathname(unquote(parsed.path))
        if _os.name == "nt" and _re.match(r"^[\\/][A-Za-z]:", raw):
            raw = raw[1:]
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(path)

    if parsed.scheme:
        raise ValueError("text adapter accepts local files only")

    return Path(source_uri).expanduser().resolve()


class TextAdapter:
    """Capture .md, .txt, .csv files — no external dependencies."""

    def probe(self, request: CaptureRequest) -> CapabilityStatus:
        try:
            source = _local_path(request.source_uri)
        except ValueError as exc:
            return CapabilityStatus(False, str(exc))
        if not source.is_file():
            return CapabilityStatus(False, "source file not found")
        suffix = source.suffix.lower()
        if suffix not in {".md", ".txt", ".csv", ".markdown", ".text"}:
            return CapabilityStatus(False, f"unsupported text suffix: {suffix}")
        return CapabilityStatus(True)

    def capture(self, request: CaptureRequest) -> CaptureResult:
        source = _local_path(request.source_uri)
        if not source.is_file():
            raise FileNotFoundError(source)

        started_at = _utc_now()
        started = __import__("time").monotonic()
        raw_bytes = source.read_bytes()
        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw_bytes.decode("gbk")
            except UnicodeDecodeError:
                content = raw_bytes.decode("utf-8", errors="replace")
        latency_ms = round((__import__("time").monotonic() - started) * 1000)
        finished_at = _utc_now()

        has_content = len(content.strip()) > 0

        return CaptureResult(
            status="complete" if has_content else "partial",
            provider="oks-connector",
            provider_version="0.3.0",
            capability="text.markdown",
            source_uri=str(source),
            snapshot_path=source,
            snapshot_media_type=None,
            content_markdown=content,
            title=source.stem,
            modalities={
                "text": ModalityResult(
                    "succeeded" if has_content else "partial",
                    evidence_count=1,
                ),
            },
            evidence=(
                CaptureEvidence(
                    kind="text",
                    method="file_read",
                    locator={"kind": "document", "document_section": source.name},
                    text=content[:2000] if len(content) > 2000 else content,
                ),
            ),
            latency_ms=latency_ms,
            warnings=() if has_content else ("file is empty",),
            failure_disposition="none" if has_content else "needs_user_action",
            started_at=started_at,
            finished_at=finished_at,
        )
