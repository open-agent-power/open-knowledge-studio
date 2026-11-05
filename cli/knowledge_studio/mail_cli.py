"""Mail and terminal-registry commands backed by the existing domain services."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from . import mail as mail_domain, store
from .cli_common import emit_json, instance_root

console = Console()


mail_app = typer.Typer(help="Agent-to-agent mail (inbox/sent).")

registry_app = typer.Typer(help="Terminal registry (agent+cwd -> profile/goal).")

_UNSAFE_AGENT_ID_CHARS = '/\\:*?"<>|\0\n\r'

_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

def _is_safe_agent_id(agent_id: str) -> bool:
    """Whether *agent_id* can serve as one portable path component."""
    if agent_id in {".", ".."} or not agent_id.strip():
        return False
    if any(char in _UNSAFE_AGENT_ID_CHARS for char in agent_id):
        return False
    # ``CON`` is reserved and so is ``CON.txt``: compare the stem.
    return agent_id.split(".")[0].lower() not in _WINDOWS_RESERVED_NAMES

def _mail_agent_id(explicit: str = "") -> str:
    """Resolve the sender identity without ever claiming to be the human.

    Order: ``--from`` > ``OKS_AGENT_ID`` > the host session signal. An
    environment that resolves to nothing returns ``"unknown"`` (which
    normalises to ``sender_kind="agent"``): ``human`` is the review gate in
    the OKS pipeline, so an unset environment must not silently sign mail as
    the highest-trust identity.
    """
    for candidate in (explicit, os.environ.get("OKS_AGENT_ID", "")):
        agent_id = candidate.strip()
        if not agent_id:
            continue
        # The id is interpolated into mail/sent/{id}/ and into the inbox slug,
        # so it must be one portable path component.
        if not _is_safe_agent_id(agent_id):
            console.print(f"[red]Invalid agent id:[/red] {agent_id!r}")
            raise typer.Exit(1)
        return agent_id
    # Native Claude launches child shell commands without the OKS-specific
    # identity override. Reuse the host signal already consumed by the
    # UserPromptSubmit hook so ack/reply commands keep the same Agent scope.
    if os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip() or os.environ.get("CLAUDECODE", "").strip():
        return "claude"
    if os.environ.get("CODEX_SESSION_ID", "").strip() or os.environ.get("CODEX_CLI", "").strip():
        return "codex"
    return "unknown"

def _mail_session_id(value: str = "") -> str:
    return (
        value.strip()
        or os.environ.get("OKS_SESSION_ID", "").strip()
        or os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        or os.environ.get("CODEX_SESSION_ID", "").strip()
    )

def _mail_machine_id(value: str = "") -> str:
    return mail_domain.machine_id(value)

def _mail_evidence_refs(values: list[str]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for raw in values:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("--evidence-ref must be valid JSON") from exc
        refs.append(parsed)
    return mail_domain.normalise_evidence_refs(refs)

def _mail_action_result(result: dict[str, Any], *, sender_kind: str, notify: bool) -> dict[str, Any]:
    """Return the stable, host-facing result for a file-backed send/reply."""
    return {
        "schema": "mail.action.v1",
        "message_id": str(result["message_id"]),
        "thread_id": str(result["thread_id"]),
        "recipients": [str(recipient) for recipient in result["recipients"]],
        "sender_kind": sender_kind,
        "origin_machine_id": str(result.get("meta", {}).get("origin_machine_id", "unknown")),
        "record_kind": str(result.get("meta", {}).get("record_kind", "message")),
        "evidence_refs": result.get("evidence_refs", []),
        "attention": {
            "requested": notify,
            "status": "queued" if notify else "not_requested",
            "wake_supported": False,
        },
    }

def _emit_mail_action(result: dict[str, Any], *, sender_kind: str, notify: bool, output_format: str, text: str) -> None:
    if output_format.strip().lower() == "json":
        print(json.dumps(_mail_action_result(result, sender_kind=sender_kind, notify=notify), ensure_ascii=False))
        return
    if output_format.strip().lower() != "text":
        console.print("[red]format must be text or json[/red]")
        raise typer.Exit(2)
    console.print(text)

@mail_app.command("send")
def mail_send(
    body: str = typer.Option(..., "--body", "-b", help="Mail body text"),
    to: str = typer.Option("@all", "--to", help="Recipient (@all or @agent-id)"),
    from_agent: str = typer.Option("", "--from", help="Sender identity (default: resolve from the environment)"),
    type: str = typer.Option("message", "--type", help="message | conflict | handoff"),
    title: str = typer.Option("", "--title", "-t", help="Mail title"),
    priority: str = typer.Option("normal", "--priority", help="normal | urgent"),
    thread: str = typer.Option("", "--thread", help="Existing Thread ID (for a reply)"),
    session_id: str = typer.Option("", "--session-id", help="Originating Agent session ID"),
    delivery_reason: str = typer.Option("direct", "--delivery-reason", help="direct | conflict | review_request | handoff | system"),
    record_kind: str = typer.Option("message", "--record-kind", help="message | goal | handoff | result | blocked | note | knowledge_ref | review_request | acknowledgement"),
    notify: bool = typer.Option(False, "--notify/--no-notify", help="Request host notification; safe queued fallback when unsupported"),
    session_policy: str = typer.Option("next_prompt", "--session-policy", help="next_prompt | wait | notify"),
    sender_kind: str = typer.Option("", "--sender-kind", help="Message provenance: human | agent | unknown"),
    evidence_ref: list[str] = typer.Option([], "--evidence-ref", help="Evidence ref JSON object; repeatable"),
    output_format: str = typer.Option("text", "--format", help="text | json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Write one canonical message and recipient projections."""
    root = instance_root(path)
    sender = _mail_agent_id(from_agent)
    try:
        resolved_sender_kind = mail_domain.normalise_sender_kind(sender_kind, sender)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    try:
        refs = _mail_evidence_refs(evidence_ref)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    sid = _mail_session_id(session_id)
    mid = _mail_machine_id()
    if sid:
        mail_domain.register_session(root, sid, sender, os.getcwd(), machine_id=mid)
    try:
        result = mail_domain.write_message(
            root,
            body=body,
            sender=sender,
            sender_kind=resolved_sender_kind,
            recipients=to,
            title=title,
            kind=type,
            priority=priority,
            thread_id=thread,
            origin_session_id=sid,
            origin_machine_id=mid,
            evidence_refs=refs,
            delivery_reason=delivery_reason,
            record_kind=record_kind,
            notify=notify,
            session_policy=session_policy,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    _emit_mail_action(
        result,
        sender_kind=resolved_sender_kind,
        notify=notify,
        output_format=output_format,
        text=(
            f"[green]Sent mail:[/green] {result['message_id']} "
            f"(thread {result['thread_id']}) -> {', '.join(result['recipients'])}"
        ),
    )

@mail_app.command("delegate")
def mail_delegate(
    task: str = typer.Option(..., "--task", help="Task intent for the receiving Agent"),
    to: str = typer.Option(..., "--to", help="Recipient Agent ID (for example codex; @ is optional)"),
    title: str = typer.Option("", "--title", "-t", help="Handoff title"),
    context: str = typer.Option("", "--context", help="Relevant context, files, or prior decisions"),
    acceptance: str = typer.Option("", "--acceptance", help="Observable acceptance criteria"),
    agreement: Optional[Path] = typer.Option(None, "--agreement", help="JSON snapshot from oks handoff prepare"),
    session_id: str = typer.Option("", "--session-id", help="Originating Agent session ID"),
    notify: bool = typer.Option(False, "--notify/--no-notify", help="Request host notification; safe queued fallback when unsupported"),
    sender_kind: str = typer.Option("agent", "--sender-kind", help="Message provenance: human | agent | unknown"),
    evidence_ref: list[str] = typer.Option([], "--evidence-ref", help="Evidence ref JSON object; repeatable"),
    output_format: str = typer.Option("text", "--format", help="text | json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Submit a task handoff without requiring callers to assemble Mail fields."""
    root = instance_root(path)
    sender = _mail_agent_id()
    try:
        resolved_sender_kind = mail_domain.normalise_sender_kind(sender_kind, sender)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    try:
        refs = _mail_evidence_refs(evidence_ref)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    sid = _mail_session_id(session_id)
    mid = _mail_machine_id()
    if sid:
        mail_domain.register_session(root, sid, sender, os.getcwd(), machine_id=mid)
    try:
        from knowledge_studio.handoff_cli import load_agreement
        snapshot = load_agreement(agreement) if agreement is not None else None
        result = mail_domain.delegate_message(
            root,
            task=task,
            sender=sender,
            sender_kind=resolved_sender_kind,
            recipients=to,
            title=title,
            context=context,
            acceptance=acceptance,
            origin_session_id=sid,
            origin_machine_id=mid,
            evidence_refs=refs,
            notify=notify,
            agreement=snapshot,
        )
    except (OSError, ValueError, UnicodeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    _emit_mail_action(
        result,
        sender_kind=resolved_sender_kind,
        notify=notify,
        output_format=output_format,
        text=(
            f"[green]Delegated:[/green] {result['message_id']} "
            f"(thread {result['thread_id']}) -> {', '.join(result['recipients'])}"
        ),
    )

def _mail_unread(message: dict[str, Any]) -> bool:
    # `iter_messages(agent_id)` includes the Agent's own canonical messages so
    # a Thread can be rendered end-to-end. They are not inbox items, however,
    # and must never inflate `mail inbox` or `mail count`.
    if message.get("self"):
        return False
    state = message.get("state") or {}
    if state:
        return not state.get("read_at") and not state.get("archived_at")
    return str(message.get("meta", {}).get("read", "false")).lower() != "true"

@mail_app.command("inbox")
def mail_inbox() -> None:
    """List unread messages addressed to the current Agent."""
    root = instance_root(None)
    agent = _mail_agent_id()
    unread = [message for message in mail_domain.iter_messages(root, agent) if _mail_unread(message)]
    if not unread:
        console.print("[dim]No unread mail.[/dim]")
        return
    console.print(f"[bold]Unread mail for @{agent.lstrip('@')} ({len(unread)}):[/bold]")
    for message in unread:
        meta = message["meta"]
        console.print(
            f"  - [cyan]{meta.get('message_id')}[/cyan] "
            f"[dim]{meta.get('thread_id')} · {meta.get('delivery_reason', 'direct')}[/dim]  "
            f"{message['title']}"
        )

@mail_app.command("sent")
def mail_sent() -> None:
    """List messages authored by the current Agent."""
    root = instance_root(None)
    sender = _mail_agent_id().lstrip("@")
    messages = [
        message for message in mail_domain.iter_messages(root)
        if str(message["meta"].get("from", "")).lstrip("@") == sender
    ]
    if not messages:
        console.print("[dim]No sent mail.[/dim]")
        return
    console.print(f"[bold]Sent mail for @{sender} ({len(messages)}):[/bold]")
    for message in messages:
        meta = message["meta"]
        console.print(
            f"  - [cyan]{meta.get('message_id')}[/cyan] "
            f"[dim]{meta.get('thread_id')} · {meta.get('delivery_reason', 'direct')}[/dim]  "
            f"{message['title']} -> {', '.join(meta.get('to', []))}"
        )

@mail_app.command("thread")
def mail_thread(
    thread_id: str = typer.Argument(..., help="Thread ID"),
) -> None:
    """Show all messages in one Thread for the current Agent."""
    root = instance_root(None)
    visible = [m for m in mail_domain.iter_messages(root, _mail_agent_id()) if m["meta"].get("thread_id") == thread_id]
    messages = mail_domain.thread_messages(root, thread_id, _mail_agent_id()) if visible else []
    if not messages:
        console.print(f"[red]Thread not found:[/red] {thread_id}")
        raise typer.Exit(1)
    for message in messages:
        meta = message["meta"]
        console.print(
            f"[bold]{message['title']}[/bold]  [dim]{meta.get('from')} · "
            f"source={meta.get('sender_kind', 'unknown')} · "
            f"session={meta.get('origin_session_id') or '-'} · "
            f"reason={meta.get('delivery_reason', 'direct')}[/dim]\n"
            f"{message['body']}\n"
        )

@mail_app.command("reply")
def mail_reply(
    thread_id: str = typer.Argument(..., help="Thread ID"),
    body: str = typer.Option(..., "--body", "-b", help="Reply body text"),
    to: str = typer.Option("", "--to", help="Optional recipient override"),
    title: str = typer.Option("", "--title", "-t", help="Reply title"),
    session_id: str = typer.Option("", "--session-id", help="Replying Agent session ID"),
    notify: bool = typer.Option(False, "--notify/--no-notify", help="Request host notification"),
    sender_kind: str = typer.Option("", "--sender-kind", help="Message provenance: human | agent | unknown"),
    evidence_ref: list[str] = typer.Option([], "--evidence-ref", help="Evidence ref JSON object; repeatable"),
    record_kind: str = typer.Option("message", "--record-kind", help="message | goal | handoff | result | blocked | note | knowledge_ref | review_request | acknowledgement"),
    output_format: str = typer.Option("text", "--format", help="text | json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Append a message to an existing Thread."""
    root = instance_root(path)
    sender = _mail_agent_id()
    try:
        resolved_sender_kind = mail_domain.normalise_sender_kind(sender_kind, sender)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    try:
        refs = _mail_evidence_refs(evidence_ref)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    visible = [m for m in mail_domain.iter_messages(root, sender) if m["meta"].get("thread_id") == thread_id]
    if not visible:
        console.print(f"[red]Thread not found:[/red] {thread_id}")
        raise typer.Exit(1)
    conversation = mail_domain.thread_messages(root, thread_id, sender)
    latest = conversation[-1]
    recipients = to or ",".join(
        sorted({str(latest["meta"].get("from", ""))} | set(latest["meta"].get("to", [])) - {f"@{sender.lstrip('@')}"})
    )
    if not recipients:
        console.print("[red]No reply recipient; pass --to @agent-id[/red]")
        raise typer.Exit(2)
    sid = _mail_session_id(session_id)
    mid = _mail_machine_id()
    if sid:
        mail_domain.register_session(root, sid, sender, os.getcwd(), machine_id=mid)
    try:
        result = mail_domain.write_message(
            root,
            body=body,
            sender=sender,
            sender_kind=resolved_sender_kind,
            recipients=recipients,
            title=title or f"Re: {latest['title']}",
            kind="message",
            thread_id=thread_id,
            reply_to=str(latest["meta"].get("message_id", "")),
            origin_session_id=sid,
            origin_machine_id=mid,
            evidence_refs=refs,
            delivery_reason="thread_reply",
            record_kind=record_kind,
            notify=notify,
            session_policy="notify" if notify else "next_prompt",
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    _emit_mail_action(
        result,
        sender_kind=resolved_sender_kind,
        notify=notify,
        output_format=output_format,
        text=f"[green]Replied:[/green] {result['message_id']} (thread {thread_id})",
    )

@mail_app.command("read")
def mail_read(
    id: str = typer.Argument(..., help="Message ID or legacy mail slug"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Mark a message read for the current Agent only."""
    root = instance_root(path)
    agent = _mail_agent_id()
    found = next((m for m in mail_domain.iter_messages(root, agent) if m["meta"].get("message_id") == id or m["path"].stem == id), None)
    if not found:
        console.print(f"[red]Mail not found:[/red] {id}")
        raise typer.Exit(1)
    # Read state is per-recipient: even for a legacy shared Markdown file that
    # still carries an old `read:` marker, never rewrite the shared file.
    mail_domain.update_recipient_state(
        root, agent, str(found["meta"].get("message_id")), read_at=mail_domain.iso_now()
    )
    console.print(f"[green]Marked read for @{agent.lstrip('@')}:[/green] {id}")

@mail_app.command("count")
def mail_count() -> None:
    """Count unread mail for the current Agent (for hook use)."""
    root = instance_root(None)
    print(sum(1 for message in mail_domain.iter_messages(root, _mail_agent_id()) if _mail_unread(message)))

@mail_app.command("ack")
def mail_ack(
    id: str = typer.Argument(..., help="Message ID"),
    session_id: str = typer.Option(..., "--session-id", help="Explicit Session ID"),
    output_format: str = typer.Option("text", "--format", help="text | json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Acknowledge presentation to one explicit Agent Session."""
    if not session_id.strip():
        console.print("[red]--session-id is required[/red]")
        raise typer.Exit(2)
    if output_format.strip().lower() not in {"text", "json"}:
        console.print("[red]format must be text or json[/red]")
        raise typer.Exit(2)
    root = instance_root(path)
    agent = _mail_agent_id()
    try:
        record = mail_domain.acknowledge_delivery(
            root,
            session_id,
            id,
            agent_id=agent,
            machine_id=_mail_machine_id(),
        )
    except FileNotFoundError:
        console.print(f"[red]Session receipt not found:[/red] {id}")
        raise typer.Exit(1)
    except PermissionError as exc:
        console.print(f"[red]Cannot acknowledge receipt:[/red] {exc}")
        raise typer.Exit(1)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    result = {
        "schema": "mail.receipt.v1",
        "message_id": str(record.get("message_id", id)),
        "thread_id": str(record.get("thread_id", "")),
        "agent_id": str(record.get("agent_id", "")),
        "session_id": str(record.get("session_id", session_id)),
        "machine_id": str(record.get("machine_id", "unknown")),
        "status": str(record.get("status", "acknowledged")),
        "notified_at": record.get("notified_at"),
        "injected_at": record.get("injected_at"),
        "delivered_at": record.get("delivered_at"),
        "acknowledged_at": record.get("acknowledged_at"),
    }
    if output_format.strip().lower() == "json":
        print(json.dumps(result, ensure_ascii=False))
        return
    console.print(
        f"[green]Acknowledged:[/green] {result['message_id']} "
        f"(session {result['session_id']})"
    )

@mail_app.command("archive")
def mail_archive(
    id: str = typer.Argument(..., help="Message ID or Thread ID"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Archive a message or all visible messages in a Thread for this Agent."""
    root = instance_root(path)
    agent = _mail_agent_id()
    visible = list(mail_domain.iter_messages(root, agent))
    selected = [m for m in visible if m["meta"].get("message_id") == id or m["meta"].get("thread_id") == id]
    if not selected:
        console.print(f"[red]Mail or Thread not found:[/red] {id}")
        raise typer.Exit(1)
    archived_at = mail_domain.iso_now()
    for message in selected:
        message_id = str(message["meta"].get("message_id"))
        changes = {"archived_at": archived_at, "thread_state": "closed"}
        if message["path"].parent != mail_domain.messages_dir(root):
            # A legacy Markdown file is shared by every recipient: seed this
            # Agent's projection from the old read marker, but never rewrite
            # the shared file — archiving is recipient-scoped.
            state_path = mail_domain.recipient_state_path(root, agent, message_id)
            if not state_path.is_file() and str(message["meta"].get("read", "false")).lower() == "true":
                changes["read_at"] = (
                    message["meta"].get("read_at")
                    or message["meta"].get("timestamp")
                    or mail_domain.iso_now()
                )
        mail_domain.update_recipient_state(root, agent, message_id, **changes)
    console.print(f"[green]Archived for @{agent.lstrip('@')}:[/green] {id}")

@mail_app.command("setup")
def mail_setup(
    agent: str = typer.Option(..., "--agent", help="Stable identity for this Agent"),
    skills_dir: Path = typer.Option(..., "--skills-dir", help="Host skills directory, e.g. .agents/skills"),
    path: Optional[str] = typer.Option(None, "--path", help="Knowledge base root"),
) -> None:
    """Install the generic oks-mail Skill bound to this KB and Agent."""
    from knowledge_studio.mail_setup import install_skill

    try:
        destination = install_skill(instance_root(path), agent, skills_dir)
    except (ValueError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    console.print(f"Mail Skill installed: {destination}")

@mail_app.command("serve")
def mail_serve(
    path: Optional[str] = typer.Option(None, "--path", help="Knowledge base root"),
    port: int = typer.Option(3182, "--port", min=1, max=65535),
    mode: str = typer.Option("reader", "--mode", help="reader (read-only) or collaboration (legacy write API)"),
    local_review: bool = typer.Option(False, '--local-review', help='Allow local candidate review/export and inspected Draft promotion; Mail remains read-only in reader mode'),
    local_edit: bool = typer.Option(False, '--local-edit', help='Allow local Goal/task creation, bundled Skill draft import and review; Mail remains read-only'),
    background: bool = typer.Option(False, "--background", help="Run independently of this terminal or host session"),
    status: bool = typer.Option(False, "--status", help="Probe the managed server without writing files"),
    stop: bool = typer.Option(False, "--stop", help="Stop only this instance's managed background server"),
) -> None:
    """Serve the real local Mail workspace for a human browser."""
    from knowledge_studio.mail_web import create_server

    if sum((background, status, stop)) > 1:
        raise typer.BadParameter("Choose only one of --background, --status or --stop")
    if (local_review or local_edit) and (background or status or stop):
        raise typer.BadParameter('--local-review / --local-edit are foreground options; run serve without --background, --status or --stop')
    if background or status or stop:
        from knowledge_studio.mail_server import start_background, server_status, stop_background

        operation = start_background if background else (server_status if status else stop_background)
        try:
            result = operation(instance_root(path), port, **({"mode": mode} if background else {}))
        except (ValueError, OSError, RuntimeError) as exc:
            emit_json({"error": str(exc)})
            raise typer.Exit(2)
        emit_json(result)
        return

    try:
        server = create_server(instance_root(path), port, mode=mode, local_review=local_review, local_edit=local_edit)
    except (ValueError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    console.print(f"OKS Mail: http://127.0.0.1:{server.server_port}/ — Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

@mail_app.command("view")
def mail_view(
    output: Path = typer.Option(..., "--output", "-o", help="Standalone HTML output path"),
    agent: str = typer.Option("", "--agent", help="Agent identity (default: OKS_AGENT_ID or human)"),
) -> None:
    """Render a read-only Compact Inbox snapshot; browser actions never write Mail."""
    root = instance_root(None)
    target_agent = agent.strip() or _mail_agent_id()
    path = mail_domain.render_snapshot(root, target_agent, output)
    console.print(f"[green]Mail view written:[/green] {path}")

@mail_app.command("snapshot")
def mail_snapshot(
    output_format: str = typer.Option("json", "--format", help="Output format: json"),
    agent: str = typer.Option("", "--agent", help="Agent identity (default: OKS_AGENT_ID or human)"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Emit a bounded JSON Thread projection for host integrations such as DSH."""
    if output_format.strip().lower() != "json":
        console.print("[red]--format must be json[/red]")
        raise typer.Exit(2)
    root = instance_root(path)
    target_agent = agent.strip() or _mail_agent_id()
    emit_json(mail_domain.snapshot_data(root, target_agent))

@mail_app.command("wait")
def mail_wait(
    timeout: int = typer.Option(0, "--timeout", min=0, max=300, help="Seconds to wait for a new visible message"),
    agent: str = typer.Option("", "--agent", help="Agent identity (default: OKS_AGENT_ID or human)"),
    session_id: str = typer.Option("", "--session-id", help="Runtime session ID"),
    output_format: str = typer.Option("json", "--format", help="Output format: json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
) -> None:
    """Wait for Mail without requiring a host-specific push API."""
    if output_format.strip().lower() != "json":
        console.print("[red]--format must be json[/red]")
        raise typer.Exit(2)
    from knowledge_studio.mail_runtime import FileMailRuntime
    root = instance_root(path)
    runtime = FileMailRuntime(root, agent.strip() or _mail_agent_id(), session_id.strip() or _mail_session_id())
    emit_json(runtime.wait(timeout=timeout))

@registry_app.command("list")
def registry_list() -> None:
    """List terminal registry entries (agent+cwd -> profile/goal)."""
    import json
    root = instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    if not path.is_file():
        console.print("[dim]No registry entries.[/dim]")
        return
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    if not entries:
        console.print("[dim]No registry entries.[/dim]")
        return
    console.print(f"[bold]Terminal registry ({len(entries)} entries):[/bold]")
    for e in entries:
        agent = e.get("agent_id", "?")
        cwd = e.get("cwd", "?")
        profile = e.get("profile_slug", "-")
        goals = ", ".join(e.get("goal_slugs", [])) or "-"
        scope = ", ".join(e.get("scope", [])) or "-"
        last = str(e.get("last_active", "?"))[:19]
        console.print(
            f"  [cyan]{agent}[/cyan] @ [dim]{cwd}[/dim]\n"
            f"    profile: {profile}  goals: {goals}  scope: {scope}  last: {last}"
        )

@registry_app.command("bind")
def registry_bind(
    agent_id: str = typer.Option(..., "--agent-id", help="Agent identity"),
    cwd: str = typer.Option(..., "--cwd", help="Terminal working directory"),
    profile: str = typer.Option("", "--profile", help="Profile slug (profiles/users/)"),
    goals: str = typer.Option("", "--goals", help="Comma-separated goal slugs"),
    scope: str = typer.Option("", "--scope", help="Comma-separated wiki areas to narrow recall (empty = all)"),
) -> None:
    """Bind an agent+cwd to a profile + goals (creates or updates entry)."""
    from datetime import datetime, timezone
    root = instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def update(current: str) -> str:
        lines = []
        found = False
        for line in current.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                    if profile:
                        rec["profile_slug"] = profile
                    if goals:
                        rec["goal_slugs"] = [g.strip() for g in goals.split(",") if g.strip()]
                    if scope:
                        rec["scope"] = [s.strip() for s in scope.split(",") if s.strip()]
                    rec["last_active"] = ts
                    found = True
                    lines.append(json.dumps(rec, ensure_ascii=False))
                else:
                    lines.append(line)
            except Exception:
                lines.append(line)
        if not found:
            rec = {
                "agent_id": agent_id,
                "cwd": cwd,
                "profile_slug": profile,
                "goal_slugs": [g.strip() for g in goals.split(",") if g.strip()],
                "first_seen": ts,
                "last_active": ts,
                "status": "active",
            }
            if scope:
                rec["scope"] = [s.strip() for s in scope.split(",") if s.strip()]
            lines.append(json.dumps(rec, ensure_ascii=False))
        return "\n".join(lines) + "\n"

    store._locked_atomic_update(
        path,
        update,
        lock_path=root / ".oks" / "locks" / "registry.lock",
    )
    console.print(
        f"[green]Bound[/green] {agent_id} @ {cwd}\n"
        f"  profile: {profile or '-'}  goals: {goals or '-'}  scope: {scope or '-'}"
    )

@registry_app.command("remove")
def registry_remove(
    agent_id: str = typer.Option(..., "--agent-id", help="Agent identity"),
    cwd: str = typer.Option(..., "--cwd", help="Terminal working directory"),
) -> None:
    """Remove a registry entry."""
    root = instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    if not path.is_file():
        console.print("[dim]No registry.[/dim]")
        return
    removed = False

    def update(current: str) -> str:
        lines = []
        nonlocal removed
        for line in current.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                    removed = True
                    continue
                lines.append(line)
            except Exception:
                lines.append(line)
        return "\n".join(lines) + "\n"

    store._locked_atomic_update(
        path,
        update,
        lock_path=root / ".oks" / "locks" / "registry.lock",
    )
    if removed:
        console.print(f"[green]Removed[/green] {agent_id} @ {cwd}")
    else:
        console.print(f"[yellow]Not found[/yellow] {agent_id} @ {cwd}")
