"""File-backed Mail coordination primitives.

Mail is deliberately a small coordination layer.  Canonical message content is
written once; recipient state and per-session delivery receipts are projections
that can be rebuilt from the message files.  This module is shared by the CLI
and the editor hooks so they cannot grow separate state machines.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from knowledge_studio import store
from knowledge_studio import identity


SCHEMA_VERSION = "mail.message.v1"
RECEIPT_VERSION = "mail.delivery-receipt.v1"
RECEIPT_EVENT_VERSION = "mail.delivery-receipt-event.v1"
SESSION_VERSION = "mail.session.v1"
DEFAULT_REASON = "direct"
REASONS = {"direct", "mention", "conflict", "review_request", "thread_reply", "system", "handoff"}
RECORD_KINDS = {"message", "goal", "handoff", "result", "blocked", "note", "knowledge_ref", "review_request", "acknowledgement"}
SENDER_KINDS = {"human", "agent", "unknown"}
EVIDENCE_REF_TYPES = {"trace", "run", "capability", "bundle", "candidate", "wiki", "commit"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    # Thread chronology is user-visible.  Second precision made a send and an
    # immediate reply share the same sort key, falling back to random IDs.
    return utc_now().isoformat(timespec="microseconds")


def safe_id(value: str, default: str = "unknown") -> str:
    value = re.sub(r"[^A-Za-z0-9_.@-]+", "_", str(value or "").strip())
    return value[:120] or default


def _message_id() -> str:
    return f"msg_{utc_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:12]}"


def _thread_id() -> str:
    return f"thr_{utc_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"


def _normalise_agent(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return "@unknown"
    return value if value.startswith("@") else f"@{value}"


def normalise_sender_kind(value: str, sender: str = "") -> str:
    """Return a compatible provenance label for a message author.

    This is deliberately provenance rather than authentication: it tells a
    receiver whether a local adapter says the message came from a person or an
    agent, but does not grant authority to its content.
    """
    candidate = str(value or "").strip().lower()
    if not candidate:
        return "human" if _normalise_agent(sender) == "@human" else "agent"
    if candidate not in SENDER_KINDS:
        raise ValueError("sender_kind must be one of: human, agent, unknown")
    return candidate


def normalise_record_kind(value: str) -> str:
    """Return a small fact classification, independent of delivery reason."""
    candidate = str(value or "").strip().lower() or "message"
    if candidate not in RECORD_KINDS:
        raise ValueError("record_kind must be one of: " + ", ".join(sorted(RECORD_KINDS)))
    return candidate


def normalise_recipients(value: str | Iterable[str]) -> list[str]:
    values = value.split(",") if isinstance(value, str) else value
    result: list[str] = []
    for raw in values:
        recipient = _normalise_agent(raw)
        if recipient not in result:
            result.append(recipient)
    return result or ["@unknown"]


def normalise_evidence_refs(value: Any) -> list[dict[str, str]]:
    """Validate compact references without accepting copied evidence content."""
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("evidence_refs must be a list of reference objects")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("each evidence ref must be an object")
        ref_type = str(raw.get("type", "") or "").strip().lower()
        if ref_type not in EVIDENCE_REF_TYPES:
            raise ValueError(f"unsupported evidence ref type: {ref_type or '(empty)'}")
        expected_key = "path" if ref_type in {"candidate", "wiki"} else "id"
        if set(raw) != {"type", expected_key}:
            raise ValueError(f"{ref_type} evidence ref must contain only type and {expected_key}")
        locator = str(raw.get(expected_key, "") or "").strip()
        if not locator or len(locator) > 240 or "\r" in locator or "\n" in locator:
            raise ValueError("evidence ref locator must be non-empty and at most 240 characters")
        if expected_key == "path":
            candidate_path = locator.replace("\\", "/")
            if candidate_path.startswith("/") or re.match(r"^[A-Za-z]:/", candidate_path):
                raise ValueError("knowledge evidence path must be relative to the KB")
            if any(part in {"", ".", ".."} for part in candidate_path.split("/")):
                raise ValueError("knowledge evidence path must not contain traversal or empty segments")
            locator = candidate_path
        ref = {"type": ref_type, expected_key: locator}
        fingerprint = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            result.append(ref)
    return result


def _registry_agents(root: Path) -> list[str]:
    agents: list[str] = []
    from .layout import registry_path
    path = registry_path(root)
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                agent = str(record.get("agent_id", "") or "").strip()
                if agent and _normalise_agent(agent) not in agents:
                    agents.append(_normalise_agent(agent))
        except OSError:
            pass
    # A live runtime session is also a routable Agent identity.  This keeps
    # @all useful for hosts that do not maintain a separate profile registry.
    session_root = sessions_dir(root)
    if session_root.is_dir():
        for session_path in session_root.glob("*.json"):
            try:
                record = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(record.get("status", "active")).lower() not in {"active", "idle"}:
                continue
            agent = str(record.get("agent_id", "") or "").strip()
            if agent and _normalise_agent(agent) not in agents:
                agents.append(_normalise_agent(agent))
    return agents


def resolve_recipients(root: Path, value: str | Iterable[str], sender: str = "") -> list[str]:
    recipients = normalise_recipients(value)
    if "@all" not in recipients:
        return recipients
    expanded = [agent for agent in _registry_agents(root) if agent != _normalise_agent(sender)]
    explicit = [agent for agent in recipients if agent != "@all"]
    merged: list[str] = []
    for agent in expanded + explicit:
        if agent not in merged:
            merged.append(agent)
    if not merged:
        raise ValueError("@all 没有可投递的已注册 Agent；请先绑定 Session，或改用 --to @agent-id")
    return merged


def messages_dir(root: Path) -> Path:
    return root / "mail" / "messages"


def inbox_dir(root: Path, agent_id: str) -> Path:
    return root / "mail" / "inbox" / safe_id(_normalise_agent(agent_id).lstrip("@"))


def receipts_dir(root: Path, session_id: str) -> Path:
    return root / "mail" / "receipts" / safe_id(session_id, "default")


def receipt_events_dir(root: Path, session_id: str, message_id: str) -> Path:
    """Append-only receipt events for one Machine-local Session/message pair."""
    return root / "mail" / "receipt-events" / safe_id(session_id, "default") / safe_id(message_id)


def receipt_event_paths(root: Path, session_id: str, message_id: str) -> list[Path]:
    directory = receipt_events_dir(root, session_id, message_id)
    return sorted(directory.glob("evt_*.json")) if directory.is_dir() else []


def iter_receipt_events(root: Path, session_id: str, message_id: str) -> Iterable[dict[str, Any]]:
    """Read the monotonic receipt lifecycle, independent of clock/UUID order.

    These events only advance injected -> presented -> acknowledged. Wall clocks
    can tie or move backwards, and UUID suffixes do not record causal order.
    Ordering by lifecycle also repairs legacy events without rewriting evidence.
    """
    events = []
    for path in receipt_event_paths(root, session_id, message_id):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            events.append(record)
    stages = {"injected": 0, "presented": 1, "acknowledged": 2}
    yield from sorted(events, key=lambda event: (
        stages.get(str(event.get("event_type", "")), -1),
        str(event.get("timestamp", "")), str(event.get("event_id", "")),
    ))


def _receipt_event_id() -> str:
    return f"evt_{utc_now().strftime('%Y%m%dT%H%M%S%f')}_{uuid.uuid4().hex[:12]}"


def _append_receipt_event(
    root: Path,
    session_id: str,
    message_id: str,
    event_type: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    event_id = _receipt_event_id()
    event = {
        "schema_version": RECEIPT_EVENT_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": iso_now(),
        "receipt": dict(receipt),
    }
    store._atomic_write(
        receipt_events_dir(root, session_id, message_id) / f"{event_id}.json",
        json.dumps(event, ensure_ascii=False, indent=2) + "\n",
    )
    return event


def _load_receipt_snapshot(root: Path, session_id: str, message_id: str) -> dict[str, Any] | None:
    path = receipt_path(root, session_id, message_id)
    events = list(iter_receipt_events(root, session_id, message_id))
    # Once event history exists it is authoritative; the JSON file is only a
    # materialized compatibility view that can be rebuilt after a Git merge.
    if events and isinstance(events[-1].get("receipt"), dict):
        return dict(events[-1]["receipt"])
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict):
                return record
        except (OSError, json.JSONDecodeError):
            pass
    return None


def sessions_dir(root: Path) -> Path:
    return root / "mail" / "sessions"


def notifications_dir(root: Path, agent_id: str) -> Path:
    return root / "mail" / "notifications" / safe_id(_normalise_agent(agent_id).lstrip("@"))


def queue_notification(
    root: Path,
    agent_id: str,
    message: dict[str, Any],
    *,
    created_at: str = "",
) -> dict[str, Any]:
    """Persist a pending notification intent without presenting the message."""
    meta = message.get("meta", {})
    message_id = str(meta.get("message_id", ""))
    notification = {
        "schema_version": "mail.notification.v1",
        "message_id": message_id,
        "thread_id": meta.get("thread_id", ""),
        "agent_id": _normalise_agent(agent_id),
        "status": "pending",
        "wake_supported": False,
        "created_at": created_at or iso_now(),
    }
    path = notifications_dir(root, agent_id) / f"{safe_id(message_id)}.json"
    store._atomic_write(path, json.dumps(notification, ensure_ascii=False, indent=2) + "\n")
    return notification


def mark_notification_presented(
    root: Path,
    agent_id: str,
    message_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any] | None:
    """Close one notification intent once a Session actually saw the message.

    The projection stays honest: presenters (``mail wait`` or the Hook) call
    this after recording delivery, so nothing lingers as ``pending`` forever.
    Idempotent — a second call never rewrites ``presented_at``.
    """
    path = notifications_dir(root, agent_id) / f"{safe_id(message_id)}.json"
    if not path.is_file():
        return None
    try:
        notification = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(notification, dict) or notification.get("status") == "presented":
        return notification if isinstance(notification, dict) else None
    notification["status"] = "presented"
    notification["presented_at"] = iso_now()
    if session_id:
        notification["presented_by_session"] = session_id
    store._atomic_write(path, json.dumps(notification, ensure_ascii=False, indent=2) + "\n")
    return notification


def _frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        if value is None:
            value = ""
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def parse_message(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip("\"'")
            body = parts[2]
    title = ""
    body_lines = body.strip().splitlines()
    if body_lines and body_lines[0].startswith("# "):
        title = body_lines.pop(0)[2:].strip()
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
    recipients = normalise_recipients(str(meta.get("to", "@unknown")))
    meta["to"] = recipients
    raw_refs = meta.get("evidence_refs", "")
    if isinstance(raw_refs, str) and raw_refs.strip():
        try:
            meta["evidence_refs"] = normalise_evidence_refs(json.loads(raw_refs))
        except (TypeError, ValueError, json.JSONDecodeError):
            meta["evidence_refs"] = []
    else:
        meta["evidence_refs"] = []
    meta.setdefault("message_id", path.stem)
    meta.setdefault("thread_id", f"legacy_{path.stem}")
    meta.setdefault("from", "unknown")
    meta.setdefault("origin_machine_id", "unknown")
    meta.setdefault("sender_kind", "unknown")
    meta.setdefault("read", "false")
    meta.setdefault("delivery_reason", "direct")
    # Legacy messages did not distinguish what a record is from why it was
    # delivered.  Treat them as ordinary messages without rewriting history.
    meta.setdefault("record_kind", "message")
    return {"path": path, "meta": meta, "title": title or "(no title)", "body": "\n".join(body_lines).strip()}


def canonical_path(root: Path, message_id: str) -> Path:
    return messages_dir(root) / f"{safe_id(message_id)}.md"


def recipient_state_path(root: Path, agent_id: str, message_id: str) -> Path:
    return inbox_dir(root, agent_id) / f"{safe_id(message_id)}.json"


def receipt_path(root: Path, session_id: str, message_id: str) -> Path:
    return receipts_dir(root, session_id) / f"{safe_id(message_id)}.json"


def machine_id(value: str = "") -> str:
    """Return a validated explicit or locally persisted Machine identity."""
    return identity.normalise_machine_id(value)


def register_session(
    root: Path,
    session_id: str,
    agent_id: str,
    cwd: str = "",
    scope: str = "",
    machine_id: str = "",
) -> Path:
    """Persist the thin execution-context registry used for routing context."""
    sid = str(session_id or "").strip() or (cwd or "default")
    path = sessions_dir(root) / f"{safe_id(sid, 'default')}.json"
    now = iso_now()
    record = {
        "schema_version": SESSION_VERSION,
        "session_id": sid,
        "agent_id": _normalise_agent(agent_id),
        "machine_id": identity.normalise_machine_id(machine_id),
        "cwd": cwd,
        "scope": scope,
        "status": "active",
        "started_at": now,
        "last_seen_at": now,
    }
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            record["started_at"] = previous.get("started_at", now)
            record["status"] = previous.get("status", "active")
        except (OSError, json.JSONDecodeError):
            pass
    store._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return path


def write_message(
    root: Path,
    *,
    body: str,
    sender: str,
    sender_kind: str = "",
    recipients: str | Iterable[str],
    title: str = "",
    kind: str = "message",
    priority: str = "normal",
    thread_id: str = "",
    reply_to: str = "",
    origin_session_id: str = "",
    origin_machine_id: str = "",
    delivery_reason: str = DEFAULT_REASON,
    record_kind: str = "message",
    notify: bool = False,
    session_policy: str = "next_prompt",
    evidence_refs: Any = None,
    agreement: dict | None = None,
) -> dict[str, Any]:
    encoded_agreement = None
    if agreement is not None:
        from knowledge_studio import handoff
        if kind != "handoff":
            raise ValueError("An agreement can only be attached to a handoff")
        encoded_agreement = handoff.encode(agreement)
        from knowledge_studio.tasks import require_active_scope
        require_active_scope(root, agreement['scope'])
        if handoff.check(root, agreement, agreement["scope"])["status"] != "current":
            raise ValueError("Agreement sources changed; prepare a new reviewed snapshot before delegating")
    sender = str(sender or "human").strip() or "human"
    sender_kind = normalise_sender_kind(sender_kind, sender)
    resolved = resolve_recipients(root, recipients, sender)
    message_id = _message_id()
    thread_id = thread_id.strip() or _thread_id()
    reason = delivery_reason if delivery_reason in REASONS else DEFAULT_REASON
    fact_kind = normalise_record_kind(record_kind)
    refs = normalise_evidence_refs(evidence_refs)
    now = iso_now()
    meta = {
        "schema_version": SCHEMA_VERSION,
        "message_id": message_id,
        "thread_id": thread_id,
        "reply_to": reply_to,
        "origin_session_id": origin_session_id,
        "origin_machine_id": identity.normalise_machine_id(origin_machine_id),
        "evidence_refs": json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
        "from": sender,
        "sender_kind": sender_kind,
        "to": resolved,
        "delivery_reason": reason,
        "record_kind": fact_kind,
        "timestamp": now,
        "type": kind,
        "priority": priority,
        "notify": bool(notify),
        "session_policy": session_policy if session_policy in {"next_prompt", "wait", "notify"} else "next_prompt",
    }
    title_line = title.strip() or "(no title)"
    if encoded_agreement is not None:
        # Mail has a line-oriented frontmatter parser; base64 keeps embedded
        # YAML delimiters and newlines from truncating the canonical message.
        meta["handoff_agreement_b64"] = encoded_agreement
    content = _frontmatter(meta) + "\n\n# " + title_line + "\n\n" + str(body).rstrip() + "\n"
    path = canonical_path(root, message_id)
    store._atomic_write(path, content)
    for recipient in resolved:
        state = {
            "schema_version": "mail.recipient-state.v1",
            "message_id": message_id,
            "thread_id": thread_id,
            "agent_id": recipient,
            "created_at": now,
            "notified_at": None,
            "read_at": None,
            "archived_at": None,
            "acknowledged_at": None,
            "thread_state": "open",
        }
        store._atomic_write(recipient_state_path(root, recipient, message_id), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        if notify or session_policy == "notify":
            queue_notification(root, recipient, {"meta": meta}, created_at=now)
    return {"message_id": message_id, "thread_id": thread_id, "path": path, "recipients": resolved, "meta": meta, "evidence_refs": refs}


def delegate_message(
    root: Path,
    *,
    task: str,
    sender: str,
    recipients: str | Iterable[str],
    sender_kind: str = "agent",
    title: str = "",
    context: str = "",
    acceptance: str = "",
    origin_session_id: str = "",
    origin_machine_id: str = "",
    notify: bool = False,
    evidence_refs: Any = None,
    agreement: dict | None = None,
) -> dict[str, Any]:
    """Create a human/Agent-friendly handoff using the existing Mail contract.

    This is an intent-level facade, not a second message protocol: the persisted
    result remains a normal ``mail.message.v1`` handoff with one canonical body,
    recipient projections, and the existing Session Receipt lifecycle.
    """
    task_text = str(task or "").strip()
    if not task_text:
        raise ValueError("task is required")
    sections = [f"## 任务\n{task_text}"]
    if str(context or "").strip():
        sections.append(f"## 上下文\n{str(context).strip()}")
    if str(acceptance or "").strip():
        sections.append(f"## 验收条件\n{str(acceptance).strip()}")
    if agreement is not None:
        from knowledge_studio.handoff import render
        sections.append(render(agreement))
    return write_message(
        root,
        body="\n\n".join(sections),
        sender=sender,
        sender_kind=sender_kind,
        recipients=recipients,
        title=title or task_text.splitlines()[0][:120],
        kind="handoff",
        origin_session_id=origin_session_id,
        origin_machine_id=origin_machine_id,
        evidence_refs=evidence_refs,
        record_kind="handoff",
        delivery_reason="handoff",
        notify=notify,
        session_policy="notify" if notify else "next_prompt",
        agreement=agreement,
    )


def _iter_canonical(root: Path) -> Iterable[dict[str, Any]]:
    directory = messages_dir(root)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        message = parse_message(path)
        if message:
            yield message


def _iter_legacy(root: Path) -> Iterable[dict[str, Any]]:
    directory = root / "mail" / "inbox"
    if not directory.is_dir():
        return
    # Historical inboxes were sometimes organised by date (mail/inbox/2026/09/11/…),
    # so walk the whole subtree instead of only the flat top level.
    for path in sorted(directory.rglob("*.md"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        message = parse_message(path)
        if message:
            yield message


def iter_messages(root: Path, agent_id: str = "") -> Iterable[dict[str, Any]]:
    """Yield new canonical messages and readable legacy flat-inbox messages."""
    wanted = _normalise_agent(agent_id) if agent_id else ""
    seen: set[str] = set()
    if wanted:
        state_dir = inbox_dir(root, wanted)
        if state_dir.is_dir():
            for state_path in sorted(state_dir.glob("*.json"), reverse=True):
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                message = parse_message(canonical_path(root, str(state.get("message_id", state_path.stem))))
                if message:
                    message["state"] = state
                    seen.add(str(message["meta"].get("message_id")))
                    yield message
    for message in _iter_canonical(root):
        message_id = str(message["meta"].get("message_id"))
        if message_id in seen:
            continue
        sender = _normalise_agent(str(message["meta"].get("from", "")))
        if not wanted or wanted in message["meta"].get("to", []) or sender == wanted:
            if wanted and sender == wanted:
                message["self"] = True
            yield message
    for message in _iter_legacy(root):
        message_id = str(message["meta"].get("message_id"))
        if message_id in seen:
            continue
        sender = _normalise_agent(str(message["meta"].get("from", "")))
        if not wanted or wanted in message["meta"].get("to", []) or "@all" in message["meta"].get("to", []) or sender == wanted:
            if wanted and sender == wanted:
                message["self"] = True
            if wanted:
                state_path = recipient_state_path(root, wanted, message_id)
                if state_path.is_file():
                    message["state"] = load_state(root, wanted, message_id)
            yield message


def load_state(root: Path, agent_id: str, message_id: str) -> dict[str, Any]:
    path = recipient_state_path(root, agent_id, message_id)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"message_id": message_id, "agent_id": _normalise_agent(agent_id), "read_at": None, "archived_at": None, "acknowledged_at": None}


def update_recipient_state(root: Path, agent_id: str, message_id: str, **changes: Any) -> dict[str, Any]:
    state = load_state(root, agent_id, message_id)
    state_path = recipient_state_path(root, agent_id, message_id)
    state.update(changes)
    with store._file_lock(state_path.with_name(".recipient-state.lock")):
        # Re-read after taking the lock so concurrent read/archive/ack updates
        # cannot overwrite each other.
        current = load_state(root, agent_id, message_id)
        current.update(changes)
        store._atomic_write(state_path, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        state = current
    return state


def record_delivery(
    root: Path,
    session_id: str,
    message: dict[str, Any],
    *,
    agent_id: str = "",
    machine_id: str = "",
    delivered: bool = True,
) -> dict[str, Any]:
    sid = str(session_id or "").strip() or "default"
    message_id = str(message["meta"].get("message_id"))
    path = receipt_path(root, sid, message_id)
    with store._file_lock(path.with_name(".delivery-receipts.lock")):
        previous = _load_receipt_snapshot(root, sid, message_id)
        now = iso_now()
        receipt = previous or {
            "schema_version": RECEIPT_VERSION,
            "message_id": message_id,
            "thread_id": message["meta"].get("thread_id", ""),
            "session_id": sid,
            "agent_id": _normalise_agent(agent_id or message["meta"].get("to", ["@unknown"])[0]),
            "machine_id": identity.normalise_machine_id(machine_id),
            "delivery_reason": message["meta"].get("delivery_reason", DEFAULT_REASON),
            "notified_at": now,
            "injected_at": now,
            "delivered_at": now if delivered else None,
            "status": "presented" if delivered else "injected",
        }
        previous_status = str(receipt.get("status", ""))
        if delivered and previous_status == "injected":
            receipt["status"] = "presented"
            receipt["delivered_at"] = receipt.get("delivered_at") or now
        transitioned = previous is None or receipt.get("status") != previous_status
        if transitioned:
            _append_receipt_event(
                root,
                sid,
                message_id,
                "presented" if delivered else "injected",
                receipt,
            )
        store._atomic_write(path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def acknowledge_delivery(
    root: Path,
    session_id: str,
    message_id: str,
    *,
    agent_id: str = "",
    machine_id: str = "",
) -> dict[str, Any]:
    """Acknowledge one Session receipt without changing Agent-level state."""
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    path = receipt_path(root, sid, message_id)
    if not path.is_file() and not receipt_event_paths(root, sid, message_id):
        raise FileNotFoundError(message_id)
    with store._file_lock(path.with_name(".delivery-receipts.lock")):
        record = _load_receipt_snapshot(root, sid, message_id)
        if record is None:
            raise FileNotFoundError(message_id)
        expected_agent = _normalise_agent(agent_id) if agent_id else ""
        actual_agent = _normalise_agent(str(record.get("agent_id", "")))
        if expected_agent and actual_agent != expected_agent:
            raise PermissionError(
                f"receipt belongs to {actual_agent}, not {expected_agent}"
            )
        expected_machine = identity.normalise_machine_id(machine_id)
        actual_machine = str(record.get("machine_id", "") or "")
        if actual_machine and actual_machine != expected_machine:
            raise PermissionError(
                f"receipt belongs to machine {actual_machine}, not {expected_machine}"
            )
        if record.get("status") != "acknowledged":
            record["acknowledged_at"] = record.get("acknowledged_at") or iso_now()
            record["status"] = "acknowledged"
        record.setdefault("machine_id", expected_machine)
        if record.get("status") == "acknowledged" and not any(
            event.get("event_type") == "acknowledged"
            for event in iter_receipt_events(root, sid, message_id)
        ):
            _append_receipt_event(root, sid, message_id, "acknowledged", record)
        store._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def has_delivery_receipt(root: Path, session_id: str, message_id: str) -> bool:
    return receipt_path(root, session_id, message_id).is_file() or bool(
        receipt_event_paths(root, session_id, message_id)
    )


def group_threads(messages: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        thread_id = str(message["meta"].get("thread_id") or message["meta"].get("message_id"))
        grouped.setdefault(thread_id, []).append(message)
    return grouped


def _message_sort_key(message: dict[str, Any]) -> tuple[str, str]:
    meta = message.get("meta", {})
    return (str(meta.get("timestamp", "")), str(meta.get("message_id", "")))


def visible_reply_parent(message: dict[str, Any], by_id: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a direct response within the caller's already filtered view.

    A bare reply_to is only a claim. Lifecycle evidence also needs the same
    Thread, an addressed respondent, and a reply addressed to the parent author.
    This checks file provenance, not authentication, acceptance, or completion.
    """
    meta = message["meta"]
    parent = by_id.get(str(meta.get("reply_to") or ""))
    if not parent:
        return None
    source = parent["meta"]
    if source["message_id"] == meta["message_id"]:
        return None
    if (source.get("thread_id") or source["message_id"]) != (meta.get("thread_id") or meta["message_id"]):
        return None
    author = _normalise_agent(str(source.get("from") or ""))
    respondent = _normalise_agent(str(meta.get("from") or ""))
    recipients = {_normalise_agent(str(value)) for value in source.get("to", [])}
    destinations = {_normalise_agent(str(value)) for value in meta.get("to", [])}
    if respondent in {author, "@unknown", "@all"} or (respondent not in recipients and "@all" not in recipients):
        return None
    if author not in destinations and "@all" not in destinations:
        return None
    return parent


def thread_messages(root: Path, thread_id: str, agent_id: str = "") -> list[dict[str, Any]]:
    """Return the visible canonical/legacy conversation for one Thread."""
    wanted = str(thread_id or "")
    messages = [
        message for message in iter_messages(root, agent_id)
        if str(message["meta"].get("thread_id") or message["meta"].get("message_id")) == wanted
    ]
    return sorted(messages, key=_message_sort_key)


def _message_unread(message: dict[str, Any]) -> bool:
    if message.get("self"):
        return False
    state = message.get("state") or {}
    if state:
        return not state.get("read_at") and not state.get("archived_at")
    return str(message.get("meta", {}).get("read", "false")).lower() != "true"


def snapshot_data(root: Path, agent_id: str, *, max_threads: int = 100, max_messages: int = 50) -> dict[str, Any]:
    """Return a bounded, JSON-safe Thread-first Mail projection for hosts.

    This is intentionally a read-only projection.  Hosts such as dsh-oks can
    render it without reading OKS files directly or parsing the HTML snapshot;
    all state changes continue to go through ``oks mail`` commands.
    """
    messages = list(iter_messages(root, agent_id))
    grouped = group_threads(messages)
    ordered = sorted(
        grouped.items(),
        key=lambda item: max(_message_sort_key(message) for message in item[1]),
        reverse=True,
    )
    truncated = len(ordered) > max_threads
    ordered = ordered[:max_threads]
    threads: list[dict[str, Any]] = []
    for thread_id, items in ordered:
        items = sorted(items, key=_message_sort_key)
        item_truncated = len(items) > max_messages
        selected = items[-max_messages:]
        serialised: list[dict[str, Any]] = []
        for message in selected:
            meta = message["meta"]
            state = message.get("state") or {}
            serialised.append({
                "message_id": str(meta.get("message_id", "")),
                "thread_id": str(meta.get("thread_id") or thread_id),
                "reply_to": str(meta.get("reply_to", "") or ""),
                "from": str(meta.get("from", "unknown")),
                "sender_kind": str(meta.get("sender_kind", "unknown")),
                "to": [str(value) for value in meta.get("to", [])],
                "title": str(message.get("title", "(no title)")),
                "body": str(message.get("body", ""))[:4000],
                "timestamp": str(meta.get("timestamp", "")),
                "origin_session_id": str(meta.get("origin_session_id", "") or ""),
                "origin_machine_id": str(meta.get("origin_machine_id", "unknown") or "unknown"),
                "evidence_refs": normalise_evidence_refs(meta.get("evidence_refs", [])),
                "delivery_reason": str(meta.get("delivery_reason", DEFAULT_REASON)),
                "record_kind": str(meta.get("record_kind", "message")),
                "read_at": state.get("read_at"),
                "archived_at": state.get("archived_at"),
                "thread_state": str(state.get("thread_state", "open")),
            })
        latest = serialised[-1] if serialised else {}
        unread_count = sum(1 for message in items if _message_unread(message))
        archived = all((message.get("state") or {}).get("archived_at") for message in items)
        participants = sorted({
            participant
            for message in items
            for participant in (
                [_normalise_agent(str(message["meta"].get("from", "unknown")))]
                + [_normalise_agent(str(value)) for value in message["meta"].get("to", [])]
            )
            if participant
        })
        threads.append({
            "thread_id": thread_id,
            "title": str(items[0].get("title", "(no title)")),
            "state": "archived" if archived else "open",
            "message_count": len(items),
            "unread_count": unread_count,
            "participants": participants,
            "delivery_reason": latest.get("delivery_reason", DEFAULT_REASON),
            "last_at": latest.get("timestamp", ""),
            "messages": serialised,
            "truncated": item_truncated,
        })
    active_messages = [message for message in messages if not message.get("self") and not (message.get("state") or {}).get("archived_at")]
    return {
        "schema": "mail.snapshot.v1",
        "agent": _normalise_agent(agent_id),
        "counts": {
            "inbox": len(active_messages),
            "unread": sum(1 for message in active_messages if _message_unread(message)),
            "open_threads": sum(1 for thread in threads if thread["state"] == "open"),
            "archived_threads": sum(1 for thread in threads if thread["state"] == "archived"),
            "sent": sum(1 for message in messages if str(message["meta"].get("from", "")).lstrip("@") == _normalise_agent(agent_id).lstrip("@")),
        },
        "threads": threads,
        "truncated": truncated,
    }


def render_snapshot(root: Path, agent_id: str, output: Path) -> Path:
    """Render a standalone, read-only Compact Inbox snapshot."""
    messages = list(iter_messages(root, agent_id))
    grouped = group_threads(messages)
    ordered = sorted(
        grouped.items(),
        key=lambda item: _message_sort_key(item[1][-1]),
        reverse=True,
    )
    selected_id = ordered[0][0] if ordered else ""

    def build_thread_view(thread_id: str, visible_items: list[dict[str, Any]]) -> dict[str, Any]:
        selected_messages = thread_messages(root, thread_id, agent_id)
        visible_states = {
            str(message["meta"].get("message_id")): message.get("state") or {}
            for message in visible_items
        }
        for message in selected_messages:
            state = visible_states.get(str(message["meta"].get("message_id")))
            if state:
                message["state"] = state
        latest_message = selected_messages[-1] if selected_messages else None
        latest_meta = latest_message["meta"] if latest_message else {}
        latest_scope = str(latest_meta.get("scope", "") or "")
        latest_session = str(latest_meta.get("origin_session_id", "") or "")
        if not latest_scope and latest_session:
            session_path = sessions_dir(root) / f"{safe_id(latest_session, 'default')}.json"
            try:
                latest_scope = str(json.loads(session_path.read_text(encoding="utf-8")).get("scope", "") or "")
            except (OSError, json.JSONDecodeError):
                pass
        context_files = latest_meta.get("files", [])
        if isinstance(context_files, str):
            context_files = [item.strip() for item in context_files.split(",") if item.strip()]
        return {
            "thread_id": thread_id,
            "visible": visible_items,
            "messages": selected_messages,
            "latest": latest_message,
            "latest_meta": latest_meta,
            "scope": latest_scope,
            "files": context_files,
        }

    thread_views = [build_thread_view(thread_id, items) for thread_id, items in ordered]
    selected_view = thread_views[0] if thread_views else None
    selected = selected_view["messages"] if selected_view else []
    latest = selected_view["latest"] if selected_view else None
    unread_count = sum(1 for message in messages if _message_unread(message))
    open_count = sum(
        1 for _, items in ordered
        if any((message.get("state") or {}).get("thread_state", "open") == "open" for message in items)
    )

    reason_labels = {
        "conflict": "⚠ conflict",
        "thread_reply": "↩ reply",
        "review_request": "◎ review",
        "handoff": "→ handoff",
        "system": "• system",
        "direct": "• direct",
    }
    thread_rows = []
    for thread_id, items in ordered:
        head = items[0]
        latest_item = items[-1]
        thread_rows.append(
            f'<button type="button" class="thread-row {"selected" if thread_id == selected_id else ""}" '
            f'data-thread-id="{escape(thread_id)}" aria-pressed="{"true" if thread_id == selected_id else "false"}">'
            f'<span class="dot {"unread" if any(_message_unread(m) for m in items) else "done"}"></span>'
            f'<span class="thread-copy"><strong>{escape(head["title"])}</strong>'
            f'<small>{escape(str(head["meta"].get("from", "unknown")))} → {escape(", ".join(head["meta"].get("to", [])))}</small>'
            f'<small>{escape(reason_labels.get(str(latest_item["meta"].get("delivery_reason", "direct")), "• direct"))} · {len(items)} 条消息</small></span>'
            f'<time>{escape(str(latest_item["meta"].get("timestamp", ""))[-8:-3])}</time></button>'
        )

    def render_message_blocks(items: list[dict[str, Any]]) -> str:
        blocks = []
        for message in items:
            meta = message["meta"]
            state = message.get("state") or {}
            blocks.append(
                f'<div class="session-label">Session · {escape(str(meta.get("from", "unknown")))} · '
                f'{escape(str(meta.get("origin_session_id") or "-"))} · {escape(str(meta.get("timestamp", ""))[-8:-3])}</div>'
                f'<article class="message-card {"accent" if meta.get("delivery_reason") == "thread_reply" else ""}">'
                f'<h3>{escape(message["title"])}</h3><p>{escape(message["body"])}</p>'
                f'<small>message_id: {escape(str(meta.get("message_id", "")))} · '
                f'reply_to: {escape(str(meta.get("reply_to") or "-"))} · '
                f'{"已读" if state.get("read_at") else "未读"}</small></article>'
            )
        return "".join(blocks) or '<div class="empty">当前 Agent 没有可显示的 Mail。</div>'

    detail_panels = []
    context_panels = []
    for view in thread_views:
        thread_id = view["thread_id"]
        visible = view["visible"]
        messages_for_thread = view["messages"]
        latest_for_thread = view["latest"]
        latest_meta_for_thread = view["latest_meta"]
        title = str(visible[0].get("title", "(no title)")) if visible else "暂无 Thread"
        state = "处理中" if any(
            (message.get("state") or {}).get("thread_state", "open") == "open"
            for message in visible
        ) else "已归档"
        session_count = len({
            str(message["meta"].get("origin_session_id"))
            for message in messages_for_thread
            if message["meta"].get("origin_session_id")
        })
        hidden = "" if thread_id == selected_id else " hidden"
        detail_panels.append(
            f'<section class="thread-detail" data-thread-id="{escape(thread_id)}"{hidden}>'
            f'<div class="detail-head"><h2>{escape(title)}</h2><span class="badge">{state}</span>'
            f'<small>{len(messages_for_thread)} Messages · {session_count} Sessions</small></div>'
            f'{render_message_blocks(messages_for_thread)}</section>'
        )
        files = view["files"]
        files_html = "".join(f"<li>{escape(str(item))}</li>" for item in files) or "<li>未记录文件</li>"
        context_panels.append(
            f'<section class="thread-context" data-thread-id="{escape(thread_id)}"{hidden}>'
            f'<h3>当前消息</h3><dl><dt>Agent</dt><dd>{escape(str(latest_meta_for_thread.get("from", "-")))}</dd>'
            f'<dt>Session</dt><dd>{escape(str(latest_meta_for_thread.get("origin_session_id") or "-"))}</dd>'
            f'<dt>原因</dt><dd>{escape(reason_labels.get(str(latest_meta_for_thread.get("delivery_reason", "direct")), "• direct"))}</dd>'
            f'<dt>范围</dt><dd>{escape(str(view["scope"] or "-"))}</dd></dl><hr><h3>关联文件</h3><ul>{files_html}</ul>'
            f'</section>'
        )
    generated = escape(iso_now())
    html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKS Mail · Compact Inbox</title>
<style>
:root{{color-scheme:light;--ink:#18233d;--muted:#657590;--line:#dce3ef;--surface:#fff;--wash:#f6f8fc;--purple:#7250c8;--soft:#f1edff;--green:#26975b;--orange:#ef8a32}}
*{{box-sizing:border-box}}body{{margin:0;background:#f8faff;color:var(--ink);font:15px/1.55 "Segoe UI","Microsoft YaHei",sans-serif}}
.app{{max-width:1500px;margin:32px auto;background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:0 16px 50px #18233d14}}
.top{{height:70px;background:var(--ink);color:#fff;display:flex;align-items:center;gap:34px;padding:0 30px}}.top strong{{font-size:21px}}.top span{{color:#c8d3e8}}.top time{{margin-left:auto;color:#c8d3e8;font-size:13px}}
.workspace{{display:grid;grid-template-columns:220px 360px minmax(420px,1fr) 270px;min-height:650px}}.nav{{background:var(--wash);padding:28px 24px;border-right:1px solid var(--line)}}
.nav h2,.threads h2,.detail h2,.context h2{{margin:0 0 24px;font-size:20px}}.nav-label{{color:var(--muted);font-size:13px;margin:22px 0 8px}}.nav p{{margin:13px 0;font-size:16px}}.num{{color:var(--purple);font-weight:700}}.nav-note{{margin-top:150px;color:var(--muted);font-size:13px}}.nav-note code{{color:var(--purple);font-weight:700}}
 .threads{{border-right:1px solid var(--line);padding:28px 16px}}.thread-row{{display:flex;width:100%;gap:12px;align-items:flex-start;padding:16px 12px;margin:5px 0;border:0;border-radius:12px;background:transparent;color:var(--ink);font:inherit;text-align:left;cursor:pointer}}.thread-row.selected{{background:var(--soft)}}.thread-row:hover{{background:var(--wash)}}.thread-row:focus-visible{{outline:2px solid var(--purple);outline-offset:2px}}.dot{{width:11px;height:11px;border-radius:50%;margin-top:6px;flex:none;background:var(--green)}}.dot.unread{{background:var(--purple)}}.thread-copy{{display:flex;flex-direction:column;min-width:0;flex:1}}.thread-copy strong{{font-size:16px}}.thread-copy small{{color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.thread-row time{{font-size:12px;color:var(--muted);white-space:nowrap}}
 .detail{{padding:28px 32px;min-width:0}}.thread-detail[hidden],.thread-context[hidden]{{display:none}}.detail-head{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:23px}}.detail-head h2{{margin:0}}.badge{{background:var(--soft);color:var(--purple);padding:4px 12px;border-radius:15px;font-weight:700;font-size:13px}}.detail-head small{{color:var(--muted)}}.session-label{{color:#52627d;font-weight:700;font-size:13px;margin:19px 0 8px}}.message-card{{background:var(--wash);border-radius:12px;padding:17px 20px;margin-bottom:18px}}.message-card.accent{{background:var(--soft)}}.message-card h3{{font-size:17px;margin:0 0 8px}}.message-card p{{margin:0 0 12px;white-space:pre-wrap}}.message-card small{{color:var(--muted)}}.empty{{padding:50px;text-align:center;color:var(--muted)}}
 .context{{border-left:1px solid var(--line);padding:28px 24px}}.context h3{{font-size:14px;color:var(--muted);font-weight:500;margin:0 0 10px}}.context dl{{display:grid;grid-template-columns:70px 1fr;gap:12px 10px;margin:0 0 26px}}.context dt{{color:var(--muted)}}.context dd{{margin:0;overflow-wrap:anywhere}}.context hr{{border:0;border-top:1px solid var(--line);margin:22px 0}}.context ul{{padding-left:18px;color:var(--purple);font-weight:600}}.readonly{{margin-top:30px;border:1px solid var(--line);border-radius:10px;padding:12px;text-align:center;font-weight:700;color:var(--ink)}}
@media(max-width:1100px){{.workspace{{grid-template-columns:190px 300px minmax(380px,1fr)}}.context{{grid-column:2 / -1;border-left:0;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr;gap:20px}}.context h2{{grid-column:1 / -1}}.readonly{{margin-top:0}}}}
@media(max-width:760px){{.app{{margin:0;border-radius:0;border-left:0;border-right:0}}.top{{padding:0 18px;gap:14px}}.top span,.top time{{display:none}}.workspace{{display:block}}.nav,.threads,.detail,.context{{border:0;border-bottom:1px solid var(--line)}}.nav{{padding:20px}}.nav-note{{margin-top:25px}}.threads{{padding:20px 12px}}.detail{{padding:24px 18px}}.context{{display:block;padding:24px 18px}}}}
</style></head><body><main class="app"><header class="top"><strong>OKS Mail</strong><span>项目：{escape(str(root.name))}</span><time>快照生成于 {generated} · 只读</time></header>
 <section class="workspace"><aside class="nav"><h2>视图</h2><p>收件箱 <span class="num">{len(messages)}</span></p><p>未读 <span class="num">{unread_count}</span></p><p>待处理 <span class="num">{open_count}</span></p><p>已发送</p><p>已归档</p><div class="nav-label">范围</div><p>当前 Agent：<strong>{escape(_normalise_agent(agent_id))}</strong></p><p>全部 Thread</p><div class="nav-note">写操作仍通过 CLI<br><code>reply · read · archive</code></div></aside>
 <section class="threads"><h2>线程</h2>{''.join(thread_rows) or '<div class="empty">暂无 Thread</div>'}</section>
 <section class="detail">{''.join(detail_panels) or '<div class="empty">当前 Agent 没有可显示的 Mail。</div>'}</section>
 <aside class="context"><h2>来源与上下文</h2>{''.join(context_panels) or '<div class="empty">当前 Agent 没有可显示的 Mail。</div>'}<div class="readonly">只读快照 · 通过 CLI 操作</div></aside></section></main>
 <script>
 (() => {{
   const rows = Array.from(document.querySelectorAll('.thread-row[data-thread-id]'));
   const panels = Array.from(document.querySelectorAll('.thread-detail[data-thread-id]'));
   const contexts = Array.from(document.querySelectorAll('.thread-context[data-thread-id]'));
   const selectThread = (id) => {{
     rows.forEach(row => {{
       const active = row.dataset.threadId === id;
       row.classList.toggle('selected', active);
       row.setAttribute('aria-pressed', String(active));
     }});
     panels.forEach(panel => {{ panel.hidden = panel.dataset.threadId !== id; }});
     contexts.forEach(context => {{ context.hidden = context.dataset.threadId !== id; }});
   }};
   rows.forEach(row => row.addEventListener('click', () => selectThread(row.dataset.threadId)));
 }})();
 </script></body></html>'''
    output = Path(output)
    store._atomic_write(output, html)
    return output
