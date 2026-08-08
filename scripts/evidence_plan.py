"""Evidence acquisition plan — capability-aware fallback chain planning.

Replaces simple (suffix, platform) → extractor routing with a structured
plan that describes *what* evidence to acquire and *which providers* can
supply it, in fallback order.  The plan is a machine-readable decision;
it does NOT execute capture itself.

New providers register here once.  Legacy extractors that still call
``route_plan()`` directly are NOT routed through this module yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from route import SourceDescriptor

EVIDENCE_PLAN_VERSION = "oks-evidence-plan/v0.1"


@dataclass(frozen=True)
class CaptureCandidate:
    strategy: str
    provider: str
    capability: str
    expected_status: str = "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "provider": self.provider,
            "capability": self.capability,
            "expected_status": self.expected_status,
        }


@dataclass(frozen=True)
class FallbackCandidate:
    strategy: str
    provider: str
    capability: str
    condition: str  # e.g. "primary_returned_partial", "primary_returned_failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "provider": self.provider,
            "capability": self.capability,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class EvidencePlan:
    plan_id: str
    source_modality: str
    access_mode: str
    primary_capture: CaptureCandidate
    fallback_capture: tuple[FallbackCandidate, ...] = ()
    human_gate: str = "none"
    human_gate_reason: str | None = None
    agent_role: str = "distill"
    cost_estimate: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    schema_version: str = field(default=EVIDENCE_PLAN_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source_modality": self.source_modality,
            "access_mode": self.access_mode,
            "primary_capture": self.primary_capture.to_dict(),
            "fallback_capture": [item.to_dict() for item in self.fallback_capture],
            "human_gate": self.human_gate,
            "agent_role": self.agent_role,
            "warnings": list(self.warnings),
        }
        if self.human_gate_reason:
            value["human_gate_reason"] = self.human_gate_reason
        if self.cost_estimate:
            value["cost_estimate"] = self.cost_estimate
        return value


# ── Routing tables ──────────────────────────────────────────────────────────

# Format: (source_modality, access_mode) → (primary, fallbacks, agent_role, human_gate)
# Each entry is a pure data mapping — no branching, no side effects.
# Capability identifiers use reverse-DNS style: <modality>.<method>

_TEXT_LOCAL = (
    CaptureCandidate("direct", "oks-connector", "text.markdown", "complete"),
    (),
    "distill",
    "none",
)

_PDF_LOCAL_LITE = (
    CaptureCandidate("text_layer", "pymupdf4llm", "pdf.text-layer", "complete"),
    (
        FallbackCandidate("remote_ocr", "firecrawl", "ocr.document", "primary_returned_partial"),
        FallbackCandidate("remote_ocr", "agentkey", "ocr.document", "primary_returned_failed"),
        FallbackCandidate("manual", "human", "manual.snapshot", "primary_returned_failed"),
    ),
    "distill",
    "none",
)

_PDF_LOCAL_MINERU = (
    CaptureCandidate("text_layer", "mineru", "pdf.layout", "complete"),
    (
        FallbackCandidate("remote_ocr", "firecrawl", "ocr.document", "primary_returned_partial"),
    ),
    "distill",
    "none",
)

_OFFICE_LOCAL = (
    CaptureCandidate("file", "markitdown", "office.markitdown", "complete"),
    (
        FallbackCandidate("remote_api", "firecrawl", "office.parse", "primary_returned_failed"),
        FallbackCandidate("manual", "human", "manual.snapshot", "primary_returned_failed"),
    ),
    "distill",
    "none",
)

_IMAGE_LOCAL = (
    CaptureCandidate("screenshot", "rapidocr", "ocr.block", "complete"),
    (
        FallbackCandidate("remote_api", "agentkey", "ocr.block", "primary_returned_failed"),
    ),
    "observe",
    "none",
)

_VIDEO_BILIBILI = (
    CaptureCandidate("subtitle", "yt-dlp", "video.caption", "complete"),
    (
        FallbackCandidate("remote_api", "agentkey", "video.caption", "primary_returned_failed"),
        FallbackCandidate("manual", "human", "manual.snapshot", "primary_returned_failed"),
    ),
    "observe",
    "none",
)

_VIDEO_YOUTUBE = (
    CaptureCandidate("subtitle", "yt-dlp", "video.caption", "complete"),
    (
        FallbackCandidate("remote_api", "agentkey", "video.caption", "primary_returned_failed"),
        FallbackCandidate("manual", "human", "manual.snapshot", "primary_returned_failed"),
    ),
    "observe",
    "none",
)

_AUDIO_LOCAL = (
    CaptureCandidate("audio", "openai", "asr.whisper", "complete"),
    (
        FallbackCandidate("manual", "human", "manual.transcription", "primary_returned_failed"),
    ),
    "observe",
    "none",
)

_WEB_PUBLIC = (
    CaptureCandidate("dom", "trafilatura", "web.article", "complete"),
    (
        FallbackCandidate("remote_api", "agentkey", "web.scrape", "primary_returned_failed"),
        FallbackCandidate("manual", "human", "manual.snapshot", "primary_returned_failed"),
    ),
    "distill",
    "none",
)

_UNKNOWN = (
    CaptureCandidate("direct", "human", "manual.snapshot", "partial"),
    (),
    "not_needed",
    "none",
)

ROUTING_TABLE: dict[tuple[str, str], tuple[CaptureCandidate, tuple[FallbackCandidate, ...], str, str]] = {
    ("text", "local_file"): _TEXT_LOCAL,
    ("pdf", "local_file"): _PDF_LOCAL_LITE,
    ("office", "local_file"): _OFFICE_LOCAL,
    ("image", "local_file"): _IMAGE_LOCAL,
    ("video", "local_file"): _AUDIO_LOCAL,  # local video → ASR path
    ("audio", "local_file"): _AUDIO_LOCAL,
    ("video", "authenticated_remote"): _VIDEO_BILIBILI,
    ("video", "public_url"): _VIDEO_YOUTUBE,
    ("web", "public_url"): _WEB_PUBLIC,
    ("web", "local_file"): _TEXT_LOCAL,  # .html files → text extraction
    ("unknown", "local_file"): _UNKNOWN,
}

MINERU_OVERRIDE: dict[tuple[str, str], tuple[CaptureCandidate, tuple[FallbackCandidate, ...], str, str]] = {
    ("pdf", "local_file"): _PDF_LOCAL_MINERU,
}


def _plan_id(source: SourceDescriptor) -> str:
    payload = f"{source.source_modality}|{source.access_mode}|{source.platform or ''}"
    return sha256(payload.encode()).hexdigest()[:16]


def plan_evidence(
    source: SourceDescriptor,
    *,
    pdf_engine: str = "pdf-lite",
) -> EvidencePlan:
    """Generate an evidence acquisition plan from a pure source description.

    The plan is a data structure — it does NOT execute any capture.
    Agent code reads the plan, selects an available provider, and calls
    the matching ``CaptureAdapter.capture()``.

    *pdf_engine* selects the PDF strategy:
    - ``"pdf-lite"`` — pymupdf4llm text layer extraction (default, ~55MB)
    - ``"mineru"``    — MinerU full layout pipeline (legacy, heavy)
    """
    key = (source.source_modality, source.access_mode)
    table = MINERU_OVERRIDE if pdf_engine == "mineru" else ROUTING_TABLE
    primary, fallbacks, agent_role, human_gate = table.get(
        key,
        _UNKNOWN,
    )

    warnings: list[str] = []
    if source.source_modality == "unknown":
        warnings.append(
            f"unsupported source modality: extension={source.diagnostics.get('detected_extension')}"
        )
    if source.access_mode == "authenticated_remote":
        warnings.append("authenticated remote may require user login or cookie")

    return EvidencePlan(
        plan_id=_plan_id(source),
        source_modality=source.source_modality,
        access_mode=source.access_mode,
        primary_capture=primary,
        fallback_capture=fallbacks,
        human_gate=human_gate,
        human_gate_reason=None,
        agent_role=agent_role,
        cost_estimate=None,
        warnings=tuple(warnings),
    )
