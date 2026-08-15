"""Feishu worker notification module — render/parse review messages, send IM notifications.

Extracted from feishu_worker/candidate.py (Round 3 Phase 6).  Imports only from
feishu_worker.* leaf modules (config, io_utils, base_client) and stdlib.
Never imports feishu_base_worker.  Callers must supply *root* explicitly so
this module has zero dependency on the ROOT constant in the main worker.
"""

from __future__ import annotations

import functools
import hashlib
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
    idempotency_key = hashlib.sha256(
        f"{state['candidate_id']}:{state['revision']}:{state['candidate_sha256']}".encode("utf-8")
    ).hexdigest()[:50]
    _lark = _lark_fn if _lark_fn is not None else functools.partial(_base_lark_json, root=root)
    try:
        envelope = _lark(
            config,
            "im",
            "+messages-send",
            "--user-id",
            recipient,
            "--markdown",
            message,
            "--idempotency-key",
            idempotency_key,
            "--as",
            config.review_message_identity,
            "--format",
            "json",
        )
    except RuntimeError as error:
        return {"status": "failed", "error": str(error)[:500]}
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    return {
        "status": "sent",
        "message_id": data.get("message_id") or envelope.get("message_id"),
        "chat_id": data.get("chat_id") or envelope.get("chat_id"),
        "identity": config.review_message_identity,
        "recipient": recipient,
        "idempotency_key": idempotency_key,
    }
