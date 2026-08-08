"""Provider-neutral capture contract for new OKS connectors.

Legacy extractors continue to emit Raw Bundles directly.  New providers return
``CaptureResult`` and leave Raw layout/provenance assembly to ``raw_assembler``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


CAPTURE_RESULT_VERSION = "oks-capture-result/v0.1"
CAPTURE_STATUSES = {"complete", "partial", "failed"}
MODALITY_STATUSES = {"succeeded", "partial", "failed", "skipped"}
FAILURE_DISPOSITIONS = {
    "none", "needs_user_auth", "needs_user_action", "retryable", "final",
}


@dataclass(frozen=True)
class CaptureRequest:
    source_uri: str
    expected_modalities: tuple[str, ...] = ()
    network_policy: str | None = None

    def __post_init__(self) -> None:
        if not self.source_uri.strip():
            raise ValueError("source_uri must not be empty")


@dataclass(frozen=True)
class CapabilityStatus:
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class CaptureArtifact:
    artifact_id: str
    kind: str
    path: Path
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.kind:
            raise ValueError("artifact_id and kind must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": str(self.path),
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class CaptureEvidence:
    kind: str
    method: str
    locator: Mapping[str, Any]
    text: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.method:
            raise ValueError("evidence kind and method must not be empty")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("evidence confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": self.kind,
            "method": self.method,
            "locator": dict(self.locator),
        }
        if self.text is not None:
            value["text"] = self.text
        if self.confidence is not None:
            value["confidence"] = self.confidence
        return value


@dataclass(frozen=True)
class CaptureCost:
    amount: float
    unit: str
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.amount < 0 or not self.unit:
            raise ValueError("cost must be non-negative and include a unit")

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "unit": self.unit, "currency": self.currency}


@dataclass(frozen=True)
class ModalityResult:
    status: str
    evidence_count: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in MODALITY_STATUSES:
            raise ValueError(f"invalid modality status: {self.status}")
        if self.evidence_count < 0:
            raise ValueError("evidence_count must be non-negative")

    def to_dict(self, capability: str | None = None) -> dict[str, Any]:
        return {
            "status": self.status,
            "capability": capability,
            "error_code": self.error_code,
            "evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class CaptureError:
    code: str
    message: str
    modality: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "modality": self.modality}


@dataclass(frozen=True)
class CaptureResult:
    status: str
    provider: str
    provider_version: str
    capability: str
    source_uri: str
    snapshot_path: Path
    content_markdown: str
    started_at: str
    finished_at: str
    modalities: Mapping[str, ModalityResult]
    title: str | None = None
    snapshot_kind: str = "content"
    content_hash_status: str = "verified"
    snapshot_media_type: str | None = None
    artifacts: tuple[CaptureArtifact, ...] = ()
    evidence: tuple[CaptureEvidence, ...] = ()
    latency_ms: int | None = None
    cost: CaptureCost | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[CaptureError, ...] = ()
    failure_disposition: str = "none"
    raw_response_reference: Path | None = None
    schema_version: str = field(default=CAPTURE_RESULT_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.status not in CAPTURE_STATUSES:
            raise ValueError(f"invalid capture status: {self.status}")
        if self.failure_disposition not in FAILURE_DISPOSITIONS:
            raise ValueError(f"invalid failure disposition: {self.failure_disposition}")
        if self.snapshot_kind not in {"content", "reference"}:
            raise ValueError(f"invalid snapshot kind: {self.snapshot_kind}")
        if self.content_hash_status not in {"verified", "unavailable"}:
            raise ValueError(f"invalid content hash status: {self.content_hash_status}")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if not self.provider or not self.provider_version or not self.capability:
            raise ValueError("provider, provider_version and capability are required")
        if not self.source_uri:
            raise ValueError("source_uri is required")
        modality_statuses = {item.status for item in self.modalities.values()}
        if self.status == "complete" and modality_statuses.intersection({"partial", "failed"}):
            raise ValueError("complete CaptureResult cannot contain partial/failed modalities")
        if self.status == "partial" and not self.warnings:
            raise ValueError("partial CaptureResult must explain its limitation in warnings")
        if self.status == "failed" and self.failure_disposition == "none":
            raise ValueError("failed CaptureResult must declare a failure disposition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "capability": self.capability,
            "source_uri": self.source_uri,
            "title": self.title,
            "source_snapshot": {
                "path": str(self.snapshot_path),
                "kind": self.snapshot_kind,
                "content_hash_status": self.content_hash_status,
                "media_type": self.snapshot_media_type,
            },
            "content_markdown": self.content_markdown,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "evidence": [item.to_dict() for item in self.evidence],
            "modalities": {key: value.to_dict() for key, value in self.modalities.items()},
            "latency_ms": self.latency_ms,
            "cost": self.cost.to_dict() if self.cost else None,
            "warnings": list(self.warnings),
            "errors": [item.to_dict() for item in self.errors],
            "failure_disposition": self.failure_disposition,
            "raw_response_reference": (
                str(self.raw_response_reference) if self.raw_response_reference else None
            ),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class CaptureContext:
    capture_id: str
    run_id: str
    recipe_version: str = "capture-adapter-v0.1"
    source_type: str = "local"

    def __post_init__(self) -> None:
        if self.source_type not in {"feishu_base", "browser", "obsidian", "local", "remote_api"}:
            raise ValueError(f"invalid capture source type: {self.source_type}")


class CaptureAdapter(Protocol):
    def probe(self, request: CaptureRequest) -> CapabilityStatus: ...

    def capture(self, request: CaptureRequest) -> CaptureResult: ...


# ── Unified failure state mapping ──────────────────────────────────────────

UNIFIED_STATES = (
    "passed",
    "partial",
    "failed",
    "skipped",
    "awaiting_human",
    "environment_limited",
)


def map_to_unified(result: CaptureResult) -> str:
    """Map CaptureResult.status + failure_disposition to a 6-state unified code.

    ===================== ====================================================
    Unified state         Meaning
    ===================== ====================================================
    ``passed``            All required modalities succeeded; ready for Candidate.
    ``partial``           Some modalities partial; warnings may apply.
    ``failed``            Core modality failed; disposition is ``final``.
    ``skipped``           Capture was not attempted (capability missing, quota
                          exhausted, or Agent chose not to execute).
    ``awaiting_human``    Failure disposition is ``needs_user_auth`` or
                          ``needs_user_action`` — human must intervene.
    ``environment_limited`` Failure disposition is ``retryable`` — network,
                            proxy, or quota issue; may succeed later.
    ===================== ====================================================
    """
    if result.status == "complete":
        return "passed"
    if result.status == "partial":
        return "partial"
    # status == "failed"
    disposition = result.failure_disposition
    if disposition in ("needs_user_auth", "needs_user_action"):
        return "awaiting_human"
    if disposition == "retryable":
        return "environment_limited"
    return "failed"
