"""Raw Bundle validation (v0.1 and v0.2)."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tempfile
from _shared import _fsync_dir, sha256_file
from constants import SCHEMA_VERSION, RAW_V2_VERSION
from route import is_url


def validate_bundle(bundle: Path) -> dict[str, Any]:
    from _shared import markdown_asset_references
    bundle = bundle.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not bundle.is_dir():
        return {"valid": False, "bundle": str(bundle), "errors": ["bundle目录不存在"]}
    required = [
        "raw.md",
        "content.md",
        "metadata.json",
        "evidence.jsonl",
        "quality-report.json",
    ]
    for name in required:
        if not (bundle / name).is_file():
            errors.append(f"缺少必需文件：{name}")
    metadata: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    for name, target in (("metadata.json", metadata), ("quality-report.json", quality)):
        path = bundle / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                errors.append(f"{name}必须是JSON对象")
            else:
                target.update(value)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name}无法解析：{exc}")
    if metadata and metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.json schema_version不受支持")
    if metadata and metadata.get("processing_status") not in {"complete", "partial", "failed"}:
        errors.append("metadata.json processing_status无效")
    evidence_count = 0
    evidence_path = bundle / "evidence.jsonl"
    if evidence_path.is_file():
        for line_number, line in enumerate(
            evidence_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                evidence = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"evidence.jsonl第{line_number}行无法解析：{exc}")
                continue
            evidence_count += 1
            if not evidence.get("kind") or not evidence.get("method"):
                errors.append(f"evidence.jsonl第{line_number}行缺少kind或method")
            if not isinstance(evidence.get("locator"), dict):
                errors.append(f"evidence.jsonl第{line_number}行缺少locator")
            asset = evidence.get("locator", {}).get("asset")
            if asset and not (bundle / asset).is_file():
                errors.append(f"evidence.jsonl第{line_number}行引用不存在资产：{asset}")
    if quality:
        expected = quality.get("evidence_count")
        if expected is not None and int(expected) != evidence_count:
            errors.append(f"质量报告证据数{expected}与实际{evidence_count}不一致")
        quality_warnings = [str(item) for item in quality.get("warnings", [])]
        warnings.extend(quality_warnings)
        checks = quality.get("coverage_checks")
        if not isinstance(checks, dict) or not checks:
            errors.append("质量报告缺少coverage_checks")
        else:
            recomputed: list[str] = []
            for name, check in checks.items():
                if not isinstance(check, dict):
                    errors.append(f"coverage_checks.{name}必须是JSON对象")
                    continue
                expected_count = check.get("expected")
                observed_count = check.get("observed")
                declared = check.get("status")
                actual = (
                    "unknown"
                    if expected_count is None
                    else "passed"
                    if observed_count == expected_count
                    else "partial"
                )
                recomputed.append(actual)
                if declared != actual:
                    errors.append(
                        f"coverage_checks.{name}状态{declared}与计数推导结果{actual}不一致"
                    )
            actual_overall = (
                "partial"
                if "partial" in recomputed
                else "passed"
                if recomputed and all(item == "passed" for item in recomputed)
                else "unknown"
            )
            if quality.get("coverage_status") != actual_overall:
                errors.append("coverage_status与coverage_checks不一致")
            if actual_overall == "partial" and not quality_warnings:
                errors.append("覆盖不完整时必须在warnings中显式说明")
    for name in ("raw.md", "content.md", "document.md", "transcript.md", "visual.md"):
        markdown_path = bundle / name
        if not markdown_path.is_file():
            continue
        for reference in markdown_asset_references(markdown_path.read_text(encoding="utf-8")):
            if is_url(reference):
                continue
            if not (markdown_path.parent / reference).is_file():
                errors.append(f"{markdown_path.name}引用不存在资产：{reference}")
    report = {
        "valid": not errors,
        "bundle": str(bundle),
        "schema_version": metadata.get("schema_version"),
        "processing_status": metadata.get("processing_status"),
        "evidence_count": evidence_count,
        "errors": errors,
        "warnings": warnings,
    }
    if (bundle / "bundle.json").is_file():
        v2_report = validate_bundle_v2(bundle)
        report["valid"] = bool(report["valid"] and v2_report["valid"])
        report["schema_version"] = v2_report.get("schema_version")
        report["bundle_id"] = v2_report.get("bundle_id")
        report["processing_status"] = v2_report.get("processing_status")
        report["errors"] = [*report["errors"], *v2_report.get("errors", [])]
        report["warnings"] = list(
            dict.fromkeys([*report["warnings"], *v2_report.get("warnings", [])])
        )
    return report


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile as _tmp
    with _tmp.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                 prefix=f".{path.name}.", dir=path.parent,
                                 delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(Path(handle.name), path)
    _fsync_dir(path.parent)


def _source_snapshot(bundle: Path, metadata: dict[str, Any], explicit_source: Path | None = None) -> Path:
    candidates = [explicit_source.expanduser() if explicit_source else None, bundle / "assets" / "page.html"]
    source = metadata.get("source")
    if isinstance(source, dict):
        for key in ("local_path", "path"):
            if source.get(key):
                candidates.append(Path(str(source[key])).expanduser())
    candidate = next((path.resolve() for path in candidates if path is not None and path.is_file()), None)
    if candidate is None:
        raise ValueError("v0.2 requires a primary source snapshot; none was found")
    source_dir = bundle / "source"
    source_dir.mkdir(exist_ok=True)
    suffix = candidate.suffix or ".bin"
    destination = source_dir / f"primary{suffix.lower()}"
    if candidate != destination.resolve():
        shutil.copy2(candidate, destination)
    return destination


def finalize_bundle_v2(
    bundle: Path,
    capture_envelope_path: Path,
    processing_run_path: Path,
    source_path: Path | None = None,
) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    legacy = validate_bundle(bundle)
    if not legacy["valid"]:
        raise ValueError(f"legacy bundle is invalid: {legacy['errors']}")
    capture = _read_json_object(capture_envelope_path.expanduser().resolve())
    run = _read_json_object(processing_run_path.expanduser().resolve())
    if capture.get("schema_version") != "oks-capture-envelope/v0.2":
        raise ValueError("capture envelope must use oks-capture-envelope/v0.2")
    if run.get("schema_version") != "oks-processing-run/v0.2":
        raise ValueError("processing run must use oks-processing-run/v0.2")
    if capture.get("capture_id") != run.get("capture_id"):
        raise ValueError("capture_id differs between Capture Envelope and Processing Run")
    if run.get("status") not in {"complete", "partial"}:
        raise ValueError("only a successful or partial run can finalize a Raw Bundle")

    metadata = _read_json_object(bundle / "metadata.json")
    quality = _read_json_object(bundle / "quality-report.json")
    primary = _source_snapshot(bundle, metadata, source_path)
    (bundle / "assets").mkdir(exist_ok=True)
    (bundle / "derived").mkdir(exist_ok=True)
    run_journal = bundle / "processing-runs.jsonl"
    existing_runs: list[dict[str, Any]] = []
    if run_journal.is_file():
        for line in run_journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing_runs.append(json.loads(line))
    existing_runs = [item for item in existing_runs if item.get("run_id") != run.get("run_id")]
    existing_runs.append(run)
    _atomic_write_text(
        run_journal,
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing_runs),
    )

    source_rel = primary.relative_to(bundle).as_posix()
    source_hash = sha256_file(primary)
    capture_snapshot = capture.get("source_snapshot") if isinstance(capture.get("source_snapshot"), dict) else {}
    snapshot_kind = capture_snapshot.get("kind", "content")
    content_hash_status = capture_snapshot.get("content_hash_status", "verified")
    source_entity = f"entity:source:{source_hash[:16]}"
    content_entity = f"entity:content:{sha256_file(bundle / 'content.md')[:16]}"
    evidence_entity = f"entity:evidence:{sha256_file(bundle / 'evidence.jsonl')[:16]}"
    activity = f"activity:{run['run_id']}"
    agent = f"agent:{run['job']['name']}:{run['job']['version']}"
    manifest = {
        "schema_version": RAW_V2_VERSION,
        "bundle_id": f"bundle:{capture['capture_id']}:{run['run_id']}",
        "capture_id": capture["capture_id"],
        "content_hash": capture["content_hash"],
        "recipe_version": run["recipe_version"],
        "processing_status": run["status"],
        "files": {
            "manifest": "bundle.json",
            "content": "content.md",
            "evidence": "evidence.jsonl",
            "quality_report": "quality-report.json",
            "processing_runs": "processing-runs.jsonl",
            "source_dir": "source/",
            "assets_dir": "assets/",
            "derived_dir": "derived/",
        },
        "sources": [
            {
                "entity_id": source_entity,
                "path": source_rel,
                "sha256": source_hash,
                "media_type": metadata.get("source", {}).get("content_type") if isinstance(metadata.get("source"), dict) else None,
                "snapshot_kind": snapshot_kind,
                "content_hash_status": content_hash_status,
                "primary_source": True,
            }
        ],
        "derived": [],
        "provenance": {
            "entities": [
                {"id": source_entity, "path": source_rel, "primary_source": True, "snapshot_kind": snapshot_kind, "content_hash_status": content_hash_status},
                {"id": content_entity, "path": "content.md"},
                {"id": evidence_entity, "path": "evidence.jsonl"},
            ],
            "activities": [
                {"id": activity, "run_id": run["run_id"], "started_at": run["started_at"], "finished_at": run["finished_at"], "status": run["status"]}
            ],
            "agents": [
                {"id": agent, "type": "SoftwareAgent", "name": run["job"]["name"], "version": run["job"]["version"], "capability": run["job"].get("capability")}
            ],
            "relations": [
                {"type": "used", "subject": activity, "object": source_entity},
                {"type": "wasGeneratedBy", "subject": content_entity, "object": activity},
                {"type": "wasGeneratedBy", "subject": evidence_entity, "object": activity},
                {"type": "wasDerivedFrom", "subject": content_entity, "object": source_entity},
                {"type": "wasDerivedFrom", "subject": evidence_entity, "object": source_entity},
            ],
        },
        "warnings": list(quality.get("warnings") or []),
    }
    _atomic_write_text(bundle / "bundle.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    report = validate_bundle_v2(bundle)
    if not report["valid"]:
        raise ValueError(f"v0.2 bundle validation failed: {report['errors']}")
    return report


def validate_bundle_v2(bundle: Path) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    errors: list[str] = []
    manifest_path = bundle / "bundle.json"
    if not manifest_path.is_file():
        return {"valid": False, "bundle": str(bundle), "schema_version": None, "errors": ["missing bundle.json"]}
    try:
        manifest = _read_json_object(manifest_path)
    except Exception as exc:
        return {"valid": False, "bundle": str(bundle), "schema_version": None, "errors": [str(exc)]}
    if manifest.get("schema_version") != RAW_V2_VERSION:
        errors.append("schema_version must be raw-multimodal/v0.2")
    expected_files = {
        "manifest": "bundle.json",
        "content": "content.md",
        "evidence": "evidence.jsonl",
        "quality_report": "quality-report.json",
        "processing_runs": "processing-runs.jsonl",
        "source_dir": "source/",
        "assets_dir": "assets/",
        "derived_dir": "derived/",
    }
    if manifest.get("files") != expected_files:
        errors.append("files must match the stable v0.2 layout")
    for name in ("bundle.json", "content.md", "evidence.jsonl", "quality-report.json", "processing-runs.jsonl"):
        if not (bundle / name).is_file():
            errors.append(f"missing required file: {name}")
    for name in ("source", "assets", "derived"):
        if not (bundle / name).is_dir():
            errors.append(f"missing required directory: {name}/")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must contain at least one primary source")
    else:
        if not any(item.get("primary_source") is True for item in sources if isinstance(item, dict)):
            errors.append("sources must mark a primary source")
        for item in sources:
            if not isinstance(item, dict):
                errors.append("source entry must be an object")
                continue
            path = bundle / str(item.get("path", ""))
            if not path.is_file():
                errors.append(f"missing source entity: {item.get('path')}")
            elif item.get("sha256") != sha256_file(path):
                errors.append(f"source hash mismatch: {item.get('path')}")
            if item.get("snapshot_kind", "content") not in {"content", "reference"}:
                errors.append(f"invalid source snapshot_kind: {item.get('snapshot_kind')}")
            if item.get("content_hash_status", "verified") not in {"verified", "unavailable"}:
                errors.append(f"invalid source content_hash_status: {item.get('content_hash_status')}")
    relations = manifest.get("provenance", {}).get("relations", [])
    relation_types = {item.get("type") for item in relations if isinstance(item, dict)}
    for required in ("used", "wasGeneratedBy", "wasDerivedFrom"):
        if required not in relation_types:
            errors.append(f"missing provenance relation: {required}")
    try:
        runs = [json.loads(line) for line in (bundle / "processing-runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if not runs:
            errors.append("processing-runs.jsonl is empty")
        if not any(run.get("capture_id") == manifest.get("capture_id") for run in runs if isinstance(run, dict)):
            errors.append("no processing run matches bundle capture_id")
    except Exception as exc:
        errors.append(f"invalid processing-runs.jsonl: {exc}")
    return {
        "valid": not errors,
        "bundle": str(bundle),
        "schema_version": manifest.get("schema_version"),
        "bundle_id": manifest.get("bundle_id"),
        "processing_status": manifest.get("processing_status"),
        "errors": errors,
        "warnings": manifest.get("warnings", []),
    }


