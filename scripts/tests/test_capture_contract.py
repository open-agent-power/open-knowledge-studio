from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_contract import (  # noqa: E402
    CaptureArtifact,
    CapabilityStatus,
    CaptureAdapter,
    CaptureContext,
    CaptureEvidence,
    CaptureRequest,
    CaptureResult,
    ModalityResult,
)
from raw_assembler import assemble_raw_bundle  # noqa: E402
from validator import validate_bundle  # noqa: E402


class FakeAdapter:
    def __init__(self, snapshot: Path, raw_response: Path):
        self.snapshot = snapshot
        self.raw_response = raw_response

    def probe(self, request: CaptureRequest) -> CapabilityStatus:
        return CapabilityStatus(available=request.source_uri.startswith("file:"))

    def capture(self, request: CaptureRequest) -> CaptureResult:
        now = datetime.now(timezone.utc).isoformat()
        return CaptureResult(
            status="complete",
            provider="fake.local",
            provider_version="0.1",
            capability="document.text",
            source_uri=request.source_uri,
            snapshot_path=self.snapshot,
            snapshot_media_type="text/plain",
            title="中文 Fake Capture",
            content_markdown="# 原始正文\n\n这是 UTF-8 内容。",
            evidence=(CaptureEvidence(
                kind="text",
                method="fake_fixture",
                locator={"line_start": 1, "line_end": 1},
                text="这是 UTF-8 内容。",
            ),),
            modalities={"text": ModalityResult("succeeded", evidence_count=1)},
            latency_ms=3,
            raw_response_reference=self.raw_response,
            started_at=now,
            finished_at=now,
        )


def test_fake_adapter_assembles_valid_raw_v2(tmp_path):
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("这是源文件。", encoding="utf-8")
    response = tmp_path / "response.json"
    response.write_text('{"message":"中文 😀"}\n', encoding="utf-8")
    adapter: CaptureAdapter = FakeAdapter(snapshot, response)
    request = CaptureRequest(snapshot.as_uri(), expected_modalities=("text",))

    assert adapter.probe(request).available is True
    result = adapter.capture(request)
    output = tmp_path / "raw-bundle"
    report = assemble_raw_bundle(
        result,
        output,
        CaptureContext(capture_id="capture-fake-1", run_id="run-fake-1"),
    )

    assert report["valid"] is True
    assert validate_bundle(output)["valid"] is True
    manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    stored_result = json.loads(
        (output / "derived" / "capture-result.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "raw-multimodal/v0.2"
    assert manifest["recipe_version"] == "capture-adapter-v0.1"
    assert metadata["execution_protocol"] == "oks-capture-result/v0.1"
    assert stored_result["provider"] == "fake.local"
    assert "中文 😀" in (
        output / metadata["raw_response_reference"]
    ).read_text(encoding="utf-8")
    capture = json.loads(
        (output / "derived" / "capture-envelope.json").read_text(encoding="utf-8")
    )
    assert capture["content_hash"] != manifest["sources"][0]["sha256"]
    assert len(capture["content_hash"]) == 64


def test_failed_result_is_preserved_but_not_assembled(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "reference.json"
    snapshot.write_text("{}", encoding="utf-8")
    result = CaptureResult(
        status="failed",
        provider="fake.remote",
        provider_version="0.1",
        capability="web.article",
        source_uri="https://example.invalid/article",
        snapshot_path=snapshot,
        snapshot_kind="reference",
        content_hash_status="unavailable",
        content_markdown="",
        modalities={"text": ModalityResult("failed", error_code="CHALLENGE")},
        failure_disposition="needs_user_auth",
        started_at=now,
        finished_at=now,
    )

    assert result.to_dict()["failure_disposition"] == "needs_user_auth"
    assert result.to_dict()["source_snapshot"]["content_hash_status"] == "unavailable"
    try:
        assemble_raw_bundle(
            result,
            tmp_path / "failed-bundle",
            CaptureContext(capture_id="capture-failed", run_id="run-failed"),
        )
    except ValueError as exc:
        assert "failed CaptureResult" in str(exc)
    else:
        raise AssertionError("failed CaptureResult must not become promotable Raw")


def test_capture_result_schema_declares_required_statuses():
    schema_path = SCRIPTS.parent / "schemas" / "capture-result-v0.1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["status"]["enum"] == ["complete", "partial", "failed"]
    assert "needs_user_auth" in schema["properties"]["failure_disposition"]["enum"]
    assert "provider_version" in schema["required"]
    assert "capability" in schema["properties"]["modalities"]["additionalProperties"]["properties"]
    assert len(schema["allOf"]) == 3

    envelope = json.loads(
        (SCRIPTS.parent / "schemas" / "capture-envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert "remote_api" in envelope["properties"]["source_type"]["enum"]


def test_capture_result_rejects_status_that_hides_partial_modality(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("source", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot contain partial/failed"):
        CaptureResult(
            status="complete",
            provider="fake.local",
            provider_version="0.1",
            capability="document.text",
            source_uri=snapshot.as_uri(),
            snapshot_path=snapshot,
            content_markdown="partial content",
            modalities={"text": ModalityResult("partial")},
            started_at=now,
            finished_at=now,
        )


def test_partial_capture_result_requires_warning(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("source", encoding="utf-8")

    with pytest.raises(ValueError, match="must explain its limitation"):
        CaptureResult(
            status="partial",
            provider="fake.local",
            provider_version="0.1",
            capability="document.text",
            source_uri=snapshot.as_uri(),
            snapshot_path=snapshot,
            content_markdown="partial content",
            modalities={"text": ModalityResult("partial")},
            started_at=now,
            finished_at=now,
        )


def test_artifact_is_traced_in_run_and_manifest(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("source", encoding="utf-8")
    artifact = tmp_path / "page.png"
    artifact.write_bytes(b"not-a-real-png")
    result = CaptureResult(
        status="complete",
        provider="fake.local",
        provider_version="0.1",
        capability="document.text",
        source_uri=snapshot.as_uri(),
        snapshot_path=snapshot,
        content_markdown="content",
        artifacts=(CaptureArtifact("page-1", "visual_observation", artifact, "image/png"),),
        evidence=(CaptureEvidence(
            kind="visual",
            method="fake_fixture",
            locator={"artifact_id": "page-1"},
        ),),
        modalities={"visual": ModalityResult("succeeded", evidence_count=1)},
        started_at=now,
        finished_at=now,
    )
    output = tmp_path / "bundle"

    assert assemble_raw_bundle(
        result,
        output,
        CaptureContext(capture_id="capture-artifact", run_id="run-artifact"),
    )["valid"] is True
    run = json.loads((output / "processing-runs.jsonl").read_text(encoding="utf-8"))
    manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    evidence = json.loads((output / "evidence.jsonl").read_text(encoding="utf-8"))
    assert run["outputs"][0]["dataset_id"] == "artifact:page-1"
    assert manifest["derived"][0]["path"] == evidence["locator"]["asset"]
    assert any(
        relation["subject"] == manifest["derived"][0]["entity_id"]
        and relation["type"] == "wasGeneratedBy"
        for relation in manifest["provenance"]["relations"]
    )


def test_duplicate_artifact_ids_are_rejected(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("source", encoding="utf-8")
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"artifact")
    duplicate = CaptureArtifact("duplicate", "other", artifact)
    result = CaptureResult(
        status="complete",
        provider="fake.local",
        provider_version="0.1",
        capability="document.text",
        source_uri=snapshot.as_uri(),
        snapshot_path=snapshot,
        content_markdown="content",
        artifacts=(duplicate, duplicate),
        modalities={},
        started_at=now,
        finished_at=now,
    )

    with pytest.raises(ValueError, match="duplicate artifact_id"):
        assemble_raw_bundle(
            result,
            tmp_path / "bundle",
            CaptureContext(capture_id="capture-duplicate", run_id="run-duplicate"),
        )


def test_declared_evidence_count_must_match_records(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = tmp_path / "source.txt"
    snapshot.write_text("source", encoding="utf-8")
    result = CaptureResult(
        status="complete",
        provider="fake.local",
        provider_version="0.1",
        capability="document.text",
        source_uri=snapshot.as_uri(),
        snapshot_path=snapshot,
        content_markdown="content",
        evidence=(CaptureEvidence("text", "fake", {"line": 1}),),
        modalities={"text": ModalityResult("succeeded", evidence_count=0)},
        started_at=now,
        finished_at=now,
    )

    with pytest.raises(ValueError, match="evidence_count total"):
        assemble_raw_bundle(
            result,
            tmp_path / "bundle",
            CaptureContext(capture_id="capture-count", run_id="run-count"),
        )


def test_reference_snapshot_does_not_claim_remote_content_hash(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    reference = tmp_path / "reference.json"
    reference.write_text('{"url":"https://example.invalid/article"}', encoding="utf-8")
    result = CaptureResult(
        status="partial",
        provider="fake.remote",
        provider_version="0.1",
        capability="web.article",
        source_uri="https://example.invalid/article",
        snapshot_path=reference,
        snapshot_kind="reference",
        content_hash_status="unavailable",
        content_markdown="metadata only",
        modalities={"text": ModalityResult("partial")},
        warnings=("remote body was unavailable",),
        failure_disposition="needs_user_auth",
        started_at=now,
        finished_at=now,
    )
    output = tmp_path / "bundle"

    assert assemble_raw_bundle(
        result,
        output,
        CaptureContext(
            capture_id="capture-reference",
            run_id="run-reference",
            source_type="remote_api",
        ),
    )["valid"] is True
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    assert metadata["source"]["content_hash_status"] == "unavailable"
    assert metadata["source"]["content_sha256"] is None
    assert len(metadata["source"]["reference_sha256"]) == 64
    assert manifest["sources"][0]["content_hash_status"] == "unavailable"
