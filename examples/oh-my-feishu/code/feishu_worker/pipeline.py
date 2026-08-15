"""Feishu worker pipeline — process_record orchestration and its direct helpers.

Extracted from feishu_base_worker.py (Round 3 Phase 3).  Imports only from
feishu_worker.* leaf modules and stdlib.  Never imports feishu_base_worker.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from feishu_worker.config import WorkerConfig
from feishu_worker.io_utils import (
    attachment_capability,
    atomic_write_json,
    content_type_extension,
    _redact_error_text,
    sha256_file,
    utc_now,
)
from feishu_worker.base_client import (
    RETRYABLE_CODES,
    parse_json_output,
    lark_json as _base_client_lark_json,
    base_args as _base_client_base_args,
)
from feishu_worker.capture import (
    extract_url,
    normalize_attachments,
    capture_envelope,
    envelope_content_hash,
)
from feishu_worker.source_router import (
    _connector_binary as _source_router__connector_binary,
    package_local_attachment as _source_router_package_local_attachment,
    package_routed_source as _source_router_package_routed_source,
    package_public_web as _source_router_package_public_web,
)

ROOT = Path(__file__).resolve().parents[2]


# ── Thin wrappers (supply ROOT) ──────────────────────────────────────────


def lark_json(config: WorkerConfig, *arguments: str) -> dict[str, Any]:
    return _base_client_lark_json(config, *arguments, root=ROOT)


def base_args(config: WorkerConfig) -> list[str]:
    return _base_client_base_args(config)


def _connector_binary() -> list[str]:
    return _source_router__connector_binary(ROOT)


# ── Direct helpers for process_record ────────────────────────────────────


def update_record(config: WorkerConfig, record_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update one Base record via the worker's monkeypatchable lark_json."""
    return lark_json(
        config,
        "base",
        "+record-upsert",
        *_base_client_base_args(config),
        "--record-id",
        record_id,
        "--json",
        json.dumps(patch, ensure_ascii=False, separators=(",", ":")),
    )


def download_attachments(config: WorkerConfig, record_id: str, output: Path) -> list[Path]:
    output = output.resolve()
    try:
        relative_output = output.relative_to(ROOT)
    except ValueError as error:
        raise RuntimeError(f"attachment download target must stay inside Studio: {output}") from error
    output.mkdir(parents=True, exist_ok=True)
    lark_json(
        config,
        "base",
        "+record-download-attachment",
        *base_args(config),
        "--record-id",
        record_id,
        "--output",
        "./" + relative_output.as_posix(),
        "--overwrite",
    )
    return sorted(path for path in output.iterdir() if path.is_file())


def initial_run(run_id: str, capture: dict[str, Any], capability: str = "web.trafilatura") -> dict[str, Any]:
    return {
        "schema_version": "oks-processing-run/v0.2",
        "run_id": run_id,
        "parent_run_id": None,
        "capture_id": capture["capture_id"],
        "recipe_version": "feishu-web-v0.1" if capability == "web.trafilatura" else "feishu-attachment-v0.1",
        "job": {
            "namespace": "open-knowledge-studio",
            "name": "feishu-base-to-raw",
            "version": "0.1.0",
            "capability": capability,
        },
        "started_at": utc_now(),
        "finished_at": None,
        "status": "running",
        "failure_disposition": "none",
        "inputs": [
            {
                "dataset_id": capture["capture_id"],
                "uri": capture["source_uri"],
                "kind": "capture",
                "sha256": capture["content_hash"],
            }
        ],
        "outputs": [],
        "modalities": {
            "text": {"status": "pending", "capability": capability if capability in {"web.trafilatura", "office.markitdown", "pdf.mineru"} else None, "error_code": None, "evidence_count": 0},
            "ocr": {"status": "skipped", "capability": None, "error_code": None, "evidence_count": 0},
            "asr": {"status": "skipped", "capability": None, "error_code": None, "evidence_count": 0},
            "video": {"status": "skipped", "capability": None, "error_code": None, "evidence_count": 0},
            "visual_observation": {"status": "skipped", "capability": None, "error_code": None, "evidence_count": 0},
        },
        "warnings": [],
        "errors": [],
    }


def finish_run(
    run: dict[str, Any],
    status: str,
    *,
    disposition: str = "none",
    error: dict[str, Any] | None = None,
    error_modality: str = "text",
) -> None:
    run["status"] = status
    run["failure_disposition"] = disposition
    run["finished_at"] = utc_now()
    if error:
        run["errors"].append({"code": error["code"], "message": error["message"], "modality": error_modality})
        run["modalities"][error_modality].update({"status": "failed", "error_code": error["code"]})


def finalize_raw_v2(
    config: WorkerConfig,
    output: Path,
    capture_path: Path,
    run_path: Path,
    source_path: Path | None = None,
) -> dict[str, Any]:
    connector = _connector_binary()
    command = [
            *connector,
            "finalize-v2",
            str(output),
            "--capture-envelope",
            str(capture_path),
            "--processing-run",
            str(run_path),
        ]
    if source_path is not None:
        command.extend(["--source", str(source_path)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    report = parse_json_output(result)
    if report.get("valid") is not True or report.get("schema_version") != "raw-multimodal/v0.2":
        raise RuntimeError(f"Raw Bundle v0.2 validation failed: {json.dumps(report, ensure_ascii=False)}")
    return report


def probe_source(config: WorkerConfig, url: str) -> dict[str, Any]:
    connector = _connector_binary()
    result = subprocess.run(
        [*connector, "probe", url],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return parse_json_output(result, allow_codes={0, 2})


def download_public_source(
    config: WorkerConfig,
    url: str,
    probe_receipt: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    suffix = Path(str(probe_receipt.get("final_url") or url).split("?", 1)[0]).suffix.lower()
    if not suffix:
        suffix = content_type_extension(probe_receipt.get("content_type"))
    if not suffix:
        raise RuntimeError("public file route has neither a supported URL extension nor MIME type")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"source{suffix}"
    connector = _connector_binary()
    result = subprocess.run(
        [
            *connector,
            "fetch",
            url,
            "--output",
            str(target),
            "--overwrite",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    receipt = parse_json_output(result, allow_codes={0, 2})
    if receipt.get("status") != "ok":
        error = receipt.get("error") or {}
        raise RuntimeError(f"{error.get('code', 'FETCH_FAILED')}: {error.get('message', 'source download failed')}")
    downloaded = Path(str(receipt.get("output") or target)).resolve()
    if not downloaded.is_file():
        raise RuntimeError(f"fetch reported success without a source snapshot: {downloaded}")
    return downloaded, receipt


def package_local_attachment(config: WorkerConfig, source: Path, output: Path) -> dict[str, Any]:
    """Package a local attachment file into a Raw bundle (delegates to feishu_worker.source_router)."""
    return _source_router_package_local_attachment(config, source, output, root=ROOT)


def package_routed_source(config: WorkerConfig, source: str, output: Path) -> dict[str, Any]:
    """Package a platform-routed source into a Raw bundle (delegates to feishu_worker.source_router)."""
    return _source_router_package_routed_source(config, source, output, root=ROOT)


def package_public_web(
    config: WorkerConfig,
    url: str,
    output: Path,
    human_context: str,
) -> dict[str, Any]:
    """Package a public web page into a Raw bundle (delegates to feishu_worker.source_router)."""
    return _source_router_package_public_web(config, url, output, human_context, root=ROOT)


# ── Shared tail helpers (dedup attachment / public-file / public-web) ──────


def _complete_bundle(
    *,
    config: WorkerConfig,
    record_id: str,
    run: dict[str, Any],
    run_dir: Path,
    capture: dict[str, Any],
    output: Path,
    report: dict[str, Any],
    modality_key: str,
    extra_metadata: dict[str, str] | None,
    build_success_patch: Any,
    _finalize: Any,
    _update: Any,
    finalize_source: Path | None = None,
) -> None:
    """Success tail: metadata capture-envelope write, outputs, finish_run, finalize, Base update."""
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["capture_envelope"] = capture
    if extra_metadata:
        metadata.update(extra_metadata)
    atomic_write_json(metadata_path, metadata)
    quality = report.get("processing_status") or metadata.get("processing_status") or "partial"
    evidence_count = int(report.get("evidence_count") or 0)
    run["modalities"][modality_key].update({"status": "succeeded", "evidence_count": evidence_count})
    run["outputs"] = [{"dataset_id": f"bundle:{capture['capture_id']}", "uri": str(output), "kind": "bundle", "sha256": None}]
    finish_run(run, "complete" if quality == "complete" else "partial")
    atomic_write_json(run_dir / "processing-run.json", run)
    _finalize(config, output, run_dir / "capture-envelope.json", run_dir / "processing-run.json", finalize_source)
    _update(config, record_id, build_success_patch(quality))


def _fail_bundle(
    *,
    config: WorkerConfig,
    record_id: str,
    run: dict[str, Any],
    run_dir: Path,
    error: Exception,
    failure_code: str,
    build_failure_patch: Any,
    _update: Any,
    clear_outputs: bool = True,
) -> None:
    """Failure tail: finish_run, processing-run write, Base update with redaction."""
    failure = {"code": failure_code, "message": str(error)}
    if clear_outputs:
        run["outputs"] = []
    finish_run(run, "failed", disposition="retryable", error=failure)
    atomic_write_json(run_dir / "processing-run.json", run)
    redacted = _redact_error_text(str(error))
    _update(config, record_id, build_failure_patch(failure_code, redacted))


# ── Main pipeline ────────────────────────────────────────────────────────


def process_record(
    config: WorkerConfig,
    record: dict[str, Any],
    *,
    claimed_run_id: str | None = None,
    _update_record: Any = None,
    _download_attachments: Any = None,
    _package_local_attachment: Any = None,
    _finalize_raw_v2: Any = None,
    _probe_source: Any = None,
    _download_public_source: Any = None,
    _package_routed_source: Any = None,
    _package_public_web: Any = None,
) -> dict[str, Any]:
    _update = _update_record if _update_record is not None else update_record
    _dl_att = _download_attachments if _download_attachments is not None else download_attachments
    _pkg_local = _package_local_attachment if _package_local_attachment is not None else package_local_attachment
    _finalize = _finalize_raw_v2 if _finalize_raw_v2 is not None else finalize_raw_v2
    _probe = _probe_source if _probe_source is not None else probe_source
    _dl_source = _download_public_source if _download_public_source is not None else download_public_source
    _pkg_routed = _package_routed_source if _package_routed_source is not None else package_routed_source
    _pkg_web = _package_public_web if _package_public_web is not None else package_public_web

    record_id = record["record_id"]
    fields = record["fields"]
    url = extract_url(fields.get("内容"))
    attachment_descriptors = normalize_attachments(fields.get("附件"))
    run_id = claimed_run_id or f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    capture = capture_envelope(config, record_id, fields)
    source_hash = capture["content_hash"]
    run_dir = ROOT / ".oks" / "runs" / run_id
    declared_capability = "web.trafilatura"
    if not url and attachment_descriptors:
        declared_capability, _ = attachment_capability(Path(attachment_descriptors[0]["name"]))
    run = initial_run(run_id, capture, declared_capability)
    atomic_write_json(run_dir / "capture-envelope.json", capture)
    atomic_write_json(run_dir / "processing-run.json", run)
    _update(
        config,
        record_id,
        {
            "运行状态": "已领取",
            "运行ID": run_id,
            "来源哈希": source_hash,
            "错误码": None,
            "错误说明": None,
            "重试": False,
            "Wiki状态": "none",
        },
    )
    if not url and attachment_descriptors:
        try:
            downloaded = _dl_att(config, record_id, run_dir / "source-downloads")
            if len(downloaded) != 1:
                raise RuntimeError(f"首版附件 Worker 要求恰好 1 个附件，实际下载 {len(downloaded)} 个")
            source = downloaded[0]
            capability, modality = attachment_capability(source)
            capture["attachments"][0]["sha256"] = sha256_file(source)
            source_hash = envelope_content_hash(capture)
            capture["content_hash"] = source_hash
            capture["capture_id"] = f"feishu-{record_id}-{source_hash[:12]}"
            run["capture_id"] = capture["capture_id"]
            run["job"]["capability"] = capability
            run["inputs"] = [{"dataset_id": capture["capture_id"], "uri": capture["source_uri"], "kind": "capture", "sha256": source_hash}]
            run["modalities"]["text"]["status"] = "skipped" if modality != "text" else "running"
            run["modalities"][modality].update({"status": "running", "capability": capability})
            atomic_write_json(run_dir / "capture-envelope.json", capture)
            atomic_write_json(run_dir / "processing-run.json", run)
            _update(config, record_id, {"运行状态": "探测中", "来源哈希": source_hash, "采集模式": "附件"})
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-.") or "attachment"
            output = config.output_root / f"feishu-{record_id}-{source_hash[:10]}-{safe_stem}"
            report = _pkg_local(config, source, output)
            _complete_bundle(
                config=config,
                record_id=record_id,
                run=run,
                run_dir=run_dir,
                capture=capture,
                output=output,
                report=report,
                modality_key=modality,
                extra_metadata=None,
                build_success_patch=lambda q: {
                    "运行状态": "Raw就绪",
                    "采集模式": "附件",
                    "Raw Bundle": str(output),
                    "质量状态": q,
                    "错误码": None,
                    "错误说明": None,
                    "总结": f"附件 Raw Bundle v0.2 已生成并通过校验；能力={capability}；质量状态={q}。",
                },
                _finalize=_finalize,
                _update=_update,
                finalize_source=source,
            )
        except Exception as error:
            _fail_bundle(
                config=config,
                record_id=record_id,
                run=run,
                run_dir=run_dir,
                error=error,
                failure_code="ATTACHMENT_PROCESSING_FAILED",
                build_failure_patch=lambda code, msg: {
                    "运行状态": "可重试失败",
                    "采集模式": "附件",
                    "错误码": code,
                    "错误说明": msg[:500],
                    "质量状态": "failed",
                    "Raw Bundle": None,
                    "总结": f"附件未生成 Raw：{msg}"[:1000],
                },
                _update=_update,
            )
        return run

    if not url:
        error = {"code": "UNSUPPORTED_SOURCE", "message": "内容字段中没有 HTTP(S) URL"}
        finish_run(run, "failed", disposition="final", error=error)
        atomic_write_json(run_dir / "processing-run.json", run)
        _update(
            config,
            record_id,
            {"运行状态": "最终失败", "错误码": error["code"], "错误说明": error["message"], "质量状态": "failed"},
        )
        return run

    _update(config, record_id, {"运行状态": "探测中"})
    run["modalities"]["text"]["status"] = "running"
    receipt = _probe(config, url)
    atomic_write_json(run_dir / "fetch-receipt.json", receipt)
    if receipt.get("status") != "ok":
        source_error = receipt.get("error") or {}
        code = source_error.get("code", "FETCH_FAILED")
        message = source_error.get("message", "链接探测未成功")
        if receipt.get("status") == "needs_user_action":
            state = "需授权" if code in {"AUTH_REQUIRED", "CHALLENGE_REQUIRED"} else "需人工"
        elif code in RETRYABLE_CODES:
            state = "可重试失败"
        else:
            state = "最终失败"
        error = {"code": code, "message": message}
        disposition = {
            "需授权": "needs_user_auth",
            "需人工": "needs_user_action",
            "可重试失败": "retryable",
            "最终失败": "final",
        }[state]
        finish_run(run, "failed", disposition=disposition, error=error)
        atomic_write_json(run_dir / "processing-run.json", run)
        _update(
            config,
            record_id,
            {
                "运行状态": state,
                "采集模式": "登录浏览器" if state == "需授权" else "HTTP",
                "错误码": code,
                "错误说明": _redact_error_text(message)[:500],
                "质量状态": "failed",
                "Raw Bundle": None,
                "总结": f"未生成 Raw：{code}。{_redact_error_text(message)}"[:1000],
            },
        )
        return run

    if (receipt.get("error") or {}).get("code") == "JS_RENDER_REQUIRED" or receipt.get("next_action") == "browser_public":
        error = {
            "code": "JS_RENDER_REQUIRED",
            "message": "公开页面需要浏览器执行 JavaScript；等待受控浏览器快照后继续",
        }
        finish_run(run, "failed", disposition="needs_user_action", error=error)
        atomic_write_json(run_dir / "processing-run.json", run)
        _update(
            config,
            record_id,
            {
                "运行状态": "需人工",
                "采集模式": "公开浏览器",
                "错误码": error["code"],
                "错误说明": error["message"],
                "质量状态": "failed",
                "Raw Bundle": None,
                "总结": "HTTP 探测确认需要 JavaScript；尚未生成 Raw，等待公开浏览器快照。",
            },
        )
        return run

    if receipt.get("next_action") == "platform_extractor":
        try:
            route = receipt.get("route_plan") or {}
            platform_reference = {
                "schema_version": "oks-platform-source-reference/v0.1",
                "source_url": url,
                "final_url": str(receipt.get("final_url") or url),
                "platform": route.get("platform"),
                "source_type": route.get("source_type"),
                "original_media_retained": False,
                "content_hash_status": "unavailable",
                "retention_note": "The extractor may acquire temporary media; Raw retains captions, frames, OCR and metadata rather than the full platform media file.",
            }
            reference_path = run_dir / "platform-source.json"
            atomic_write_json(reference_path, platform_reference)
            capture["source_snapshot"] = {
                "kind": "reference",
                "content_hash_status": "unavailable",
                "final_url": platform_reference["final_url"],
                "content_type": receipt.get("content_type"),
                "size": reference_path.stat().st_size,
                "sha256": sha256_file(reference_path),
            }
            source_hash = envelope_content_hash(capture)
            capture["content_hash"] = source_hash
            capture["capture_id"] = f"feishu-{record_id}-{source_hash[:12]}"
            run["capture_id"] = capture["capture_id"]
            run["recipe_version"] = "feishu-platform-video-v0.1"
            run["job"]["capability"] = "video.watch"
            run["inputs"] = [{"dataset_id": capture["capture_id"], "uri": capture["source_uri"], "kind": "capture", "sha256": source_hash}]
            run["modalities"]["text"].update({"status": "skipped", "capability": None})
            run["modalities"]["video"].update({"status": "running", "capability": "video.watch"})
            atomic_write_json(run_dir / "capture-envelope.json", capture)
            atomic_write_json(run_dir / "processing-run.json", run)
            _update(config, record_id, {"运行状态": "探测中", "来源哈希": source_hash, "采集模式": "平台提取器"})
            output = config.output_root / f"feishu-{record_id}-{source_hash[:10]}-platform-video"
            report = _pkg_routed(config, url, output)
            metadata_path = output / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["capture_envelope"] = capture
            metadata["fetch_receipt"] = str((run_dir / "fetch-receipt.json").resolve())
            metadata["platform_source_reference"] = str(reference_path.resolve())
            atomic_write_json(metadata_path, metadata)
            quality_path = output / "quality-report.json"
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
            quality = report.get("processing_status") or quality_report.get("processing_status") or metadata.get("processing_status") or "partial"
            frame_count = int(quality_report.get("frame_count") or 0)
            transcript_count = int(quality_report.get("transcript_segment_count") or 0)
            ocr_count = int(quality_report.get("ocr_block_count") or 0)
            run["modalities"]["video"].update({"status": "succeeded" if frame_count else "skipped", "evidence_count": frame_count})
            run["modalities"]["asr"].update({"status": "succeeded" if transcript_count else "skipped", "capability": "video.watch" if transcript_count else None, "evidence_count": transcript_count})
            run["modalities"]["ocr"].update({"status": "succeeded" if ocr_count else "skipped", "capability": "image.rapidocr" if ocr_count else None, "evidence_count": ocr_count})
            run["warnings"] = [str(item) for item in quality_report.get("warnings", [])]
            run["outputs"] = [{"dataset_id": f"bundle:{capture['capture_id']}", "uri": str(output), "kind": "bundle", "sha256": None}]
            finish_run(run, "complete" if quality == "complete" else "partial")
            atomic_write_json(run_dir / "processing-run.json", run)
            _finalize(config, output, run_dir / "capture-envelope.json", run_dir / "processing-run.json", reference_path)
            _update(
                config,
                record_id,
                {
                    "运行状态": "Raw就绪",
                    "采集模式": "平台提取器",
                    "Raw Bundle": str(output),
                    "质量状态": quality,
                    "错误码": None,
                    "错误说明": None,
                    "总结": f"平台视频 Raw Bundle v0.2 已生成；帧={frame_count}，字幕/ASR段={transcript_count}，OCR块={ocr_count}；未永久保存整段平台媒体。",
                },
            )
        except Exception as error:
            failure = {"code": "PLATFORM_EXTRACTOR_FAILED", "message": str(error)}
            run["outputs"] = []
            finish_run(run, "failed", disposition="retryable", error=failure, error_modality="video")
            atomic_write_json(run_dir / "processing-run.json", run)
            _update(
                config,
                record_id,
                {
                    "运行状态": "可重试失败",
                    "采集模式": "平台提取器",
                    "错误码": failure["code"],
                    "错误说明": _redact_error_text(failure["message"])[:500],
                    "质量状态": "failed",
                    "Raw Bundle": None,
                    "总结": f"平台提取器未生成 Raw：{_redact_error_text(failure['message'])}"[:1000],
                },
            )
        return run

    if not str(receipt.get("content_type", "")).lower().startswith("text/html"):
        try:
            source, acquisition = _dl_source(config, url, receipt, run_dir / "source-downloads")
            atomic_write_json(run_dir / "acquisition-receipt.json", acquisition)
            capability, modality = attachment_capability(source)
            if capability == "office.markitdown" and source.suffix.lower() not in {".pptx", ".docx", ".xlsx", ".html", ".htm", ".txt", ".csv"}:
                raise RuntimeError(f"unsupported downloaded source format: {source.suffix or 'unknown'}")
            capture["source_snapshot"] = {
                "final_url": str(acquisition.get("final_url") or url),
                "content_type": acquisition.get("content_type"),
                "size": int(acquisition.get("downloaded_bytes") or source.stat().st_size),
                "sha256": str(acquisition.get("content_sha256") or sha256_file(source)),
            }
            source_hash = envelope_content_hash(capture)
            capture["content_hash"] = source_hash
            capture["capture_id"] = f"feishu-{record_id}-{source_hash[:12]}"
            run["capture_id"] = capture["capture_id"]
            run["recipe_version"] = "feishu-public-file-v0.1"
            run["job"]["capability"] = capability
            run["inputs"] = [{"dataset_id": capture["capture_id"], "uri": capture["source_uri"], "kind": "capture", "sha256": source_hash}]
            run["modalities"]["text"]["status"] = "skipped" if modality != "text" else "running"
            run["modalities"][modality].update({"status": "running", "capability": capability})
            atomic_write_json(run_dir / "capture-envelope.json", capture)
            atomic_write_json(run_dir / "processing-run.json", run)
            _update(config, record_id, {"运行状态": "探测中", "来源哈希": source_hash, "采集模式": "HTTP"})
            output = config.output_root / f"feishu-{record_id}-{source_hash[:10]}-{source.stem}"
            report = _pkg_local(config, source, output)
            _complete_bundle(
                config=config,
                record_id=record_id,
                run=run,
                run_dir=run_dir,
                capture=capture,
                output=output,
                report=report,
                modality_key=modality,
                extra_metadata={
                    "fetch_receipt": str((run_dir / "fetch-receipt.json").resolve()),
                    "acquisition_receipt": str((run_dir / "acquisition-receipt.json").resolve()),
                },
                build_success_patch=lambda q: {
                    "运行状态": "Raw就绪",
                    "采集模式": "HTTP",
                    "Raw Bundle": str(output),
                    "质量状态": q,
                    "错误码": None,
                    "错误说明": None,
                    "总结": f"公网文件 Raw Bundle v0.2 已生成并通过校验；能力={capability}；质量状态={q}。",
                },
                _finalize=_finalize,
                _update=_update,
                finalize_source=source,
            )
        except Exception as error:
            _fail_bundle(
                config=config,
                record_id=record_id,
                run=run,
                run_dir=run_dir,
                error=error,
                failure_code="PUBLIC_FILE_PROCESSING_FAILED",
                build_failure_patch=lambda code, msg: {
                    "运行状态": "可重试失败",
                    "采集模式": "HTTP",
                    "错误码": code,
                    "错误说明": msg[:500],
                    "质量状态": "failed",
                    "Raw Bundle": None,
                    "总结": f"公网文件未生成 Raw：{msg}"[:1000],
                },
                _update=_update,
            )
        return run

    output = config.output_root / f"feishu-{record_id}-{source_hash[:10]}"
    try:
        report = _pkg_web(config, url, output, str(fields.get("思考") or ""))
        _complete_bundle(
            config=config,
            record_id=record_id,
            run=run,
            run_dir=run_dir,
            capture=capture,
            output=output,
            report=report,
            modality_key="text",
            extra_metadata={"fetch_receipt": str((run_dir / "fetch-receipt.json").resolve())},
            build_success_patch=lambda q: {
                "运行状态": "Raw就绪",
                "采集模式": "HTTP",
                "Raw Bundle": str(output),
                "质量状态": q,
                "错误码": None,
                "错误说明": None,
                "总结": f"Raw Bundle v0.2 已生成并通过校验；质量状态={q}。",
            },
            _finalize=_finalize,
            _update=_update,
        )
    except Exception as error:
        _fail_bundle(
            config=config,
            record_id=record_id,
            run=run,
            run_dir=run_dir,
            error=error,
            failure_code="EXTRACTION_FAILED",
            build_failure_patch=lambda code, msg: {
                "运行状态": "可重试失败",
                "采集模式": "HTTP",
                "错误码": code,
                "错误说明": msg[:500],
                "质量状态": "failed",
                "Raw Bundle": None,
                "总结": f"未生成 Raw：{code}。{msg}"[:1000],
            },
            _update=_update,
            clear_outputs=False,
        )
    return run
