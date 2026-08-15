"""Feishu worker claim layer — record leasing, candidate detection, datetime parsing.

Extracted from feishu_base_worker.py (Round 3 Phase 3A).  TRUE leaf module:
imports only from feishu_worker.config, feishu_worker.io_utils, and stdlib.
Never imports feishu_base_worker.  The original module provides legacy wrappers
that supply ROOT and inject monkeypatch-compatible callables.

All internal comparisons and lease/run-id timestamps are aware UTC.  Old naive
lease reads are accepted only via the explicit ``naive_migration="assume_utc"``
opt-in on ``parse_base_datetime``; the default ``"reject"`` returns None for
naive timestamps.  Callers that still store or read naive leases must migrate.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import os
import subprocess  # fresh import — available for future phases
from pathlib import Path
from typing import Any, Callable
import uuid

from feishu_worker.config import WorkerConfig
from feishu_worker.io_utils import scalar_cell

# ── Type aliases for dependency injection ──────────────────────────────────
# Signatures are deliberately loose (Callable[..., …]) so callers can inject
# legacy wrappers, base_client functions, or test mocks without protocol fuss.

ClaimListFn = Callable[..., list[dict[str, Any]]]
ClaimGetFn = Callable[..., dict[str, Any]]
ClaimUpdateFn = Callable[..., dict[str, Any]]
ClaimLockFn = Callable[..., Any]  # context-manager callable

# ── Fields required for claim/candidate detection ──────────────────────────
# Mirrors CAPTURE_FIELDS in feishu_base_worker.py so the claim layer can
# request the right projection without importing the orchestrator module.

_CLAIM_PROJECTION = [
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
]


# ── Datetime helpers ───────────────────────────────────────────────────────


def parse_base_datetime(
    value: object,
    *,
    naive_migration: str = "reject",
) -> datetime | None:
    """Parse a Base datetime cell into an aware UTC datetime.

    ``naive_migration`` controls how naive (tz-less) timestamps are handled:
    ``"reject"`` returns ``None``; ``"assume_utc"`` treats them as UTC.

    This is the canonical implementation.  The legacy ``feishu_base_worker``
    module re-exports it directly (no wrapper needed — pure function, no DI).
    """
    value = scalar_cell(value)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if naive_migration == "reject":
            return None
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── Candidate detection ────────────────────────────────────────────────────


def is_candidate(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Return True when *record* is eligible for claiming.

    A record is a candidate when:
    * Status is ``None``, ``""``, or ``"待处理"``; or
    * ``"重试"`` is ``True``; or
    * Status is ``"已领取"`` AND the lease (``"租约到期"``) has expired.

    Lease expiry is always evaluated against aware UTC.  Naive lease values
    stored in Base are accepted via ``naive_migration="assume_utc"`` (the
    ``parse_base_datetime`` default is ``"reject"``, so callers must opt in).
    """
    fields = record["fields"]
    status = scalar_cell(fields.get("运行状态"))
    retry = fields.get("重试") is True
    expired = status == "已领取" and (
        (expires := parse_base_datetime(fields.get("租约到期"), naive_migration="assume_utc")) is not None
        and expires <= (now or datetime.now(timezone.utc))
    )
    return status in (None, "", "待处理") or retry or expired


# ── Local advisory lock ────────────────────────────────────────────────────


@contextmanager
def local_claim_lock(config: WorkerConfig, *, root: Path):
    """Acquire an exclusive file-based lease lock for the Base+table pair.

    This is a **single-host serialization** primitive, not a distributed
    coordination lock.  The lock scope is the local filesystem only:

    * On a single machine, only one worker process per (base_token, table_id)
      pair can hold the lock at a time.
    * The lock does NOT span hosts, network shares, or containers.  Running
      workers on multiple machines against the same Base table requires an
      external coordination mechanism (e.g. a database lease table, Redis
      Redlock, or a Feishu Base record-level compare-and-swap).

    Implementation:  Uses ``msvcrt.locking`` on Windows, ``fcntl.flock`` on
    POSIX.  Both provide advisory exclusive locking scoped to the local kernel.

    *root* is the repository root (analogous to the ROOT constant in
    feishu_base_worker).  Legacy callers supply it via a one-argument wrapper.
    """
    lock_dir = root / ".oks" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        f"{config.base_token}/{config.table_id}".encode("utf-8")
    ).hexdigest()[:16]
    lock_path = lock_dir / f"feishu-base-{key}.lock"
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# ── Claim / release operations ─────────────────────────────────────────────


def claim_next_record(
    config: WorkerConfig,
    *,
    limit: int = 100,
    _list_fn: ClaimListFn,
    _update_fn: ClaimUpdateFn,
    _lock_fn: ClaimLockFn,
) -> tuple[dict[str, Any], str, str] | None:
    """Claim the first candidate record from the pending-rows list.

    Acquires the local claim lock, fetches pending records via *_list_fn*,
    filters through :func:`is_candidate`, picks the first match, stamps the
    lease fields via *_update_fn*, and returns ``(record, run_id, owner)``.

    Returns ``None`` when no candidate is found.

    All injected callables receive the same single-argument signatures as the
    legacy ``feishu_base_worker`` wrappers so monkeypatching continues to work.
    """
    with _lock_fn(config):
        all_records = _list_fn(config, limit)
        candidates = [record for record in all_records if is_candidate(record)]
        if not candidates:
            return None
        record = candidates[0]
        run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        owner = f"{os.environ.get('COMPUTERNAME', 'local')}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=config.lease_seconds)
        _update_fn(
            config,
            record["record_id"],
            {
                "运行状态": "已领取",
                "运行ID": run_id,
                "租约所有者": owner,
                "租约到期": expires.strftime("%Y-%m-%d %H:%M:%S+00:00"),
                "重试": False,
            },
        )
        return record, run_id, owner


def claim_record(
    config: WorkerConfig,
    record_id: str,
    *,
    _get_fn: ClaimGetFn,
    _update_fn: ClaimUpdateFn,
    _lock_fn: ClaimLockFn,
) -> tuple[dict[str, Any], str, str] | None:
    """Claim one explicitly selected Base record without touching other pending rows.

    Acquires the local claim lock, fetches the specific record via *_get_fn*
    (with claim-relevant projection), checks :func:`is_candidate`, stamps the
    lease fields via *_update_fn*, and returns ``(record, run_id, owner)``.

    Returns ``None`` when the explicitly selected record is not a candidate.
    """
    with _lock_fn(config):
        record = _get_fn(config, record_id, _CLAIM_PROJECTION)
        if not is_candidate(record):
            return None
        run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        owner = f"{os.environ.get('COMPUTERNAME', 'local')}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=config.lease_seconds)
        _update_fn(
            config,
            record_id,
            {
                "运行状态": "已领取",
                "运行ID": run_id,
                "租约所有者": owner,
                "租约到期": expires.strftime("%Y-%m-%d %H:%M:%S+00:00"),
                "重试": False,
            },
        )
        return record, run_id, owner


def release_lease(
    config: WorkerConfig,
    record_id: str,
    *,
    _update_fn: ClaimUpdateFn,
) -> None:
    """Release the lease on *record_id* by clearing owner and expiry fields."""
    _update_fn(config, record_id, {"租约所有者": None, "租约到期": None})
