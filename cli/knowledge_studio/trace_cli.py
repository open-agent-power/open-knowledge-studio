"""`oks trace` — append-only execution traces and external/human judgements.

Split out of `cli.py` as a verbatim move (B4-2). The Typer instance lives here
so that `cli.py` only has to `add_typer` it; every command body is byte-identical
to the pre-split version, which `block_equivalence.py` verifies via AST.
"""
from __future__ import annotations

from knowledge_studio.output import emit_json as _emit_json

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from knowledge_studio import store
from knowledge_studio.instance_cli import _instance_root

console = Console()

trace_app = typer.Typer(help="Append-only execution traces and feedback.")


def _parse_json_object(value: str, option: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        console.print(f"[red]{option} must be valid JSON: {e}[/red]")
        raise typer.Exit(2)
    if not isinstance(parsed, dict):
        console.print(f"[red]{option} must be a JSON object[/red]")
        raise typer.Exit(2)
    return parsed


def _append_trace_feedback_jsonl(root: Path, run_id: str, outcome: str, comment: str) -> None:
    """Append human feedback to records/trace-feedback.jsonl (git-shared)."""
    from datetime import datetime, timezone
    path = root / "records" / "trace-feedback.jsonl"
    rec = {
        "run_id": run_id,
        "outcome": outcome,
        "comment": comment,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        store._append_jsonl(
            path,
            rec,
            lock_path=root / ".oks" / "locks" / "trace-feedback.lock",
        )
    except Exception:
        pass


@trace_app.command("start")
def trace_start(
    goal_id: str = typer.Argument(help="Goal identifier"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Stable run identifier"),
):
    """Start an execution trace with a goal event."""
    from knowledge_studio.trace import start_trace

    try:
        result = start_trace(goal_id, run_id)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(result)


@trace_app.command("append")
def trace_append(
    run_id: str = typer.Argument(help="Run identifier"),
    event_type: str = typer.Option(..., "--type", help="Trace event type"),
    actor: str = typer.Option(..., "--actor", help="agent | judge | human | tool | system"),
    payload: str = typer.Option("{}", "--payload", help="JSON object without secrets"),
    evidence: list[str] = typer.Option([], "--evidence", help="Repeatable evidence reference"),
):
    """Append one typed event to a running trace."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, event_type, actor, _parse_json_object(payload, "--payload"), evidence)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(event)


@trace_app.command("judge")
def trace_judge(
    run_id: str = typer.Argument(help="Run identifier"),
    outcome: str = typer.Option(..., "--outcome", help="pass | fail | uncertain"),
    comment: str = typer.Option(..., "--comment", help="Judge rationale"),
):
    """Record an external or deterministic judge result."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "judge_comment", "judge", {"outcome": outcome, "comment": comment})
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(event)


@trace_app.command("feedback")
def trace_feedback(
    run_id: str = typer.Argument(help="Run identifier"),
    outcome: str = typer.Option(..., "--outcome", help="accepted | rejected | needs_changes"),
    comment: str = typer.Option(..., "--comment", help="Human feedback"),
):
    """Record human feedback without changing formal knowledge."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "human_comment", "human", {"outcome": outcome, "comment": comment})
        root = _instance_root(None)
        _append_trace_feedback_jsonl(root, run_id, outcome, comment)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(event)


@trace_app.command("blocker")
def trace_blocker(
    run_id: str = typer.Argument(help="Run identifier"),
    reason: str = typer.Option(..., "--reason", help="Why execution cannot continue"),
    needed: str = typer.Option(..., "--needed", help="Condition required to resume"),
):
    """Record a blocker and the exact condition needed to resume."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "blocker", "agent", {"reason": reason, "needed": needed})
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(event)


@trace_app.command("propose")
def trace_propose(
    run_id: str = typer.Argument(help="Run identifier"),
    kind: str = typer.Option(..., "--kind", help="wiki | skill"),
    title: str = typer.Option(..., "--title", help="Proposal title"),
    summary: str = typer.Option(..., "--summary", help="Proposed content summary"),
):
    """Write a review-only proposal under drafts/proposals/."""
    from knowledge_studio.proposals import create_proposal

    try:
        path = create_proposal(run_id, kind, title, summary)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json({"path": str(path), "applied": False})


@trace_app.command("finish")
def trace_finish(
    run_id: str = typer.Argument(help="Run identifier"),
    result: str = typer.Option(..., "--result", help="Final result JSON object"),
):
    """Finish a trace with exactly one final_result event."""
    from knowledge_studio.trace import finish_trace

    try:
        manifest = finish_trace(run_id, _parse_json_object(result, "--result"))
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(manifest)


@trace_app.command("validate")
def trace_validate(
    run_id: str = typer.Argument(help="Run identifier"),
    completed: bool = typer.Option(False, "--completed", help="Require a completed run"),
):
    """Validate event ordering, types, manifest consistency, and secret safety."""
    from knowledge_studio.trace import validate_trace

    try:
        result = validate_trace(run_id, require_completed=completed)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(result)
    if not result["valid"]:
        raise typer.Exit(1)


@trace_app.command("show")
def trace_show(run_id: str = typer.Argument(help="Run identifier")):
    """Print a trace and its manifest as JSON."""
    from knowledge_studio.trace import show_trace

    try:
        _emit_json(show_trace(run_id))
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
