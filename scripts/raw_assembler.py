"""Assemble provider-neutral CaptureResult values into Raw Bundle v0.2."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any

from _shared import (
    common_metadata,
    coverage_report,
    prepare_output,
    sha256_file,
    source_identity,
    write_json,
    write_jsonl,
)
from capture_contract import CaptureContext, CaptureResult
from constants import SCHEMA_VERSION
from validator import finalize_bundle_v2, validate_bundle


def _copy_artifacts(result: CaptureResult, output: Path) -> dict[str, str]:
    references: dict[str, str] = {}
    for index, artifact in enumerate(result.artifacts, start=1):
        if artifact.artifact_id in references:
            raise ValueError(f"duplicate artifact_id: {artifact.artifact_id}")
        source = artifact.path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output / "derived" / f"{index:03d}-{source.name}"
        shutil.copy2(source, destination)
        references[artifact.artifact_id] = destination.relative_to(output).as_posix()
    return references


def _evidence_records(result: CaptureResult, artifacts: dict[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in result.evidence:
        value = item.to_dict()
        locator = value["locator"]
        artifact_id = locator.pop("artifact_id", None)
        if artifact_id is not None:
            if artifact_id not in artifacts:
                raise ValueError(f"evidence references unknown artifact_id: {artifact_id}")
            locator["asset"] = artifacts[artifact_id]
        records.append(value)
    return records


def _canonical_envelope_hash(capture: dict[str, Any]) -> str:
    canonical = {
        "source_type": capture["source_type"],
        "source_uri": capture["source_uri"],
        "content": capture.get("content"),
        "user_note": capture.get("user_note"),
        "attachments": capture.get("attachments", []),
        "source_snapshot": capture.get("source_snapshot"),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _add_artifact_provenance(
    output: Path,
    manifest: dict[str, Any],
    result: CaptureResult,
    artifact_references: dict[str, str],
) -> None:
    if not artifact_references:
        return
    source_entity = manifest["sources"][0]["entity_id"]
    activity = manifest["provenance"]["activities"][0]["id"]
    allowed_kinds = {"ocr", "asr", "visual_observation", "layout", "other"}
    by_id = {item.artifact_id: item for item in result.artifacts}
    for artifact_id, relative in artifact_references.items():
        artifact = by_id[artifact_id]
        digest = sha256_file(output / relative)
        entity = f"entity:artifact:{digest[:16]}"
        kind = artifact.kind if artifact.kind in allowed_kinds else "other"
        manifest["derived"].append({
            "entity_id": entity,
            "kind": kind,
            "path": relative,
            "generated_by": result.provider,
            "derived_from": [source_entity],
            "review_status": "unreviewed",
            "model": None,
            "cost": result.cost.amount if result.cost else None,
        })
        manifest["provenance"]["entities"].append({
            "id": entity,
            "path": relative,
            "sha256": digest,
            "artifact_id": artifact_id,
        })
        manifest["provenance"]["relations"].extend([
            {"type": "wasGeneratedBy", "subject": entity, "object": activity},
            {"type": "wasDerivedFrom", "subject": entity, "object": source_entity},
        ])


def assemble_raw_bundle(
    result: CaptureResult,
    output: Path,
    context: CaptureContext,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize one complete/partial CaptureResult and validate Raw v0.2.

    Degradation contract (P0-0):
    - ``complete`` results are assembled directly.
    - ``partial`` results are assembled WITH their warnings preserved in
      quality-report.json — the degradation chain may continue afterward.
    - ``failed`` results are rejected here; the degradation engine in
      ``degradation.py`` should have already routed to a fallback before
      reaching this function.  If you see a ``ValueError`` for a failed
      result, check that the EvidencePlan's fallback chain was exhausted.
    """
    if result.status == "failed":
        raise ValueError(
            "failed CaptureResult has no promotable Raw content to assemble. "
            "The degradation chain should have routed to a fallback before "
            "reaching assemble_raw_bundle(). Check EvidencePlan.fallbacks."
        )
    snapshot = result.snapshot_path.expanduser().resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)

    output = prepare_output(output, overwrite)
    (output / "assets").mkdir()
    (output / "derived").mkdir()
    artifact_references = _copy_artifacts(result, output)
    evidence = _evidence_records(result, artifact_references)
    declared_evidence = sum(item.evidence_count for item in result.modalities.values())
    if declared_evidence != len(evidence):
        raise ValueError(
            f"modality evidence_count total {declared_evidence} differs from "
            f"evidence records {len(evidence)}"
        )

    content = result.content_markdown.rstrip() + "\n"
    (output / "content.md").write_text(content, encoding="utf-8", newline="\n")
    evidence_count = write_jsonl(output / "evidence.jsonl", evidence)

    identity = source_identity(result.source_uri, source_file=snapshot)
    if result.content_hash_status == "unavailable":
        identity["reference_sha256"] = identity.get("content_sha256")
        identity["content_sha256"] = None
        identity["content_hash_status"] = "unavailable"
    metadata = common_metadata(
        capture_id=context.capture_id,
        identity=identity,
        title=result.title or Path(result.source_uri).name or result.source_uri,
        source_type=context.source_type,
        modalities=list(result.modalities),
        route=[result.capability],
        extractor_name=result.provider,
        extractor_version=result.provider_version,
        processing_status=result.status,
        benchmark=False,
    )
    metadata["execution_protocol"] = result.schema_version
    metadata["provider"] = result.provider
    metadata["capability"] = result.capability
    metadata["latency_ms"] = result.latency_ms
    metadata["cost"] = result.cost.to_dict() if result.cost else None
    metadata["failure_disposition"] = result.failure_disposition
    metadata["raw_response_reference"] = None

    if result.raw_response_reference is not None:
        raw_response = result.raw_response_reference.expanduser().resolve()
        if not raw_response.is_file():
            raise FileNotFoundError(raw_response)
        suffix = raw_response.suffix or ".bin"
        destination = output / "derived" / f"provider-response{suffix}"
        shutil.copy2(raw_response, destination)
        metadata["raw_response_reference"] = destination.relative_to(output).as_posix()

    write_json(output / "metadata.json", metadata)
    coverage_checks, coverage_status = coverage_report({
        name: (
            0 if modality.status == "skipped" else 1,
            1 if modality.status == "succeeded" else 0,
        )
        for name, modality in result.modalities.items()
    })
    coverage_checks["evidence_records"] = {
        "expected": evidence_count,
        "observed": evidence_count,
        "status": "passed",
    }
    quality = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": result.status,
        "review_status": "pending",
        "evidence_count": evidence_count,
        "asset_count": len(artifact_references),
        "elapsed_seconds": None if result.latency_ms is None else result.latency_ms / 1000,
        "coverage_status": coverage_status,
        "coverage_checks": coverage_checks,
        "warnings": list(result.warnings),
        "errors": [item.to_dict() for item in result.errors],
        "human_fallback": "Review CaptureResult evidence before creating a Candidate.",
    }
    write_json(output / "quality-report.json", quality)
    write_json(output / "derived" / "capture-result.json", result.to_dict())

    warnings = "".join(f"- {item}\n" for item in result.warnings) or "- 无\n"
    raw_md = (
        f"---\nschema_version: {SCHEMA_VERSION}\ncapture_id: {context.capture_id}\n"
        f"processing_status: {result.status}\nreview_status: pending\n"
        f"execution_protocol: {result.schema_version}\n---\n\n"
        f"# {result.title or 'Captured source'}\n\n"
        f"## 来源\n\n- URI：`{result.source_uri}`\n"
        f"- Provider：`{result.provider}`\n- Capability：`{result.capability}`\n\n"
        f"## Raw 提取物\n\n- [正文](content.md)\n"
        f"- [原子证据](evidence.jsonl)：{evidence_count} 条\n"
        f"- [Capture Result](derived/capture-result.json)\n\n"
        f"## 已知限制\n\n{warnings}"
    )
    (output / "raw.md").write_text(raw_md, encoding="utf-8", newline="\n")

    snapshot_hash = sha256_file(snapshot)
    capture_envelope = {
        "schema_version": "oks-capture-envelope/v0.2",
        "capture_id": context.capture_id,
        "capture_revision": 1,
        "source_type": context.source_type,
        "source_uri": result.source_uri,
        "captured_at": result.finished_at,
        "submitted_by": None,
        "user_note": None,
        "content": None,
        "source_snapshot": {
            "kind": result.snapshot_kind,
            "content_hash_status": result.content_hash_status,
            "final_url": result.source_uri,
            "content_type": result.snapshot_media_type,
            "size": snapshot.stat().st_size,
            "sha256": snapshot_hash,
        },
        "content_hash": "0" * 64,
        "hash_algorithm": "sha256-canonical-json-v1",
        "source_record": None,
        "attachments": [],
        "capture_adapter": {"name": result.provider, "version": result.provider_version},
    }
    capture_envelope["content_hash"] = _canonical_envelope_hash(capture_envelope)
    run_outputs = [
        {
            "dataset_id": f"artifact:{artifact_id}",
            "uri": relative,
            "kind": "artifact",
            "sha256": sha256_file(output / relative),
        }
        for artifact_id, relative in artifact_references.items()
    ]
    processing_run = {
        "schema_version": "oks-processing-run/v0.2",
        "run_id": context.run_id,
        "parent_run_id": None,
        "capture_id": context.capture_id,
        "recipe_version": context.recipe_version,
        "job": {
            "namespace": "oks.capture",
            "name": result.provider,
            "version": result.provider_version,
            "capability": result.capability,
        },
        "status": result.status,
        "failure_disposition": result.failure_disposition,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "inputs": [{
            "dataset_id": f"source:{snapshot_hash[:16]}",
            "uri": result.source_uri,
            "kind": "source",
            "sha256": snapshot_hash,
        }],
        "outputs": run_outputs,
        "modalities": {
            name: modality.to_dict(result.capability)
            for name, modality in result.modalities.items()
        },
        "warnings": list(result.warnings),
        "errors": [item.to_dict() for item in result.errors],
    }
    capture_path = output / "derived" / "capture-envelope.json"
    run_path = output / "derived" / "processing-run.json"
    write_json(capture_path, capture_envelope)
    write_json(run_path, processing_run)

    legacy_report = validate_bundle(output)
    if not legacy_report["valid"]:
        raise ValueError(f"assembled legacy bundle is invalid: {legacy_report['errors']}")
    report = finalize_bundle_v2(output, capture_path, run_path, source_path=snapshot)
    manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    _add_artifact_provenance(output, manifest, result, artifact_references)
    write_json(output / "bundle.json", manifest)
    final_report = validate_bundle(output)
    if not final_report["valid"]:
        raise ValueError(f"artifact provenance made bundle invalid: {final_report['errors']}")
    return final_report
