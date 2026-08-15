"""Feishu worker Base protocol/client operations -- lark_json, record CRUD, retry helpers.

Extracted from feishu_base_worker.py (Round 3 Phase 2).  TRUE leaf module:
imports only from feishu_worker.config, feishu_worker.io_utils, and stdlib.
Never imports feishu_base_worker.  Callers must supply *root* explicitly so
this module has zero dependency on the ROOT constant in the main worker.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from feishu_worker.config import WorkerConfig
from feishu_worker.io_utils import _redact_error_text
from feishu_worker.states import CLAIMABLE_STATUSES

# Signature of a lark_json-compatible callable, for dependency injection.
LarkFn = Callable[..., dict[str, Any]]

# ── Retry constants ────────────────────────────────────────────────────
RETRYABLE_CODES = {"RATE_LIMITED", "UPSTREAM_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"}
_FATAL_LARK_CODES = {
    "AUTH_FAILED",
    "AUTH_REQUIRED",
    "ACCESS_DENIED",
    "PERMISSION_DENIED",
    "INVALID_ARGUMENT",
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "CHALLENGE_REQUIRED",
}
_LARK_MAX_RETRIES = 3
_LARK_BASE_DELAY = 1.0
_LARK_SUBPROCESS_TIMEOUT = 30.0


# ── Error-code helpers ─────────────────────────────────────────────────


def _extract_lark_error_code(value: dict[str, Any]) -> str:
    error = value.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        if code:
            return str(code)
    code = value.get("code")
    return str(code) if code else ""


def _is_retryable_lark_error(value: dict[str, Any]) -> bool:
    code = _extract_lark_error_code(value)
    return code in RETRYABLE_CODES


def _is_fatal_lark_error(value: dict[str, Any]) -> bool:
    code = _extract_lark_error_code(value)
    return code in _FATAL_LARK_CODES


# ── Core protocol ──────────────────────────────────────────────────────


def lark_json(config: WorkerConfig, *arguments: str, root: Path) -> dict[str, Any]:
    """Run a lark-cli command and return its parsed JSON response.

    Retries only on structured retryable error codes, TimeoutExpired, and
    narrowly-intended transient OSError subclasses.  Malformed/non-JSON
    output and non-object JSON values raise immediately without retry.
    """
    command = [str(config.lark_cli), *arguments]
    last_error: Exception | None = None

    for attempt in range(1 + _LARK_MAX_RETRIES):
        try:
            result = subprocess.run(
                command,
                cwd=root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=_LARK_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = exc
            if attempt < _LARK_MAX_RETRIES:
                time.sleep(_LARK_BASE_DELAY * (2 ** attempt))
                continue
            raise RuntimeError(
                f"lark-cli timed out after {_LARK_MAX_RETRIES + 1} attempts: "
                f"{' '.join(arguments[:3])}..."
            ) from exc
        except OSError as exc:
            # Only retry narrowly-intended transient OSError subclasses.
            if isinstance(exc, (ConnectionRefusedError, ConnectionResetError, BrokenPipeError)):
                last_error = exc
                if attempt < _LARK_MAX_RETRIES:
                    time.sleep(_LARK_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(
                    f"lark-cli subprocess failed after {_LARK_MAX_RETRIES + 1} attempts: "
                    f"{' '.join(arguments[:3])}...: {exc}"
                ) from exc
            raise

        text = result.stdout.strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            if result.returncode:
                # Some lark-cli validation failures are written only to stderr.
                # Preserve the actionable server message without ever echoing the
                # Base credential supplied in the command arguments.
                detail = result.stderr.strip() or text or "(no diagnostic output)"
                detail = _redact_error_text(detail).replace(config.base_token, "***")
                raise RuntimeError(
                    f"lark-cli exited {result.returncode}: {detail[:400]}"
                ) from exc
            # Malformed/non-JSON output -- do NOT retry.
            raise RuntimeError(
                f"command returned non-JSON output: {text[:400]}"
            ) from exc

        if not isinstance(value, dict):
            raise RuntimeError("command returned a non-object JSON value")

        if value.get("ok") is True:
            return value

        if _is_fatal_lark_error(value):
            raise RuntimeError(
                f"lark-cli operation failed: {json.dumps(value, ensure_ascii=False)}"
            )

        if _is_retryable_lark_error(value):
            last_error = RuntimeError(
                f"lark-cli transient error: {json.dumps(value, ensure_ascii=False)}"
            )
            if attempt < _LARK_MAX_RETRIES:
                time.sleep(_LARK_BASE_DELAY * (2 ** attempt))
                continue
            raise RuntimeError(
                f"lark-cli failed after {_LARK_MAX_RETRIES + 1} attempts: "
                f"{' '.join(arguments[:3])}..."
            ) from last_error

        raise RuntimeError(
            f"lark-cli operation failed: {json.dumps(value, ensure_ascii=False)}"
        )

    raise RuntimeError(
        f"lark-cli failed after {_LARK_MAX_RETRIES + 1} attempts: "
        f"{' '.join(arguments[:3])}..."
    ) from last_error


def parse_json_output(
    result: subprocess.CompletedProcess[str],
    *,
    allow_codes: set[int] = {0},
) -> dict[str, Any]:
    if result.returncode not in allow_codes:
        raise RuntimeError(
            f"command failed ({result.returncode}): {(result.stderr or result.stdout).strip()}"
        )
    text = result.stdout.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"command returned non-JSON output: {text[:400]}") from error
    if not isinstance(value, dict):
        raise RuntimeError("command returned a non-object JSON value")
    return value


# ── Base argument helpers ──────────────────────────────────────────────


def base_args(config: WorkerConfig) -> list[str]:
    return [
        "--base-token",
        config.base_token,
        "--table-id",
        config.table_id,
        "--as",
        config.identity,
    ]


# ── Record CRUD ────────────────────────────────────────────────────────


def _parse_record_rows(
    rows: list[Any],
    fields: list[str],
    record_ids: list[str],
) -> list[dict[str, Any]]:
    """Normalize row-list + record-id-list responses into uniform record dicts."""
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        record_id = record_ids[index] if index < len(record_ids) else None
        if isinstance(row, list):
            values = dict(zip(fields, row))
        elif isinstance(row, dict):
            record_id = row.get("record_id") or row.get("id") or record_id
            values = row.get("fields", row)
        else:
            continue
        if record_id:
            records.append({"record_id": record_id, "fields": values})
    return records


def update_record(
    config: WorkerConfig,
    record_id: str,
    patch: dict[str, Any],
    *,
    root: Path,
    _lark_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _lark = _lark_fn if _lark_fn is not None else lark_json
    return _lark(
        config,
        "base",
        "+record-upsert",
        *base_args(config),
        "--record-id",
        record_id,
        "--json",
        json.dumps(patch, ensure_ascii=False, separators=(",", ":")),
        root=root,
    )


def create_record(
    config: WorkerConfig,
    fields: dict[str, Any],
    *,
    root: Path,
    _lark_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _lark = _lark_fn if _lark_fn is not None else lark_json
    return _lark(
        config,
        "base",
        "+record-upsert",
        *base_args(config),
        "--json",
        json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
        root=root,
    )


def list_records(
    config: WorkerConfig,
    limit: int = 100,
    *,
    root: Path,
    projection: list[str],
    _lark_fn: LarkFn | None = None,
) -> list[dict[str, Any]]:
    _lark = _lark_fn if _lark_fn is not None else lark_json
    command = [
        "base",
        "+record-list",
        *base_args(config),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for field in projection:
        command.extend(["--field-id", field])
    # Fetch every claimable status, not just 待处理: is_candidate() also accepts
    # retry-flagged records and 已领取 records whose lease expired. Filtering to
    # 待处理 here would make retries and crash recovery unreachable.
    command.extend([
        "--filter-json",
        json.dumps(
            {"logic": "and", "conditions": [["运行状态", "intersects", list(CLAIMABLE_STATUSES)]]},
            ensure_ascii=False,
        ),
    ])
    envelope = _lark(config, *command, root=root)
    data = envelope.get("data", {})
    fields = data.get("fields", projection)
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    return _parse_record_rows(rows, fields, record_ids)


def get_record(
    config: WorkerConfig,
    record_id: str,
    projection: list[str],
    *,
    root: Path,
    _lark_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _lark = _lark_fn if _lark_fn is not None else lark_json
    command = [
        "base",
        "+record-get",
        *base_args(config),
        "--record-id",
        record_id,
        "--format",
        "json",
    ]
    for field in projection:
        command.extend(["--field-id", field])
    envelope = _lark(config, *command, root=root)
    data = envelope.get("data", {})
    rows = data.get("data", [])
    fields = data.get("fields", projection)
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


def list_review_records(
    config: WorkerConfig,
    limit: int = 100,
    *,
    root: Path,
    projection: list[str],
    _lark_fn: LarkFn | None = None,
) -> list[dict[str, Any]]:
    _lark = _lark_fn if _lark_fn is not None else lark_json
    command = [
        "base",
        "+record-list",
        *base_args(config),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for field in projection:
        command.extend(["--field-id", field])
    envelope = _lark(config, *command, root=root)
    data = envelope.get("data", {})
    fields = data.get("fields", projection)
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    return _parse_record_rows(rows, fields, record_ids)
