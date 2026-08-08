"""OKS evidence submission protocols — frozen dataclass equivalents.

Three protocols (schemas/*.json):

1. ``SourceEnvelope`` — Agent declares "I have captured a source".
   Identity, modality, access mode, content hash.  No content body.

2. ``EvidenceFragment`` — A single tool's contribution.
   Each external capability (pdf-lite, Firecrawl, AgentKey, Agent vision)
   produces one fragment.  The Agent collects and merges them.

3. ``EvidenceManifest`` — Agent's final merged evidence declaration.
   Submitted to ``oks raw commit`` alongside artifacts.  OKS validates
   structural integrity, cross-references, hash matching, and assembles
   a Raw Bundle v0.2.

These dataclasses are the canonical in-memory representation.
The JSON schemas in ``schemas/`` are the human-readable contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Constants ─────────────────────────────────────────────────────

SOURCE_ENVELOPE_VERSION = "oks-source-envelope/v0.1"
EVIDENCE_FRAGMENT_VERSION = "oks-evidence-fragment/v0.1"
EVIDENCE_MANIFEST_VERSION = "oks-evidence-manifest/v0.1"

SOURCE_MODALITIES = frozenset({
    "pdf", "office", "image", "video", "audio", "web", "text",
})
ACCESS_MODES = frozenset({
    "local_file", "public_url", "authenticated_remote", "user_browser", "manual",
})
PRODUCERS = frozenset({
    "firecrawl", "agentkey", "pdf-lite", "mineru",
    "rapidocr", "remote-asr", "browser",
    "agent.vision", "agent.direct_read", "human",
})
ARTIFACT_KINDS = frozenset({
    "primary_text", "page_image", "ocr_result", "subtitle",
    "screenshot", "dom_snapshot", "api_response",
    "rendered_page", "other",
})
LOCATOR_KINDS = frozenset({
    "page", "bbox", "timestamp", "dom", "document", "custom",
})
AGENT_JUDGMENTS = frozenset({
    "mechanical", "agent_observed", "human_supplied",
})
FRAGMENT_STATUSES = frozenset({"succeeded", "partial", "failed"})
MANIFEST_STATUSES = frozenset({"complete", "partial"})
MODALITY_STATUSES = frozenset({"succeeded", "partial", "failed", "skipped"})
MODALITY_NAMES = frozenset({"text", "image", "layout", "speech", "video"})
DISPOSITIONS = frozenset({
    "none", "needs_user_auth", "needs_user_action", "retryable", "final",
})

VALID_LOCATOR_KINDS_BY_REQUIRED: dict[str, tuple[str, ...]] = {
    "page": ("page",),
    "bbox": ("bbox",),
    "timestamp": ("start_ms", "end_ms"),
    "dom": ("xpath_fragment",),
    "document": (),
    "custom": ("custom_label",),
}


# ── ArtifactRef ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ArtifactRef:
    """Pointer to a single evidence file inside the submission."""

    artifact_id: str
    kind: str
    path: str
    sha256: str
    media_type: str | None = None
    locator_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be empty")
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError(f"artifact kind {self.kind!r} not in {sorted(ARTIFACT_KINDS)}")
        if not self.path.strip():
            raise ValueError("path must not be empty")
        if not _looks_like_sha256(self.sha256):
            raise ValueError(f"sha256 must be 64 hex chars, got {self.sha256!r}")
        if self.locator_kind is not None and self.locator_kind not in LOCATOR_KINDS:
            raise ValueError(f"locator_kind {self.locator_kind!r} not in {sorted(LOCATOR_KINDS)}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
        }
        if self.media_type is not None:
            d["media_type"] = self.media_type
        if self.locator_kind is not None:
            d["locator_kind"] = self.locator_kind
        return d


# ── EvidenceRecord ────────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceRecordDC:
    """One atomic piece of evidence anchored to an artifact."""

    evidence_id: str
    artifact_id: str
    kind: str
    method: str
    locator: dict[str, Any]
    text: str | None = None
    confidence: float | None = None
    agent_judgment: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be empty")
        if not self.kind.strip():
            raise ValueError("evidence kind must not be empty")
        if not self.method.strip():
            raise ValueError("evidence method must not be empty")
        if not isinstance(self.locator, dict) or not self.locator:
            raise ValueError("locator must be a non-empty dict")
        if self.confidence is not None and not (0 <= self.confidence <= 1):
            raise ValueError("confidence must be between 0 and 1")
        if self.agent_judgment is not None and self.agent_judgment not in AGENT_JUDGMENTS:
            raise ValueError(f"agent_judgment {self.agent_judgment!r} not in {sorted(AGENT_JUDGMENTS)}")

        # Validate locator kind
        lk = self.locator.get("kind")
        if lk is None:
            # Legacy locator — accept with implied warning
            pass
        elif lk not in VALID_LOCATOR_KINDS_BY_REQUIRED:
            raise ValueError(f"locator kind {lk!r} not in {sorted(VALID_LOCATOR_KINDS_BY_REQUIRED)}")
        else:
            for req in VALID_LOCATOR_KINDS_BY_REQUIRED[lk]:
                if req not in self.locator:
                    raise ValueError(
                        f"locator kind {lk!r} requires field {req!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "method": self.method,
            "locator": dict(self.locator),
        }
        if self.text is not None:
            d["text"] = self.text
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.agent_judgment is not None:
            d["agent_judgment"] = self.agent_judgment
        return d


# ── ModalityEntry ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ModalityEntry:
    modality: str
    status: str
    evidence_count: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.modality not in MODALITY_NAMES:
            raise ValueError(f"modality {self.modality!r} not in {sorted(MODALITY_NAMES)}")
        if self.status not in MODALITY_STATUSES:
            raise ValueError(f"modality status {self.status!r} not in {sorted(MODALITY_STATUSES)}")
        if self.evidence_count < 0:
            raise ValueError("evidence_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "modality": self.modality,
            "status": self.status,
            "evidence_count": self.evidence_count,
        }
        if self.error_code is not None:
            d["error_code"] = self.error_code
        return d


# ── SourceEnvelope ────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceEnvelope:
    """Agent declares ownership of a captured source."""

    source_id: str
    source_uri: str
    source_modality: str
    access_mode: str
    captured_at: str
    captured_by: dict[str, Any]
    content_hash: str
    evidence_manifest_ref: str
    title: str | None = None
    user_note: str | None = None
    schema_version: str = field(default=SOURCE_ENVELOPE_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.source_uri.strip():
            raise ValueError("source_uri must not be empty")
        if self.source_modality not in SOURCE_MODALITIES:
            raise ValueError(f"source_modality {self.source_modality!r} not in {sorted(SOURCE_MODALITIES)}")
        if self.access_mode not in ACCESS_MODES:
            raise ValueError(f"access_mode {self.access_mode!r} not in {sorted(ACCESS_MODES)}")
        if not _looks_like_sha256(self.content_hash):
            raise ValueError(f"content_hash must be 64 hex chars")
        if not self.evidence_manifest_ref.strip():
            raise ValueError("evidence_manifest_ref must not be empty")
        cb = self.captured_by
        if not isinstance(cb, dict) or not cb.get("runtime"):
            raise ValueError("captured_by must have a non-empty 'runtime' key")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_uri": self.source_uri,
            "source_modality": self.source_modality,
            "access_mode": self.access_mode,
            "captured_at": self.captured_at,
            "captured_by": dict(self.captured_by),
            "content_hash": self.content_hash,
            "evidence_manifest_ref": self.evidence_manifest_ref,
        }
        if self.title is not None:
            d["title"] = self.title
        if self.user_note is not None:
            d["user_note"] = self.user_note
        return d


# ── EvidenceFragment ──────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceFragment:
    """A single tool's contribution to evidence acquisition."""

    fragment_id: str
    source_id: str
    producer: str
    status: str
    artifacts: tuple[ArtifactRef, ...]
    evidence: tuple[EvidenceRecordDC, ...]
    modalities: tuple[ModalityEntry, ...]
    producer_version: str | None = None
    warnings: tuple[str, ...] = ()
    cost: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    schema_version: str = field(default=EVIDENCE_FRAGMENT_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.fragment_id.strip():
            raise ValueError("fragment_id must not be empty")
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if self.producer not in PRODUCERS:
            raise ValueError(f"producer {self.producer!r} not in {sorted(PRODUCERS)}")
        if self.status not in FRAGMENT_STATUSES:
            raise ValueError(f"fragment status {self.status!r} not in {sorted(FRAGMENT_STATUSES)}")
        if not self.artifacts:
            raise ValueError("at least one artifact is required")
        if self.status == "failed" and self.evidence:
            raise ValueError("failed fragment must have zero evidence records")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "fragment_id": self.fragment_id,
            "source_id": self.source_id,
            "producer": self.producer,
            "status": self.status,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "evidence": [e.to_dict() for e in self.evidence],
            "modalities": {m.modality: m.to_dict() for m in self.modalities},
            "warnings": list(self.warnings),
        }
        if self.producer_version is not None:
            d["producer_version"] = self.producer_version
        if self.cost is not None:
            d["cost"] = self.cost
        if self.provenance is not None:
            d["provenance"] = self.provenance
        return d


# ── EvidenceManifest ──────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceManifest:
    """Agent's final merged evidence declaration for ``oks raw commit``."""

    manifest_id: str
    source_id: str
    status: str
    fragment_refs: tuple[str, ...]
    primary_artifact: ArtifactRef
    evidence_records: tuple[EvidenceRecordDC, ...]
    modalities: tuple[ModalityEntry, ...]
    provenance: dict[str, Any]
    supplementary_artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()
    failure_disposition: str = "none"
    agent_observation_ref: str | None = None
    schema_version: str = field(default=EVIDENCE_MANIFEST_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must not be empty")
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if self.status not in MANIFEST_STATUSES:
            raise ValueError(f"manifest status {self.status!r} not in {sorted(MANIFEST_STATUSES)}")
        if not self.fragment_refs:
            raise ValueError("at least one fragment_ref is required")
        if not self.evidence_records:
            raise ValueError("at least one evidence record is required")
        if self.failure_disposition not in DISPOSITIONS:
            raise ValueError(f"failure_disposition {self.failure_disposition!r} not in {sorted(DISPOSITIONS)}")
        if self.status == "partial":
            if self.failure_disposition == "none":
                raise ValueError("partial manifest must declare a failure_disposition")
            if not self.warnings:
                raise ValueError("partial manifest must have warnings")
        if self.status == "complete" and self.failure_disposition != "none":
            raise ValueError("complete manifest must have failure_disposition='none'")
        prov = self.provenance
        if not isinstance(prov, dict) or not isinstance(prov.get("agent"), dict):
            raise ValueError("provenance.agent is required")
        if not prov["agent"].get("runtime"):
            raise ValueError("provenance.agent.runtime must not be empty")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_id": self.source_id,
            "status": self.status,
            "fragment_refs": list(self.fragment_refs),
            "primary_artifact": self.primary_artifact.to_dict(),
            "supplementary_artifacts": [a.to_dict() for a in self.supplementary_artifacts],
            "evidence_records": [e.to_dict() for e in self.evidence_records],
            "modalities": {m.modality: m.to_dict() for m in self.modalities},
            "warnings": list(self.warnings),
            "failure_disposition": self.failure_disposition,
            "provenance": dict(self.provenance),
        }
        if self.agent_observation_ref is not None:
            d["agent_observation_ref"] = self.agent_observation_ref
        return d

    def all_artifacts(self) -> tuple[ArtifactRef, ...]:
        return (self.primary_artifact,) + self.supplementary_artifacts

    def artifact_by_id(self, aid: str) -> ArtifactRef | None:
        for a in self.all_artifacts():
            if a.artifact_id == aid:
                return a
        return None


# ── Helpers ───────────────────────────────────────────────────────

def _looks_like_sha256(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[a-f0-9]{64}", value))


# ── Structural validation (used by oks raw commit) ───────────────

def validate_manifest_structural(
    envelope: SourceEnvelope,
    manifest: EvidenceManifest,
    *,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    """Run all structural checks without assembling a Raw Bundle.

    Returns ``{valid, errors, warnings}``.  Does NOT write files.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Cross-reference check
    if envelope.source_id != manifest.source_id:
        errors.append(
            f"SourceEnvelope.source_id ({envelope.source_id!r}) != "
            f"EvidenceManifest.source_id ({manifest.source_id!r})"
        )

    # Fragment refs exist
    for fid in manifest.fragment_refs:
        if not fid.strip():
            errors.append(f"empty fragment_ref in manifest.fragment_refs")
            break

    # Evidence → artifact cross-reference
    for rec in manifest.evidence_records:
        if manifest.artifact_by_id(rec.artifact_id) is None:
            errors.append(
                f"evidence record {rec.evidence_id!r} references "
                f"unknown artifact_id {rec.artifact_id!r}"
            )

    # Modality evidence_count consistency
    declared_total = sum(m.evidence_count for m in manifest.modalities)
    actual_total = len(manifest.evidence_records)
    if declared_total != actual_total:
        errors.append(
            f"modality evidence_count total ({declared_total}) != "
            f"actual evidence records ({actual_total})"
        )

    # If artifact_dir is provided, verify file existence + hash
    if artifact_dir is not None:
        import os
        from hashlib import sha256 as _sha256

        art_dir = __import__("pathlib").Path(artifact_dir).expanduser().resolve()
        if not art_dir.is_dir():
            errors.append(f"artifact directory does not exist: {art_dir}")
        else:
            for a in manifest.all_artifacts():
                fp = art_dir / a.path
                if not fp.is_file():
                    errors.append(f"artifact file not found: {a.path} (artifact_id={a.artifact_id})")
                    continue
                actual_hash = _sha256(fp.read_bytes()).hexdigest()
                if actual_hash != a.sha256:
                    errors.append(
                        f"artifact hash mismatch for {a.artifact_id!r}: "
                        f"declared={a.sha256[:16]}... actual={actual_hash[:16]}..."
                    )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
