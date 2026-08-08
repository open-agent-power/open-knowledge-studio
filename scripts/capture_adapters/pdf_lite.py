"""Lightweight text-layer PDF capture via pymupdf4llm."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

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
    if os.name == "nt" and (
        re.match(r"^[A-Za-z]:[\\/]", source_uri) or source_uri.startswith("\\\\")
    ):
        return Path(source_uri).expanduser().resolve()
    parsed = urlparse(source_uri)
    if parsed.scheme == "file":
        raw = url2pathname(unquote(parsed.path))
        if os.name == "nt" and re.match(r"^[\\/][A-Za-z]:", raw):
            raw = raw[1:]
        return Path(raw).expanduser().resolve()
    if parsed.scheme:
        raise ValueError("pdf-lite accepts local PDF files only")
    return Path(source_uri).expanduser().resolve()


class PdfLiteAdapter:
    """Capture local text PDFs without MinerU or OCR model dependencies."""

    def __init__(
        self,
        *,
        to_markdown: Callable[..., list[dict[str, Any]]] | None = None,
        provider_version: str | None = None,
    ) -> None:
        self._to_markdown = to_markdown
        self._provider_version = provider_version

    def probe(self, request: CaptureRequest) -> CapabilityStatus:
        try:
            source = _local_path(request.source_uri)
        except ValueError as exc:
            return CapabilityStatus(False, str(exc))
        if not source.is_file() or source.suffix.lower() != ".pdf":
            return CapabilityStatus(False, "source must be an existing local PDF")
        available = self._to_markdown is not None or importlib.util.find_spec("pymupdf4llm") is not None
        return CapabilityStatus(available, None if available else "pymupdf4llm is not installed")

    def capture(self, request: CaptureRequest) -> CaptureResult:
        source = _local_path(request.source_uri)
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.lower() != ".pdf":
            raise ValueError("pdf-lite accepts .pdf files only")

        to_markdown = self._to_markdown
        if to_markdown is None:
            import pymupdf4llm

            to_markdown = pymupdf4llm.to_markdown
        version = self._provider_version
        if version is None:
            version = importlib.metadata.version("pymupdf4llm")

        started_at = _utc_now()
        started = time.monotonic()
        pages = to_markdown(str(source), page_chunks=True, show_progress=False)
        latency_ms = round((time.monotonic() - started) * 1000)
        finished_at = _utc_now()
        if not isinstance(pages, list):
            raise TypeError("pymupdf4llm page_chunks=True must return a list")

        sections: list[str] = []
        evidence: list[CaptureEvidence] = []
        title: str | None = None
        text_chars = 0
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                raise TypeError("pymupdf4llm page chunk must be an object")
            metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
            page_number = metadata.get("page") or index
            title = title or (metadata.get("title") or None)
            page_text = page.get("text") if isinstance(page.get("text"), str) else ""
            clean_text = page_text.strip()
            text_chars += len(clean_text)
            sections.append(f"<!-- Page {page_number} -->\n\n{clean_text}".rstrip())
            evidence.append(CaptureEvidence(
                kind="text",
                method="pdf_text_layer",
                locator={"kind": "page", "page": page_number, "total_pages": len(pages)},
                text=clean_text or None,
            ))

        has_text = text_chars > 0
        warning = (
            "PDF text layer is empty; use remote OCR fallback and keep this result partial."
        )
        return CaptureResult(
            status="complete" if has_text else "partial",
            provider="pymupdf4llm",
            provider_version=version,
            capability="pdf.text-layer",
            source_uri=str(source),
            snapshot_path=source,
            snapshot_media_type="application/pdf",
            content_markdown="\n\n".join(sections).rstrip(),
            title=title or source.stem,
            modalities={
                "text": ModalityResult(
                    "succeeded" if has_text else "partial",
                    evidence_count=len(evidence),
                )
            },
            evidence=tuple(evidence),
            latency_ms=latency_ms,
            warnings=() if has_text else (warning,),
            failure_disposition="none" if has_text else "needs_user_action",
            started_at=started_at,
            finished_at=finished_at,
        )
