"""Feishu worker capture layer — envelope, URL/attachment normalization, hashing.

Extracted from feishu_base_worker.py (Round 3 Phase 4).  TRUE leaf module:
imports only from feishu_worker.config, feishu_worker.io_utils, and stdlib.
Never imports feishu_base_worker.  The original module provides legacy wrappers
that supply ROOT and inject monkeypatch-compatible callables.

All capture-envelope v0.2 field names and values are preserved byte-for-byte
as established by the existing contract tests.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess  # fresh import — available for future phases
from typing import Any

from feishu_worker.config import WorkerConfig
from feishu_worker.io_utils import utc_now

URL_RE = re.compile(r"https?://[^\s<>\]\[)]+", re.IGNORECASE)


def extract_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = URL_RE.search(value)
    return match.group(0).rstrip(".,;，。；") if match else None


def normalize_attachments(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        token = item.get("file_token") or item.get("token") or item.get("id")
        name = item.get("name") or item.get("file_name") or str(token or "attachment")
        attachments.append(
            {
                "source_token": str(token or name),
                "name": str(name),
                "size": int(item.get("size") or 0),
                "mime_type": item.get("mime_type") or item.get("type"),
                "sha256": item.get("sha256"),
                "source_uri": item.get("url") or item.get("tmp_url"),
            }
        )
    return sorted(attachments, key=lambda item: (item["source_token"], item["name"]))


def capture_user_note(fields: dict[str, Any]) -> str | None:
    thought = str(fields.get("思考") or "").strip()
    question = str(
        fields.get("重点问题（可选）")
        or fields.get("希望解决的问题")
        or ""
    ).strip()
    parts = []
    if thought:
        parts.append(thought)
    if question:
        parts.append(f"重点问题：{question}")
    return "\n\n".join(parts) or None


def capture_content_hash(fields: dict[str, Any]) -> str:
    canonical = {
        "source_type": "feishu_base",
        "source_uri": extract_url(fields.get("内容")),
        "content": fields.get("内容"),
        "user_note": capture_user_note(fields),
        "attachments": normalize_attachments(fields.get("附件")),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def envelope_content_hash(capture: dict[str, Any]) -> str:
    canonical = {
        "source_type": capture["source_type"],
        "source_uri": extract_url(capture.get("content")),
        "content": capture.get("content"),
        "user_note": capture.get("user_note"),
        "attachments": capture.get("attachments", []),
        "source_snapshot": capture.get("source_snapshot"),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_envelope(config: WorkerConfig, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    content_hash = capture_content_hash(fields)
    return {
        "schema_version": "oks-capture-envelope/v0.2",
        "capture_id": f"feishu-{record_id}-{content_hash[:12]}",
        "capture_revision": 1,
        "source_type": "feishu_base",
        "source_uri": f"feishu-base://{config.table_id}/{record_id}",
        "captured_at": utc_now(),
        "submitted_by": None,
        "user_note": capture_user_note(fields),
        "content": fields.get("内容"),
        "content_hash": content_hash,
        "hash_algorithm": "sha256-canonical-json-v1",
        "source_record": {
            "base_token_hash": hashlib.sha256(config.base_token.encode("utf-8")).hexdigest()[:12],
            "table_id": config.table_id,
            "record_id": record_id,
            "revision": None,
        },
        "attachments": normalize_attachments(fields.get("附件")),
        "capture_adapter": {"name": "feishu.base", "version": "0.1.0"},
    }
