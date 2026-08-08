"""Feishu worker notification module — render/parse review messages, send IM notifications.

Extracted from feishu_worker/candidate.py (Round 3 Phase 6).  Imports only from
feishu_worker.* leaf modules (config, io_utils, base_client) and stdlib.
Never imports feishu_base_worker.  Callers must supply *root* explicitly so
this module has zero dependency on the ROOT constant in the main worker.
"""

from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Any

from feishu_worker.config import WorkerConfig
from feishu_worker.io_utils import scalar_cell
from feishu_worker.base_client import (
    LarkFn,
    lark_json as _base_lark_json,
)


def render_candidate_review_message(
    *,
    record_id: str,
    candidate_id: str,
    revision: int,
    metadata: dict[str, Any],
    body: str,
    fields: dict[str, Any],
) -> str:
    """Render Agent-authored review context without inventing new claims."""
    summary = str(metadata.get("review_summary") or "").strip()
    if not summary:
        summary = body.strip()[:600]
        if len(body.strip()) > 600:
            summary += "\u2026"
    raw_questions = metadata.get("review_questions") or []
    if isinstance(raw_questions, str):
        questions = [raw_questions.strip()] if raw_questions.strip() else []
    elif isinstance(raw_questions, list):
        questions = [str(item).strip() for item in raw_questions if str(item).strip()]
    else:
        questions = []
    question_lines = "\n".join(f"- {item}" for item in questions[:3])
    if not question_lines:
        question_lines = "- 这条知识是否值得进入你的个人知识库？"
    source = str(scalar_cell(fields.get("内容")) or "").strip()
    user_note = str(fields.get("思考") or "").strip()
    context_lines = []
    if source:
        context_lines.append(f"**来源：** {source}")
    if user_note:
        context_lines.append(f"**你的原始思考：** {user_note}")
    context = "\n\n".join(context_lines)
    if context:
        context += "\n\n"
    return (
        "## 知识候选待审核\n\n"
        f"**主题：** {metadata.get('title', candidate_id)}\n\n"
        f"{context}"
        f"**Agent 总结：**\n\n{summary}\n\n"
        f"**需要你判断：**\n\n{question_lines}\n\n"
        "请直接回复以下任一动作：\n\n"
        "- `accept`：接受；可附一句理由\n"
        "- `edit`：说明需要修改什么\n"
        "- `reject`：说明拒绝原因\n"
        "- `defer`：暂缓处理\n\n"
        f"候选标识：`{candidate_id}` · revision `{revision}` · Base `{record_id}`"
    )


def send_candidate_review_notification(
    config: WorkerConfig,
    *,
    record_id: str,
    state: dict[str, Any],
    metadata: dict[str, Any],
    body: str,
    fields: dict[str, Any],
    root: Path,
    _lark_fn: LarkFn | None = None,
) -> dict[str, Any]:
    recipient = config.review_recipient_user_id
    if not recipient:
        return {"status": "skipped", "reason": "review_recipient_not_configured"}
    message = render_candidate_review_message(
        record_id=record_id,
        candidate_id=str(state["candidate_id"]),
        revision=int(state["revision"]),
        metadata=metadata,
        body=body,
        fields=fields,
    )
    if "????" in message:
        return {
            "status": "failed",
            "reason": "message_content_corrupt_before_send",
            "identity": config.review_message_identity,
            "recipient": recipient,
        }
    idempotency_key = hashlib.sha256(
        f"{state['candidate_id']}:{state['revision']}:{state['candidate_sha256']}".encode("utf-8")
    ).hexdigest()[:50]
    post_content = json.dumps(
        {"zh_cn": {"content": [[{"tag": "md", "text": message}]]}},
        # Keep argv ASCII-only so Windows npm/.cmd launchers cannot corrupt
        # Chinese text before Node parses the JSON payload.
        ensure_ascii=True,
        separators=(",", ":"),
    )
    _lark = _lark_fn if _lark_fn is not None else functools.partial(_base_lark_json, root=root)
    try:
        envelope = _lark(
            config,
            "im",
            "+messages-send",
            "--user-id",
            recipient,
            "--as",
            config.review_message_identity,
            "--msg-type",
            "post",
            "--content",
            post_content,
            "--idempotency-key",
            idempotency_key,
            "--format",
            "json",
        )
    except RuntimeError as error:
        return {"status": "failed", "error": str(error)[:500]}
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    message_id = data.get("message_id") or envelope.get("message_id")
    chat_id = data.get("chat_id") or envelope.get("chat_id")
    actual_identity = str(envelope.get("identity") or "").strip()
    if actual_identity and actual_identity != config.review_message_identity:
        return {
            "status": "failed",
            "reason": "message_identity_mismatch",
            "message_id": message_id,
            "chat_id": chat_id,
            "identity": actual_identity,
            "requested_identity": config.review_message_identity,
            "recipient": recipient,
            "idempotency_key": idempotency_key,
        }
    if not message_id:
        return {
            "status": "failed",
            "reason": "message_id_missing",
            "identity": actual_identity or config.review_message_identity,
            "recipient": recipient,
            "idempotency_key": idempotency_key,
        }
    try:
        verification = _lark(
            config,
            "im",
            "+messages-mget",
            "--message-ids",
            str(message_id),
            "--as",
            config.review_message_identity,
            "--no-reactions",
            "--format",
            "json",
        )
    except RuntimeError as error:
        return {
            "status": "failed",
            "reason": "message_verification_failed",
            "message_id": message_id,
            "chat_id": chat_id,
            "identity": actual_identity or config.review_message_identity,
            "recipient": recipient,
            "idempotency_key": idempotency_key,
            "error": str(error)[:500],
        }
    verification_data = (
        verification.get("data")
        if isinstance(verification.get("data"), dict)
        else {}
    )
    messages = (
        verification_data.get("messages")
        if isinstance(verification_data.get("messages"), list)
        else []
    )
    verified_message = next(
        (
            item
            for item in messages
            if isinstance(item, dict) and item.get("message_id") == message_id
        ),
        None,
    )
    sender = (
        verified_message.get("sender")
        if isinstance(verified_message, dict)
        and isinstance(verified_message.get("sender"), dict)
        else {}
    )
    sender_type = str(sender.get("sender_type") or "").strip()
    verified_content = (
        str(verified_message.get("content") or "")
        if isinstance(verified_message, dict)
        else ""
    )
    expected_sender_types = (
        {"app", "bot"}
        if config.review_message_identity == "bot"
        else {"user"}
    )
    verified_chat_id = (
        verified_message.get("chat_id")
        if isinstance(verified_message, dict)
        else None
    )
    if (
        verified_message is None
        or sender_type not in expected_sender_types
        or (chat_id and verified_chat_id != chat_id)
    ):
        return {
            "status": "failed",
            "reason": "message_delivery_mismatch",
            "message_id": message_id,
            "chat_id": chat_id,
            "identity": actual_identity or config.review_message_identity,
            "sender_type": sender_type or None,
            "recipient": recipient,
            "idempotency_key": idempotency_key,
        }
    if verified_content != message:
        return {
            "status": "failed",
            "reason": "message_content_mismatch",
            "message_id": message_id,
            "chat_id": chat_id,
            "identity": actual_identity or config.review_message_identity,
            "sender_type": sender_type,
            "recipient": recipient,
            "idempotency_key": idempotency_key,
        }
    return {
        "status": "sent",
        "message_id": message_id,
        "chat_id": chat_id,
        "identity": actual_identity or config.review_message_identity,
        "sender_type": sender_type,
        "delivery_verified": True,
        "content_verified": True,
        "recipient": recipient,
        "idempotency_key": idempotency_key,
    }
