from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_adapters.pdf_lite import PdfLiteAdapter
from capture_contract import CaptureContext, CaptureRequest
from raw_assembler import assemble_raw_bundle


def _page(page: int, text: str, *, title: str = "Light PDF") -> dict:
    return {
        "metadata": {"page": page, "page_count": 2, "title": title},
        "text": text,
        "tables": [],
        "images": [],
        "graphics": [],
        "words": [],
        "toc_items": [],
    }


def test_pdf_lite_adapter_generates_valid_raw_with_page_evidence(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture")
    adapter = PdfLiteAdapter(
        to_markdown=lambda *_args, **_kwargs: [
            _page(1, "# 第一页\n\n正文 😀"),
            _page(2, "# 第二页\n\nMore text"),
        ],
        provider_version="0.0.27",
    )

    result = adapter.capture(CaptureRequest(source.as_uri(), ("text",)))

    assert result.status == "complete"
    assert result.title == "Light PDF"
    assert result.modalities["text"].evidence_count == 2
    assert [item.locator["page"] for item in result.evidence] == [1, 2]

    output = tmp_path / "raw-bundle"
    report = assemble_raw_bundle(
        result,
        output,
        CaptureContext(capture_id="pdf-lite-capture", run_id="pdf-lite-run"),
    )
    assert report["valid"] is True
    assert "正文 😀" in (output / "content.md").read_text(encoding="utf-8")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "pymupdf4llm"


def test_pdf_lite_accepts_native_local_path(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture")
    adapter = PdfLiteAdapter(
        to_markdown=lambda *_args, **_kwargs: [_page(1, "native path")],
        provider_version="0.0.27",
    )

    result = adapter.capture(CaptureRequest(str(source), ("text",)))

    assert result.status == "complete"
    assert result.snapshot_path == source.resolve()


def test_pdf_lite_scan_without_text_is_partial(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4\nscan")
    adapter = PdfLiteAdapter(
        to_markdown=lambda *_args, **_kwargs: [_page(1, ""), _page(2, "")],
        provider_version="0.0.27",
    )

    result = adapter.capture(CaptureRequest(source.as_uri(), ("text",)))

    assert result.status == "partial"
    assert result.failure_disposition == "needs_user_action"
    assert result.modalities["text"].status == "partial"
    assert "OCR" in result.warnings[0]
