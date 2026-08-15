"""Feishu worker review-events module — review state machine, event extraction,
reply reconciliation, and event consumption.

Extracted from feishu_base_worker.py (Round 3 Phase 7).  Imports only from
feishu_worker.* leaf modules (config, io_utils, base_client, candidate) and
stdlib.  Never imports feishu_base_worker.  Callers must supply *root*
explicitly so this module has zero dependency on the ROOT constant in the
main worker.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from feishu_worker.base_client import (
    LarkFn,
    _parse_record_rows,
    base_args,
    get_record as _base_get_record,
    lark_json as _base_lark_json,
    update_record as _base_update_record,
)
from feishu_worker.candidate import (
    CANDIDATE_FIELDS,
    candidate_review_fingerprint,
    candidate_state_path,
    load_candidate_state,
    parse_candidate_document,
    render_candidate_document,
)
from feishu_worker.config import WorkerConfig, configured_knowledge_root
from feishu_worker.io_utils import (
    atomic_write_json,
    atomic_write_text,
    scalar_cell,
)

# ── Review constants ─────────────────────────────────────────────────────
REVIEW_ACTIONS = {"accept", "edit", "reject", "defer"}
REVIEW_ACTION_ALIASES = {
    "接受": "accept",
    "通过": "accept",
    "修改": "edit",
    "拒绝": "reject",
    "暂缓": "defer",
}
REVIEW_ACTION_RE = re.compile(
    r"(?<![A-Za-z\u4e00-\u9fff])(accept|edit|reject|defer|接受|通过|修改|拒绝|暂缓)(?![A-Za-z\u4e00-\u9fff])",
    re.IGNORECASE,
)


# ── Pure reply parsing / formatting ──────────────────────────────────────


def parse_review_reply(content: str) -> tuple[str, str]:
    """Extract one explicit review action and preserve the user's explanation."""
    text = str(content or "").strip()
    matches = list(REVIEW_ACTION_RE.finditer(text))
    actions = {
        REVIEW_ACTION_ALIASES.get(match.group(1), match.group(1).lower())
        for match in matches
    }
    if not matches:
        raise ValueError("review reply must contain accept, edit, reject, or defer")
    if len(actions) != 1:
        raise ValueError("review reply contains conflicting actions")
    action = next(iter(actions))
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor:match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    comment = " ".join(piece.strip() for piece in pieces if piece.strip())
    comment = comment.strip("`*_# \\t\\r\\n:：,，;；。.!！?-—")
    return action, comment


def event_reviewed_at(value: object) -> str:
    try:
        milliseconds = int(str(value))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def decoded_raw_message_content(message: dict[str, Any]) -> str:
    body = message.get("body") if isinstance(message.get("body"), dict) else {}
    raw = body.get("content")
    if not isinstance(raw, str):
        return ""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    return str(value)


# ── Candidate state helpers ──────────────────────────────────────────────


def find_candidate_state_for_reply(
    event: dict[str, Any],
    *,
    root: Path,
) -> tuple[Path, dict[str, Any]] | None:
    parent_ids = {
        str(value)
        for value in (event.get("reply_to"), event.get("root_id"))
        if str(value or "").strip()
    }
    if not parent_ids:
        return None
    state_dir = root / ".oks" / "candidates"
    for path in sorted(state_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            continue
        notification = value.get("review_notification")
        if not isinstance(notification, dict) or notification.get("status") != "sent":
            continue
        if str(notification.get("message_id") or "") not in parent_ids:
            continue
        expected_sender = str(notification.get("recipient") or "")
        if expected_sender and str(event.get("sender_id") or "") != expected_sender:
            continue
        expected_chat = str(notification.get("chat_id") or "")
        if expected_chat and str(event.get("chat_id") or "") != expected_chat:
            continue
        return path, value
    return None


def pending_review_states_in_chat(
    chat_id: str,
    *,
    root: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    states: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / ".oks" / "candidates").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("last_review_action") in {"accept", "reject"}:
            continue
        notification = value.get("review_notification")
        if not isinstance(notification, dict) or notification.get("status") != "sent":
            continue
        if str(notification.get("chat_id") or "") == chat_id:
            states.append((path, value))
    return states


def review_states_for_prompt(
    chat_id: str,
    prompt_message_id: str,
    *,
    root: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    states: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / ".oks" / "candidates").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            continue
        notification = value.get("review_notification")
        if not isinstance(notification, dict) or notification.get("status") != "sent":
            continue
        if str(notification.get("chat_id") or "") != chat_id:
            continue
        if str(notification.get("message_id") or "") == prompt_message_id:
            states.append((path, value))
    return states


# ── Event recording / I/O ────────────────────────────────────────────────


def record_review_event(
    path: Path,
    state: dict[str, Any],
    event: dict[str, Any],
    *,
    action: str,
    comment: str,
) -> None:
    receipts = state.get("review_reply_events")
    if not isinstance(receipts, list):
        receipts = []
    receipts.append(
        {
            "message_id": str(event.get("message_id") or event.get("id") or ""),
            "event_id": str(event.get("event_id") or ""),
            "sender_id": str(event.get("sender_id") or ""),
            "reply_to": str(event.get("reply_to") or ""),
            "root_id": str(event.get("root_id") or ""),
            "action": action,
            "comment": comment,
            "correlation_method": str(event.get("correlation_method") or "reply_context"),
            "received_at": event_reviewed_at(event.get("create_time")),
        }
    )
    state["review_reply_events"] = receipts
    atomic_write_json(path, state)


def read_review_record_after_write(
    config: WorkerConfig,
    record_id: str,
    expected_action: str,
    *,
    root: Path,
    _get_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _get = _get_fn if _get_fn is not None else functools.partial(_base_get_record, root=root)
    record = _get(config, record_id)
    for delay in (0.25, 0.5, 1.0):
        if scalar_cell(record["fields"].get("审核动作")) == expected_action:
            return record
        time.sleep(delay)
        record = _get(config, record_id)
    return record


def raw_message(
    config: WorkerConfig,
    message_id: str,
    *,
    root: Path,
    _lark_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _lark = _lark_fn if _lark_fn is not None else functools.partial(_base_lark_json, root=root)
    envelope = _lark(
        config,
        "api",
        "GET",
        f"/open-apis/im/v1/messages/{message_id}",
        "--as",
        "bot",
        "--format",
        "json",
    )
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise RuntimeError(f"Feishu message detail is unavailable: {message_id}")
    return items[0]


# ── Candidate promotion ──────────────────────────────────────────────────


def promote_candidate_document(
    candidate_path: Path,
    reviewed_body: str,
    review: dict[str, Any],
    *,
    root: Path,
    knowledge_root: Path | None = None,
) -> Path:
    metadata, _body = parse_candidate_document(candidate_path.read_text(encoding="utf-8"))
    metadata["status"] = "draft"
    metadata["review"] = review
    atomic_write_text(candidate_path, render_candidate_document(metadata, reviewed_body))
    cli_root = str(root / "cli")
    if cli_root not in sys.path:
        sys.path.insert(0, cli_root)
    from knowledge_studio import store

    previous_root = os.environ.get("OKS_ROOT")
    if knowledge_root is not None:
        os.environ["OKS_ROOT"] = str(knowledge_root)
    try:
        promoted_slug = store.promote_draft(
            candidate_path.stem,
            slug_hint=candidate_path.stem,
        )
        page = store.get_wiki_page(promoted_slug)
    finally:
        if previous_root is None:
            os.environ.pop("OKS_ROOT", None)
        else:
            os.environ["OKS_ROOT"] = previous_root
    if not page or not page.get("file_path"):
        raise RuntimeError(f"Promoted Wiki page cannot be resolved: {promoted_slug}")
    return Path(page["file_path"]).resolve()


# ── Core review state machine ────────────────────────────────────────────


def review_candidate(
    config: WorkerConfig,
    record: dict[str, Any],
    *,
    root: Path,
    _update_fn: LarkFn | None = None,
    _promote_fn: Callable[..., Path] | None = None,
) -> dict[str, Any]:
    _update = _update_fn if _update_fn is not None else functools.partial(_base_update_record, root=root)
    _promote = _promote_fn if _promote_fn is not None else promote_candidate_document

    record_id = record["record_id"]
    fields = record["fields"]
    action = scalar_cell(fields.get("审核动作"))
    if action not in REVIEW_ACTIONS:
        return {"processed": False, "reason": "no_review_action", "record_id": record_id}
    state = load_candidate_state(record_id, root=root)
    if scalar_cell(fields.get("候选ID")) != state.get("candidate_id"):
        raise RuntimeError(f"Candidate ID does not match local state for {record_id}")
    fingerprint = candidate_review_fingerprint(fields)
    if state.get("last_review_fingerprint") == fingerprint:
        return {"processed": False, "reason": "review_already_processed", "record_id": record_id}
    knowledge_root = configured_knowledge_root(config, root=root)
    stored_candidate = Path(str(state["candidate_path"]))
    candidate_path = (
        stored_candidate.resolve()
        if stored_candidate.is_absolute()
        else (root / stored_candidate).resolve()
    )
    if knowledge_root not in candidate_path.parents or not candidate_path.is_file():
        raise RuntimeError(
            f"Candidate file is unavailable or outside the configured knowledge root: {candidate_path}"
        )

    reviewed_at = scalar_cell(fields.get("审核时间")) or datetime.now(timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    comment = str(fields.get("审核意见") or "").strip()
    raw_change_types = fields.get("修改类型")
    change_types = (
        raw_change_types
        if isinstance(raw_change_types, list)
        else [str(raw_change_types)] if raw_change_types else []
    )
    if action in {"edit", "reject"} and not comment:
        raise RuntimeError(f"Review action {action} requires 审核意见")
    history_item = {
        "action": action,
        "comment": comment,
        "change_types": change_types,
        "reviewed_at": reviewed_at,
        "candidate_sha256": hashlib.sha256(
            str(fields.get("候选内容") or "").encode("utf-8")
        ).hexdigest(),
    }
    patch: dict[str, Any]
    wiki_path: Path | None = None
    if action == "accept":
        reviewed_body = str(fields.get("候选内容") or "").strip()
        if len(reviewed_body) < 50:
            raise RuntimeError("Accepted Candidate content is empty or too short")
        wiki_path = _promote(
            candidate_path,
            reviewed_body,
            {
                # A one-word "通过" means "accept this into the wiki". It does
                # not assert that the original decision was correct or that
                # execution succeeded — recording either would put words in the
                # reviewer's mouth, and both feed quality_score and the
                # [verified] label downstream.
                "outcome": "accepted",
                "review_depth": "light",
                "lesson": comment,
                "reviewed_at": str(reviewed_at),
            },
            root=root,
            knowledge_root=knowledge_root,
        )
        patch = {
            "运行状态": "已晋升",
            "Wiki状态": "promoted",
            "Wiki路径": wiki_path.relative_to(knowledge_root).as_posix(),
        }
    elif action == "reject":
        metadata, body = parse_candidate_document(candidate_path.read_text(encoding="utf-8"))
        metadata["status"] = "rejected"
        metadata["review"] = {
            "outcome": "failure",
            "decision_correct": False,
            "lesson": comment,
            "reviewed_at": str(reviewed_at),
        }
        atomic_write_text(candidate_path, render_candidate_document(metadata, body))
        patch = {"运行状态": "已拒绝", "Wiki状态": "rejected", "Wiki路径": None}
    elif action == "edit":
        patch = {"运行状态": "需人工", "Wiki状态": "candidate", "Wiki路径": None}
    else:
        patch = {"运行状态": "候选待审", "Wiki状态": "review_pending", "Wiki路径": None}
    patch["审核时间"] = str(reviewed_at)

    history = state.get("review_history", [])
    if not isinstance(history, list):
        history = []
    history.append(history_item)
    state["review_history"] = history
    state["last_review_fingerprint"] = fingerprint
    state["last_review_action"] = action
    state["last_reviewed_at"] = reviewed_at
    if wiki_path is not None:
        state["wiki_path"] = wiki_path.relative_to(knowledge_root).as_posix()
    atomic_write_json(candidate_state_path(record_id, root=root), state)
    _update(config, record_id, patch)
    return {"processed": True, "record_id": record_id, "action": action, "patch": patch}


def process_next_review(
    config: WorkerConfig,
    limit: int = 100,
    *,
    root: Path,
    _list_fn: Callable[..., list[dict[str, Any]]] | None = None,
    _update_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _list = _list_fn if _list_fn is not None else functools.partial(
        _list_review_records, root=root,
    )
    for record in _list(config, limit):
        fields = record["fields"]
        action = scalar_cell(fields.get("审核动作"))
        status = scalar_cell(fields.get("运行状态"))
        if action not in REVIEW_ACTIONS or status in {"已晋升", "已拒绝"}:
            continue
        result = review_candidate(config, record, root=root, _update_fn=_update_fn)
        if result.get("processed"):
            return result
    return {"processed": False, "reason": "no_pending_reviews"}


# ── Event-driven review pipeline ─────────────────────────────────────────


def apply_review_reply_event(
    config: WorkerConfig,
    event: dict[str, Any],
    *,
    root: Path,
    _update_fn: LarkFn | None = None,
    _get_fn: LarkFn | None = None,
    _review_candidate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply one direct reply to the exact Candidate notification it references."""
    _update = _update_fn if _update_fn is not None else functools.partial(_base_update_record, root=root)
    if _review_candidate_fn is not None:
        _do_review = _review_candidate_fn
    else:
        _do_review = functools.partial(review_candidate, root=root, _update_fn=_update)
    message_id = str(event.get("message_id") or event.get("id") or "").strip()
    if not message_id:
        return {"processed": False, "reason": "missing_message_id"}
    if event.get("chat_type") != "p2p" or event.get("sender_type") != "user":
        return {"processed": False, "reason": "not_personal_user_message", "message_id": message_id}
    if event.get("message_type") not in {"text", "post"}:
        return {"processed": False, "reason": "unsupported_message_type", "message_id": message_id}
    resolved = find_candidate_state_for_reply(event, root=root)
    if resolved is None:
        return {"processed": False, "reason": "unknown_review_notification", "message_id": message_id}
    state_path, state = resolved
    receipts = state.get("review_reply_events")
    if isinstance(receipts, list) and any(
        str(item.get("message_id") or "") == message_id
        for item in receipts
        if isinstance(item, dict)
    ):
        return {
            "processed": False,
            "reason": "review_message_already_processed",
            "message_id": message_id,
            "record_id": state.get("record_id"),
        }
    try:
        action, comment = parse_review_reply(str(event.get("content") or ""))
    except ValueError as error:
        return {
            "processed": False,
            "reason": "invalid_review_reply",
            "message_id": message_id,
            "record_id": state.get("record_id"),
            "error": str(error),
        }
    if action in {"edit", "reject"} and not comment:
        return {
            "processed": False,
            "reason": "review_comment_required",
            "message_id": message_id,
            "record_id": state.get("record_id"),
            "action": action,
        }
    record_id = str(state.get("record_id") or "").strip()
    if not record_id:
        raise RuntimeError(f"Candidate state has no record_id: {state_path}")
    patch = {
        "审核动作": action,
        "审核意见": comment or None,
        # The setup schema deliberately defines this as text, not a multi-select:
        # it keeps the control plane portable and supports free-form edit reasons.
        "修改类型": "无修改" if action == "accept" else None,
        "审核时间": event_reviewed_at(event.get("create_time")),
    }
    _update(config, record_id, patch)
    record = read_review_record_after_write(config, record_id, action, root=root, _get_fn=_get_fn)
    review_result = _do_review(config, record)
    if review_result.get("reason") == "no_review_action":
        raise RuntimeError(
            f"Base did not expose review action {action!r} after a bounded write-read retry"
        )
    latest = load_candidate_state(record_id, root=root)
    record_review_event(state_path, latest, event, action=action, comment=comment)
    return {
        "processed": bool(review_result.get("processed")),
        "message_id": message_id,
        "record_id": record_id,
        "candidate_id": state.get("candidate_id"),
        "revision": state.get("revision"),
        "action": action,
        "review": review_result,
    }


def reconcile_historical_review_reply(
    config: WorkerConfig,
    *,
    prompt_message_id: str,
    reply_message_id: str,
    root: Path,
    _raw_message_fn: Callable[..., dict[str, Any]] | None = None,
    _apply_reply_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recover a missed P2P review event without pretending chronology is a native reply link."""
    _raw_msg = (
        _raw_message_fn
        if _raw_message_fn is not None
        else functools.partial(raw_message, root=root)
    )
    _apply_reply = (
        _apply_reply_fn
        if _apply_reply_fn is not None
        else functools.partial(apply_review_reply_event, root=root)
    )
    prompt = _raw_msg(config, prompt_message_id)
    reply = _raw_msg(config, reply_message_id)
    chat_id = str(prompt.get("chat_id") or "")
    if not chat_id or str(reply.get("chat_id") or "") != chat_id:
        raise RuntimeError("Review prompt and reply are not in the same chat")
    reply_id = str(reply.get("message_id") or reply_message_id)
    prompt_states = review_states_for_prompt(chat_id, prompt_message_id, root=root)
    if len(prompt_states) == 1:
        _prompt_path, prompt_state = prompt_states[0]
        receipts = prompt_state.get("review_reply_events")
        if isinstance(receipts, list):
            prior = next(
                (
                    item
                    for item in receipts
                    if isinstance(item, dict) and str(item.get("message_id") or "") == reply_id
                ),
                None,
            )
            if prior is not None:
                return {
                    "processed": False,
                    "reason": "review_message_already_processed",
                    "message_id": reply_id,
                    "record_id": prompt_state.get("record_id"),
                    "correlation_method": str(
                        prior.get("correlation_method") or "reply_context"
                    ),
                }
    pending = pending_review_states_in_chat(chat_id, root=root)
    matching = [
        (path, state)
        for path, state in pending
        if str(state.get("review_notification", {}).get("message_id") or "") == prompt_message_id
    ]
    if len(pending) != 1 or len(matching) != 1:
        raise RuntimeError("Historical review fallback requires exactly one pending Candidate in the chat")
    _state_path, state = matching[0]
    notification = state["review_notification"]
    sender = reply.get("sender") if isinstance(reply.get("sender"), dict) else {}
    if sender.get("sender_type") != "user" or str(sender.get("id") or "") != str(
        notification.get("recipient") or ""
    ):
        raise RuntimeError("Historical review reply sender does not match the configured reviewer")
    parent_id = str(reply.get("parent_id") or "")
    root_id = str(reply.get("root_id") or "")
    if prompt_message_id in {parent_id, root_id}:
        method = "native_reply_context"
    else:
        try:
            prompt_position = int(str(prompt.get("message_position")))
            reply_position = int(str(reply.get("message_position")))
        except (TypeError, ValueError) as error:
            raise RuntimeError("Historical review fallback requires message positions") from error
        if reply_position != prompt_position + 1:
            raise RuntimeError("Historical review fallback requires the reply to immediately follow the prompt")
        if int(str(reply.get("create_time") or 0)) <= int(str(prompt.get("create_time") or 0)):
            raise RuntimeError("Historical review reply is not newer than the prompt")
        method = "p2p_sequence_fallback"
    event = {
        "event_id": "",
        "message_id": reply_id,
        "reply_to": prompt_message_id,
        "root_id": root_id,
        "chat_id": chat_id,
        "chat_type": "p2p",
        "sender_id": str(sender.get("id") or ""),
        "sender_type": "user",
        "message_type": str(reply.get("msg_type") or ""),
        "content": decoded_raw_message_content(reply),
        "create_time": str(reply.get("create_time") or ""),
        "correlation_method": method,
    }
    outcome = _apply_reply(config, event)
    outcome["correlation_method"] = method
    return outcome


def apply_review_event_with_fallback(
    config: WorkerConfig,
    event: dict[str, Any],
    *,
    root: Path,
    _apply_reply_fn: Callable[..., dict[str, Any]] | None = None,
    _pending_fn: Callable[..., list[tuple[Path, dict[str, Any]]]] | None = None,
    _reconcile_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _apply_reply = (
        _apply_reply_fn
        if _apply_reply_fn is not None
        else functools.partial(apply_review_reply_event, root=root)
    )
    _pending = (
        _pending_fn
        if _pending_fn is not None
        else functools.partial(pending_review_states_in_chat, root=root)
    )
    _reconcile = (
        _reconcile_fn
        if _reconcile_fn is not None
        else functools.partial(reconcile_historical_review_reply, root=root)
    )
    outcome = _apply_reply(config, event)
    if outcome.get("reason") != "unknown_review_notification":
        return outcome
    chat_id = str(event.get("chat_id") or "").strip()
    message_id = str(event.get("message_id") or event.get("id") or "").strip()
    if not chat_id or not message_id:
        return outcome
    pending = _pending(chat_id)
    if len(pending) != 1:
        return outcome
    notification = pending[0][1].get("review_notification")
    prompt_message_id = (
        str(notification.get("message_id") or "").strip()
        if isinstance(notification, dict)
        else ""
    )
    if not prompt_message_id:
        return outcome
    try:
        return _reconcile(
            config,
            prompt_message_id=prompt_message_id,
            reply_message_id=message_id,
        )
    except RuntimeError as error:
        return {**outcome, "fallback_error": str(error)}


def consume_review_events(
    config: WorkerConfig,
    *,
    max_events: int,
    timeout: str,
    root: Path,
    _apply_event_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _apply_event = (
        _apply_event_fn
        if _apply_event_fn is not None
        else functools.partial(apply_review_event_with_fallback, root=root)
    )
    if max_events < 1:
        raise ValueError("max_events must be at least 1")
    jq_filter = 'select(.chat_type=="p2p" and .sender_type=="user")'
    if config.review_recipient_user_id:
        recipient = json.dumps(config.review_recipient_user_id, ensure_ascii=False)
        jq_filter = f"{jq_filter} | select(.sender_id=={recipient})"
    result = subprocess.run(
        [
            str(config.lark_cli),
            "event",
            "consume",
            "im.message.receive_v1",
            "--as",
            "bot",
            "--max-events",
            str(max_events),
            "--timeout",
            timeout,
            "--jq",
            jq_filter,
        ],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Feishu review event consumer failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    events: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            continue
        events.append(event)
        outcomes.append(_apply_event(config, event))
    return {
        "events_received": len(events),
        "outcomes": outcomes,
        "consumer_stderr": result.stderr.strip(),
    }


# ── Internal: default list_review_records for process_next_review ────────


def _list_review_records(
    config: WorkerConfig,
    limit: int = 100,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    """Fetch review-candidate records via lark_json (standalone default)."""
    command = [
        "base",
        "+record-list",
        *base_args(config),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for field in CANDIDATE_FIELDS:
        command.extend(["--field-id", field])
    envelope = _base_lark_json(config, *command, root=root)
    data = envelope.get("data", {})
    return _parse_record_rows(
        data.get("data", []),
        data.get("fields", CANDIDATE_FIELDS),
        data.get("record_id_list", []),
    )
