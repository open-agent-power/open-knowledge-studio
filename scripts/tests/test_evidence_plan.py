from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from route import describe_source, SourceDescriptor  # noqa: E402
from evidence_plan import (  # noqa: E402
    CaptureCandidate,
    EvidencePlan,
    FallbackCandidate,
    plan_evidence,
)


# ── SourceDescriptor → EvidencePlan integration ────────────────────

def test_describe_then_plan_text():
    src = describe_source("README.md")
    assert src.source_modality == "text"
    assert src.access_mode == "local_file"

    plan = plan_evidence(src)
    assert plan.source_modality == "text"
    assert plan.primary_capture.strategy == "direct"
    assert plan.primary_capture.provider == "oks-connector"
    assert plan.agent_role == "distill"


def test_describe_then_plan_pdf():
    src = describe_source("doc.pdf")
    assert src.source_modality == "pdf"
    plan = plan_evidence(src)
    assert plan.primary_capture.strategy == "text_layer"
    assert plan.primary_capture.provider == "pymupdf4llm"
    assert len(plan.fallback_capture) >= 2


def test_describe_then_plan_pdf_mineru():
    src = describe_source("doc.pdf")
    plan = plan_evidence(src, pdf_engine="mineru")
    assert plan.primary_capture.provider == "mineru"
    assert plan.primary_capture.capability == "pdf.layout"


def test_describe_then_plan_office():
    src = describe_source("slides.pptx")
    assert src.source_modality == "office"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "markitdown"


def test_describe_then_plan_image():
    src = describe_source("photo.png")
    assert src.source_modality == "image"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "rapidocr"


def test_describe_then_plan_video_url():
    src = describe_source("https://www.bilibili.com/video/BV123")
    assert src.source_modality == "video"
    assert src.access_mode == "authenticated_remote"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "yt-dlp"


def test_describe_then_plan_youtube():
    src = describe_source("https://youtube.com/watch?v=abc")
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "yt-dlp"


def test_describe_then_plan_web():
    src = describe_source("https://example.com/page.html")
    assert src.source_modality == "web"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "trafilatura"


def test_describe_then_plan_web_no_extension():
    """URL without file extension is classified as unknown, routed to human."""
    src = describe_source("https://example.com/article")
    assert src.source_modality == "unknown"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "human"


def test_describe_then_plan_unknown():
    src = describe_source("file.xyz")
    assert src.source_modality == "unknown"
    plan = plan_evidence(src)
    assert plan.primary_capture.provider == "human"


# ── EvidencePlan dataclass properties ──────────────────────────────

def test_plan_minimal():
    plan = EvidencePlan(
        plan_id="test-1",
        source_modality="text",
        access_mode="local_file",
        primary_capture=CaptureCandidate(
            strategy="direct",
            provider="oks-connector",
            capability="text.markdown",
        ),
    )
    assert plan.plan_id == "test-1"
    assert plan.human_gate == "none"
    assert plan.agent_role == "distill"
    assert plan.fallback_capture == ()


def test_plan_with_fallbacks():
    plan = EvidencePlan(
        plan_id="test-2",
        source_modality="pdf",
        access_mode="local_file",
        primary_capture=CaptureCandidate(
            strategy="text_layer",
            provider="pymupdf4llm",
            capability="pdf.text-layer",
        ),
        fallback_capture=(
            FallbackCandidate(
                strategy="remote_ocr",
                provider="firecrawl",
                capability="ocr.document",
                condition="primary_returned_partial",
            ),
        ),
    )
    assert len(plan.fallback_capture) == 1
    assert plan.fallback_capture[0].provider == "firecrawl"
    assert plan.fallback_capture[0].condition == "primary_returned_partial"


def test_plan_human_gate():
    plan = EvidencePlan(
        plan_id="gated",
        source_modality="web",
        access_mode="authenticated_remote",
        primary_capture=CaptureCandidate(
            strategy="remote_api",
            provider="agentkey",
            capability="social.article",
        ),
        human_gate="required",
        human_gate_reason="login required",
    )
    assert plan.human_gate == "required"


def test_plan_to_dict():
    plan = EvidencePlan(
        plan_id="dict-test",
        source_modality="web",
        access_mode="public_url",
        primary_capture=CaptureCandidate(
            strategy="remote_api",
            provider="firecrawl",
            capability="web.scrape",
        ),
        warnings=("test warning",),
    )
    d = plan.to_dict()
    assert d["schema_version"] == "oks-evidence-plan/v0.1"
    assert d["plan_id"] == "dict-test"
    assert d["primary_capture"]["provider"] == "firecrawl"
    assert d["warnings"] == ["test warning"]


# ── CaptureCandidate ──────────────────────────────────────────────

def test_candidate_to_dict():
    c = CaptureCandidate("text_layer", "pymupdf4llm", "pdf.text-layer")
    d = c.to_dict()
    assert d["strategy"] == "text_layer"
    assert d["expected_status"] == "complete"


def test_candidate_partial():
    c = CaptureCandidate("remote_api", "agentkey", "social.article", "partial")
    d = c.to_dict()
    assert d["expected_status"] == "partial"


# ── FallbackCandidate ─────────────────────────────────────────────

def test_fallback_to_dict():
    f = FallbackCandidate("remote_ocr", "firecrawl", "ocr.document", "primary_returned_partial")
    d = f.to_dict()
    assert d["strategy"] == "remote_ocr"
    assert d["condition"] == "primary_returned_partial"
