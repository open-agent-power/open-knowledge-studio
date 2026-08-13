"""Feishu Base source adapter for the Open Knowledge Studio Raw pipeline.

This worker owns orchestration only: it reads capture rows, calls the connector
for safe URL probing, delegates extraction to existing Studio adapters, and
writes honest lifecycle state back to Base. It does not bypass authentication,
CAPTCHAs, robots controls, or platform restrictions.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid

import yaml

from feishu_worker.config import (
    WorkerConfig,
    configured_knowledge_root as _config_configured_knowledge_root,
    load_config as _config_load_config,
    resolve_lark_cli,
)
from feishu_worker.io_utils import (
    HOME,
    attachment_capability,
    atomic_write_json,
    atomic_write_text,
    content_type_extension,
    _redact_error_text,
    scalar_cell,
    sha256_file,
    utc_now,
)
from feishu_worker.base_client import (
    RETRYABLE_CODES,
    _FATAL_LARK_CODES,
    _LARK_BASE_DELAY,
    _LARK_MAX_RETRIES,
    _LARK_SUBPROCESS_TIMEOUT,
    CLAIMABLE_STATUSES,
    _extract_lark_error_code,
    _is_fatal_lark_error,
    _is_retryable_lark_error,
    parse_json_output,
    _parse_record_rows,
    lark_json as _base_client_lark_json,
    base_args as _base_client_base_args,
    update_record as _base_client_update_record,
    create_record as _base_client_create_record,
    list_records as _base_client_list_records,
    get_record as _base_client_get_record,
    list_review_records as _base_client_list_review_records,
)
from feishu_worker.claim import (
    parse_base_datetime,
    is_candidate,
    local_claim_lock as _claim_local_claim_lock,
    claim_next_record as _claim_claim_next_record,
    claim_record as _claim_claim_record,
    release_lease as _claim_release_lease,
)
from feishu_worker.capture import (
    URL_RE,
    extract_url,
    normalize_attachments,
    capture_user_note,
    capture_content_hash,
    envelope_content_hash,
    capture_envelope,
)
from feishu_worker.source_router import (
    _connector_binary as _source_router__connector_binary,
    package_local_attachment as _source_router_package_local_attachment,
    package_routed_source as _source_router_package_routed_source,
    package_public_web as _source_router_package_public_web,
)
from feishu_worker.pipeline import process_record as _pipeline_process_record
from feishu_worker.candidate import (
    parse_candidate_document as _candidate_parse_candidate_document,
    render_candidate_document as _candidate_render_candidate_document,
    candidate_state_path as _candidate_candidate_state_path,
    load_candidate_state as _candidate_load_candidate_state,
    candidate_review_fingerprint as _candidate_candidate_review_fingerprint,
    render_candidate_review_message as _candidate_render_candidate_review_message,
    send_candidate_review_notification as _candidate_send_candidate_review_notification,
    publish_candidate as _candidate_publish_candidate,
)
from feishu_worker.review_events import (
    apply_review_event_with_fallback as _review_apply_review_event_with_fallback,
    apply_review_reply_event as _review_apply_review_reply_event,
    consume_review_events as _review_consume_review_events,
    decoded_raw_message_content as _review_decoded_raw_message_content,
    event_reviewed_at as _review_event_reviewed_at,
    find_candidate_state_for_reply as _review_find_candidate_state_for_reply,
    parse_review_reply as _review_parse_review_reply,
    pending_review_states_in_chat as _review_pending_review_states_in_chat,
    process_next_review as _review_process_next_review,
    promote_candidate_document as _review_promote_candidate_document,
    raw_message as _review_raw_message,
    read_review_record_after_write as _review_read_review_record_after_write,
    reconcile_historical_review_reply as _review_reconcile_historical_review_reply,
    record_review_event as _review_record_review_event,
    review_candidate as _review_review_candidate,
    review_states_for_prompt as _review_review_states_for_prompt,
    REVIEW_ACTIONS,
    REVIEW_ACTION_RE,
)
from feishu_worker.states import normalize_rating

# ── Legacy wrappers: supply ROOT so callers keep one-argument API ──


def load_config(args: argparse.Namespace) -> WorkerConfig:
    return _config_load_config(args, root=ROOT)


def configured_knowledge_root(config: WorkerConfig) -> Path:
    return _config_configured_knowledge_root(config, root=ROOT)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_FIELDS = [
    "运行状态",
    "运行ID",
    "Raw Bundle",
    "Wiki状态",
    "候选ID",
    "候选内容",
    "审核动作",
    "审核意见",
    "修改类型",
    "审核时间",
    "Wiki路径",
]
CAPTURE_FIELDS = [
    "内容",
    "思考",
    "重点问题（可选）",
    "附件",
    "运行状态",
    "运行ID",
    "来源哈希",
    "重试",
    "租约所有者",
    "租约到期",
    "创建时间",
    "Wiki状态",
    "采集模式",
]
# REVIEW_ACTIONS and REVIEW_ACTION_RE are re-exported from feishu_worker.review_events


# ── Backward-compatible wrappers (supply ROOT / default projections) ──


def lark_json(config: WorkerConfig, *arguments: str) -> dict[str, Any]:
    return _base_client_lark_json(config, *arguments, root=ROOT)


def base_args(config: WorkerConfig) -> list[str]:
    return _base_client_base_args(config)


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


def create_record(config: WorkerConfig, fields: dict[str, Any]) -> dict[str, Any]:
    """Create one Base record via the worker's monkeypatchable lark_json."""
    return lark_json(
        config,
        "base",
        "+record-upsert",
        *_base_client_base_args(config),
        "--json",
        json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
    )


def created_record_id(envelope: dict[str, Any]) -> str:
    """Normalize current and legacy lark-cli record-create response shapes."""
    data = envelope.get("data")
    record = data.get("record") if isinstance(data, dict) else None
    if not isinstance(record, dict):
        record = data if isinstance(data, dict) else {}
    direct = record.get("record_id") or record.get("id")
    if direct:
        return str(direct)
    record_ids = record.get("record_id_list")
    if isinstance(record_ids, list) and record_ids:
        return str(record_ids[0])
    raise RuntimeError("lark-cli did not return a record ID after Base creation")


def list_records(config: WorkerConfig, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch capture-field records via the worker's monkeypatchable lark_json."""
    command = [
        "base",
        "+record-list",
        *_base_client_base_args(config),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for field in CAPTURE_FIELDS:
        command.extend(["--field-id", field])
    # Fetch every claimable status: is_candidate() also accepts retry-flagged
    # records and 已领取 records with an expired lease. Filtering to 待处理 here
    # would make retries and crash recovery unreachable.
    command.extend([
        "--filter-json",
        json.dumps(
            {"logic": "and", "conditions": [["运行状态", "intersects", list(CLAIMABLE_STATUSES)]]},
            ensure_ascii=False,
        ),
    ])
    envelope = lark_json(config, *command)
    data = envelope.get("data", {})
    return _parse_record_rows(
        data.get("data", []),
        data.get("fields", CAPTURE_FIELDS),
        data.get("record_id_list", []),
    )


def get_record(
    config: WorkerConfig,
    record_id: str,
    projection: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch one Base record by id via the worker's monkeypatchable lark_json."""
    fields_requested = projection if projection is not None else CANDIDATE_FIELDS
    command = [
        "base",
        "+record-get",
        *_base_client_base_args(config),
        "--record-id",
        record_id,
        "--format",
        "json",
    ]
    for field in fields_requested:
        command.extend(["--field-id", field])
    envelope = lark_json(config, *command)
    data = envelope.get("data", {})
    rows = data.get("data", [])
    fields = data.get("fields", fields_requested)
    record_ids = data.get("record_id_list", [])
    if not rows:
        raise RuntimeError(f"Base record not found: {record_id}")
    row = rows[0]
    if isinstance(row, list):
        values = dict(zip(fields, row))
    elif isinstance(row, dict):
        values = row.get("fields", row)
    else:
        raise RuntimeError(f"Base record has unsupported shape: {record_id}")
    resolved_id = record_ids[0] if record_ids else record_id
    return {"record_id": resolved_id, "fields": values}


def list_review_records(config: WorkerConfig, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch review-candidate records via the worker's monkeypatchable lark_json."""
    command = [
        "base",
        "+record-list",
        *_base_client_base_args(config),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for field in CANDIDATE_FIELDS:
        command.extend(["--field-id", field])
    envelope = lark_json(config, *command)
    data = envelope.get("data", {})
    return _parse_record_rows(
        data.get("data", []),
        data.get("fields", CANDIDATE_FIELDS),
        data.get("record_id_list", []),
    )


def _connector_binary() -> list[str]:
    """Return the oks-connector CLI path (delegates to feishu_worker.source_router)."""
    return _source_router__connector_binary(ROOT)


# ── Claim-layer re-exports ──────────────────────────────────────────────────
# parse_base_datetime and is_candidate are pure functions imported directly
# from feishu_worker.claim — no wrapper needed.  The remaining claim functions
# have legacy wrappers that supply ROOT and inject monkeypatch-compatible
# callables (list_records, get_record, update_record, local_claim_lock).


@contextmanager
def local_claim_lock(config: WorkerConfig):
    """Acquire an exclusive file-based lease lock for the Base+table pair."""
    with _claim_local_claim_lock(config, root=ROOT):
        yield


def claim_next_record(config: WorkerConfig, limit: int = 100) -> tuple[dict[str, Any], str, str] | None:
    """Claim the first candidate record from the pending-rows list."""
    return _claim_claim_next_record(
        config,
        limit=limit,
        _list_fn=list_records,
        _update_fn=update_record,
        _lock_fn=local_claim_lock,
    )


def claim_record(config: WorkerConfig, record_id: str) -> tuple[dict[str, Any], str, str] | None:
    """Claim one explicitly selected Base record without touching other pending rows."""
    return _claim_claim_record(
        config,
        record_id,
        _get_fn=get_record,
        _update_fn=update_record,
        _lock_fn=local_claim_lock,
    )


def release_lease(config: WorkerConfig, record_id: str) -> None:
    """Release the lease on *record_id* by clearing owner and expiry fields."""
    _claim_release_lease(config, record_id, _update_fn=update_record)


def parse_candidate_document(text: str) -> tuple[dict[str, Any], str]:
    return _candidate_parse_candidate_document(text)


def render_candidate_document(metadata: dict[str, Any], body: str) -> str:
    return _candidate_render_candidate_document(metadata, body)


def candidate_state_path(record_id: str) -> Path:
    return _candidate_candidate_state_path(record_id, root=ROOT)


def load_candidate_state(record_id: str) -> dict[str, Any]:
    return _candidate_load_candidate_state(record_id, root=ROOT)


def candidate_review_fingerprint(fields: dict[str, Any]) -> str:
    return _candidate_candidate_review_fingerprint(fields)


def render_candidate_review_message(
    *,
    record_id: str,
    candidate_id: str,
    revision: int,
    metadata: dict[str, Any],
    body: str,
    fields: dict[str, Any],
) -> str:
    return _candidate_render_candidate_review_message(
        record_id=record_id,
        candidate_id=candidate_id,
        revision=revision,
        metadata=metadata,
        body=body,
        fields=fields,
    )


def send_candidate_review_notification(
    config: WorkerConfig,
    *,
    record_id: str,
    state: dict[str, Any],
    metadata: dict[str, Any],
    body: str,
    fields: dict[str, Any],
    root: Path = ROOT,
    _lark_fn: Any | None = None,
) -> dict[str, Any]:
    return _candidate_send_candidate_review_notification(
        config,
        record_id=record_id,
        state=state,
        metadata=metadata,
        body=body,
        fields=fields,
        root=root,
        _lark_fn=_lark_fn or lark_json,
    )


def parse_review_reply(content: str) -> tuple[str, str]:
    return _review_parse_review_reply(content)


def event_reviewed_at(value: object) -> str:
    return _review_event_reviewed_at(value)


def find_candidate_state_for_reply(
    event: dict[str, Any],
) -> tuple[Path, dict[str, Any]] | None:
    return _review_find_candidate_state_for_reply(event, root=ROOT)


def record_review_event(
    path: Path,
    state: dict[str, Any],
    event: dict[str, Any],
    *,
    action: str,
    comment: str,
) -> None:
    _review_record_review_event(path, state, event, action=action, comment=comment)


def read_review_record_after_write(
    config: WorkerConfig,
    record_id: str,
    expected_action: str,
) -> dict[str, Any]:
    return _review_read_review_record_after_write(
        config, record_id, expected_action, root=ROOT, _get_fn=get_record,
    )


def apply_review_reply_event(
    config: WorkerConfig,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Apply one direct reply to the exact Candidate notification it references."""
    return _review_apply_review_reply_event(
        config, event, root=ROOT,
        _update_fn=update_record, _get_fn=get_record,
        _review_candidate_fn=review_candidate,
    )


def raw_message(config: WorkerConfig, message_id: str) -> dict[str, Any]:
    return _review_raw_message(config, message_id, root=ROOT, _lark_fn=lark_json)


def decoded_raw_message_content(message: dict[str, Any]) -> str:
    return _review_decoded_raw_message_content(message)


def pending_review_states_in_chat(chat_id: str) -> list[tuple[Path, dict[str, Any]]]:
    return _review_pending_review_states_in_chat(chat_id, root=ROOT)


def review_states_for_prompt(
    chat_id: str,
    prompt_message_id: str,
) -> list[tuple[Path, dict[str, Any]]]:
    return _review_review_states_for_prompt(chat_id, prompt_message_id, root=ROOT)


def reconcile_historical_review_reply(
    config: WorkerConfig,
    *,
    prompt_message_id: str,
    reply_message_id: str,
) -> dict[str, Any]:
    """Recover a missed P2P review event without pretending chronology is a native reply link."""
    return _review_reconcile_historical_review_reply(
        config,
        prompt_message_id=prompt_message_id,
        reply_message_id=reply_message_id,
        root=ROOT,
        _raw_message_fn=raw_message,
        _apply_reply_fn=apply_review_reply_event,
    )


def apply_review_event_with_fallback(
    config: WorkerConfig,
    event: dict[str, Any],
) -> dict[str, Any]:
    return _review_apply_review_event_with_fallback(
        config, event, root=ROOT,
        _apply_reply_fn=apply_review_reply_event,
        _pending_fn=pending_review_states_in_chat,
        _reconcile_fn=reconcile_historical_review_reply,
    )


def consume_review_events(
    config: WorkerConfig,
    *,
    max_events: int,
    timeout: str,
) -> dict[str, Any]:
    return _review_consume_review_events(
        config, max_events=max_events, timeout=timeout, root=ROOT,
        _apply_event_fn=apply_review_event_with_fallback,
    )


def publish_candidate(
    config: WorkerConfig,
    record_id: str,
    candidate_file: Path,
) -> dict[str, Any]:
    return _candidate_publish_candidate(
        config,
        record_id,
        candidate_file,
        root=ROOT,
        _get_fn=get_record,
        _update_fn=update_record,
        _lark_fn=lark_json,
        _send_notification_fn=send_candidate_review_notification,
    )


def promote_candidate_document(
    candidate_path: Path,
    reviewed_body: str,
    review: dict[str, Any],
    *,
    root: Path = ROOT,
    knowledge_root: Path | None = None,
) -> Path:
    return _review_promote_candidate_document(
        candidate_path, reviewed_body, review,
        root=root, knowledge_root=knowledge_root,
    )


def review_candidate(config: WorkerConfig, record: dict[str, Any]) -> dict[str, Any]:
    return _review_review_candidate(
        config, record, root=ROOT,
        _update_fn=update_record, _promote_fn=promote_candidate_document,
    )


def process_next_review(config: WorkerConfig, limit: int = 100) -> dict[str, Any]:
    return _review_process_next_review(
        config, limit, root=ROOT,
        _list_fn=list_review_records, _update_fn=update_record,
    )


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


def complete_browser_snapshot(config: WorkerConfig, record_id: str, snapshot_dir: Path) -> dict[str, Any]:
    snapshot_dir = snapshot_dir.expanduser().resolve()
    html = snapshot_dir / "rendered.html"
    screenshot = snapshot_dir / "screenshot.png"
    snapshot_manifest = snapshot_dir / "snapshot.json"
    for required in (html, screenshot, snapshot_manifest):
        if not required.is_file():
            raise FileNotFoundError(required)
    snapshot = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
    records = list_records(config, 100)
    record = next((item for item in records if item["record_id"] == record_id), None)
    if record is None:
        raise RuntimeError(f"Base record not found in current table: {record_id}")
    fields = record["fields"]
    source_url = extract_url(fields.get("内容"))
    if not source_url:
        raise RuntimeError("Base record has no HTTP(S) URL")
    snapshot_url = str(snapshot.get("url") or "").split("#", 1)[0].rstrip("/")
    if snapshot_url != source_url.split("#", 1)[0].rstrip("/"):
        raise RuntimeError("browser snapshot URL does not match the Base record URL")

    run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    capture = capture_envelope(config, record_id, fields)
    capture["source_snapshot"] = {
        "final_url": str(snapshot["url"]),
        "content_type": "text/html",
        "size": html.stat().st_size,
        "sha256": sha256_file(html),
    }
    source_hash = envelope_content_hash(capture)
    capture["content_hash"] = source_hash
    capture["capture_id"] = f"feishu-{record_id}-{source_hash[:12]}"
    run = initial_run(run_id, capture, "web.browser-snapshot")
    run["recipe_version"] = "feishu-browser-snapshot-v0.1"
    run["modalities"]["text"].update({"status": "running", "capability": "web.browser-snapshot"})
    run_dir = ROOT / ".oks" / "runs" / run_id
    atomic_write_json(run_dir / "capture-envelope.json", capture)
    atomic_write_json(run_dir / "processing-run.json", run)
    update_record(
        config,
        record_id,
        {
            "运行状态": "已领取",
            "运行ID": run_id,
            "来源哈希": source_hash,
            "采集模式": "公开浏览器",
            "错误码": None,
            "错误说明": None,
            "重试": False,
        },
    )
    try:
        output = config.output_root / f"feishu-{record_id}-{source_hash[:10]}-browser"
        report = package_local_attachment(config, html, output)
        assets = output / "assets"
        derived = output / "derived"
        assets.mkdir(exist_ok=True)
        derived.mkdir(exist_ok=True)
        shutil.copy2(screenshot, assets / "browser-screenshot.png")
        shutil.copy2(snapshot_manifest, derived / "browser-snapshot.json")
        evidence_path = output / "evidence.jsonl"
        existing_evidence = [
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        existing_evidence.append(
            {
                "id": "browser-screenshot-0001",
                "kind": "browser_screenshot",
                "text": str(snapshot.get("title") or "Rendered browser snapshot"),
                "method": "browser.public",
                "locator": {"asset": "assets/browser-screenshot.png", "url": snapshot["url"]},
            }
        )
        atomic_write_text(
            evidence_path,
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing_evidence),
        )
        quality_path = output / "quality-report.json"
        quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
        quality_report["evidence_count"] = len(existing_evidence)
        quality_report.setdefault("coverage_checks", {})["browser_screenshot"] = {
            "expected": 1,
            "observed": 1,
            "status": "passed",
        }
        atomic_write_json(quality_path, quality_report)
        metadata_path = output / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["capture_envelope"] = capture
        metadata["browser_snapshot"] = {
            "manifest": "derived/browser-snapshot.json",
            "screenshot": "assets/browser-screenshot.png",
        }
        atomic_write_json(metadata_path, metadata)
        quality = report.get("processing_status") or metadata.get("processing_status") or "partial"
        run["modalities"]["text"].update({"status": "succeeded", "evidence_count": len(existing_evidence)})
        run["outputs"] = [{"dataset_id": f"bundle:{capture['capture_id']}", "uri": str(output), "kind": "bundle", "sha256": None}]
        finish_run(run, "complete" if quality == "complete" else "partial")
        atomic_write_json(run_dir / "processing-run.json", run)
        finalize_raw_v2(config, output, run_dir / "capture-envelope.json", run_dir / "processing-run.json", html)
        update_record(
            config,
            record_id,
            {
                "运行状态": "Raw就绪",
                "采集模式": "公开浏览器",
                "Raw Bundle": str(output),
                "质量状态": quality,
                "错误码": None,
                "错误说明": None,
                "总结": f"公开 JavaScript 页面已从受控浏览器快照生成 Raw Bundle v0.2；质量状态={quality}。",
            },
        )
        return run
    except Exception as error:
        failure = {"code": "BROWSER_SNAPSHOT_PROCESSING_FAILED", "message": str(error)}
        run["outputs"] = []
        finish_run(run, "failed", disposition="retryable", error=failure)
        atomic_write_json(run_dir / "processing-run.json", run)
        update_record(
            config,
            record_id,
            {
                "运行状态": "可重试失败",
                "采集模式": "公开浏览器",
                "错误码": failure["code"],
                "错误说明": _redact_error_text(failure["message"])[:500],
                "质量状态": "failed",
                "Raw Bundle": None,
            },
        )
        return run


def process_record(
    config: WorkerConfig,
    record: dict[str, Any],
    *,
    claimed_run_id: str | None = None,
) -> dict[str, Any]:
    """Process one claimed Base record through the full Raw pipeline (delegates to feishu_worker.pipeline).

    Explicitly passes the worker's own callables so that monkeypatched
    attributes (update_record, probe_source, package_routed_source, etc.)
    remain effective in tests -- the pipeline uses module-level defaults
    only when no callback is supplied.
    """
    return _pipeline_process_record(
        config,
        record,
        claimed_run_id=claimed_run_id,
        _update_record=update_record,
        _download_attachments=download_attachments,
        _package_local_attachment=package_local_attachment,
        _finalize_raw_v2=finalize_raw_v2,
        _probe_source=probe_source,
        _download_public_source=download_public_source,
        _package_routed_source=package_routed_source,
        _package_public_web=package_public_web,
    )


def parse_args() -> argparse.Namespace:
    """Re-export of feishu_worker.cli.parse_args for backward compatibility."""
    from feishu_worker.cli import parse_args as _parse_args
    return _parse_args()


def main() -> int:
    # Windows PowerShell commonly exposes a GBK console. Raw extraction output
    # can contain arbitrary Unicode, so a successful run must not fail while
    # serializing its final machine-readable result.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    config = load_config(args)
    if args.command == "pending":
        records = list_records(config, args.limit)
        result = {
            "count": len(records),
            "records": [
                {
                    "record_id": r.get("record_id", ""),
                    "content": r.get("内容", ""),
                    "thought": r.get("思考", ""),
                    "status": r.get("运行状态", ""),
                    "created": r.get("创建时间", ""),
                    "run_id": r.get("运行ID", ""),
                    "attachments": r.get("附件", ""),
                    "wiki_status": r.get("Wiki状态", ""),
                    "capture_mode": r.get("采集模式", ""),
                }
                for r in records
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "enqueue":
        fields: dict[str, Any] = {
            "内容": args.content,
            "思考": args.thought,
            "状态": "未处理",
            "运行状态": "待处理",
            "Wiki状态": "none",
            "重试": False,
        }
        if args.rating:
            fields["评级"] = normalize_rating(args.rating)
        created = create_record(config, fields)
        print(json.dumps({
            "record_id": created_record_id(created),
            "response": created,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "complete-browser":
        result = complete_browser_snapshot(config, args.record_id, args.snapshot_dir)
        print(json.dumps({"processed": True, "run": result}, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"complete", "partial"} else 2
    if args.command == "publish-candidate":
        result = publish_candidate(config, args.record_id, args.candidate_file)
        print(json.dumps({"published": True, "candidate": result}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-once":
        result = process_next_review(config, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "listen-reviews":
        result = consume_review_events(
            config,
            max_events=args.max_events,
            timeout=args.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reconcile-review":
        result = reconcile_historical_review_reply(
            config,
            prompt_message_id=args.prompt_message_id,
            reply_message_id=args.reply_message_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run-record":
        claimed = claim_record(config, args.record_id)
    else:
        claimed = claim_next_record(config, args.limit)
    if claimed is None:
        reason = "record_not_claimable" if args.command == "run-record" else "no_pending_records"
        print(json.dumps({"processed": False, "reason": reason}, ensure_ascii=False))
        return 0
    record, run_id, _owner = claimed
    try:
        result = process_record(config, record, claimed_run_id=run_id)
    finally:
        release_lease(config, record["record_id"])
    print(json.dumps({"processed": True, "run": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
