"""`oks eval` — offline recall evaluation and run comparison.

Split out of `cli.py` as a verbatim move (B4-6c). `_validate_output_format`
stays in cli.py (shared with `recall`) and is reached through a delegation shim.
Source text was extracted programmatically.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from knowledge_studio import store
from knowledge_studio.instance_cli import _instance_root

console = Console()


def _emit_json(data) -> None:
    """Delegate to cli.py so JSON output stays byte-identical everywhere."""
    from .cli import _emit_json as emit

    return emit(data)



eval_app = typer.Typer(help="Offline recall evaluation and run comparison.")


def _validate_output_format(value: str) -> str:
    """Delegate to cli.py — the recall command shares the same validation rule."""
    from .cli import _validate_output_format as validate

    return validate(value)


@eval_app.command('candidates')
def eval_candidates():
    from .evaluation_feedback import candidates
    _emit_json(candidates(_instance_root(None)))


@eval_app.command('capture')
def eval_capture(enabled: bool = typer.Option(True, '--enabled/--disabled'),
                 retain_query: bool = typer.Option(False, '--retain-query/--hash-query')):
    from .evaluation_feedback import configure
    _emit_json(configure(_instance_root(None), {'values': {'capture_enabled': enabled, 'retain_query': retain_query}}))


@eval_app.command('review')
def eval_review(identifier: str, query: str = typer.Option(..., '--query'),
                accept: Optional[list[str]] = typer.Option(None, '--accept'),
                reject: Optional[list[str]] = typer.Option(None, '--reject'),
                clear: Optional[list[str]] = typer.Option(None, '--clear'),
                reason: str = typer.Option('', '--reason'), confirm: bool = typer.Option(False, '--confirm'),
                derived_query: bool = typer.Option(False, '--derived-query')):
    """Explicitly accept/reject knowledge for one observed query; missing labels remain unknown."""
    from .evaluation_feedback import review
    try:
        _emit_json(review(_instance_root(None), {'id': identifier, 'query': query, 'accept': accept or [],
            'reject': reject or [], 'clear': clear or [], 'reason': reason, 'confirm': confirm, 'derived_query': derived_query}))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))


@eval_app.command('export')
def eval_export(name: str = typer.Option(..., '--name'), kind: str = typer.Option('recall', '--kind'),
                case: Optional[list[str]] = typer.Option(None, '--case')):
    from .evaluation_feedback import export
    try:
        _emit_json(export(_instance_root(None), {'name': name, 'kind': kind, 'ids': case}))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))

@eval_app.command("recall")
def eval_recall(
    dataset: Path = typer.Argument(help="YAML recall dataset"),
    output: Path = typer.Option(..., "--output", "-o", help="Output run JSON"),
    limit: int = typer.Option(5, "--limit", "-n", min=5, help="Retrieved items per case (>=5 keeps recall@5 meaningful)"),
    search_backend: Optional[str] = typer.Option(None, "--search-backend", help="Override recall.yaml (fts5/native/fusion) for ablation"),
    split: Optional[str] = typer.Option(None, "--split", help="v2 dataset split: train, validation or test; required for mixed datasets"),
):
    """Run a read-only Wiki recall evaluation; v2 adds fixture-label audits."""
    from knowledge_studio.evaluation import run_evaluation

    try:
        result = run_evaluation(dataset, output, limit=limit, search_backend=search_backend, split=split)
    except (OSError, ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    summary = {"output": str(output.resolve()), "metrics": result["metrics"]}
    if "evaluation_mode" in result["manifest"]:
        summary.update(evaluation_mode=result["manifest"]["evaluation_mode"], split=result["manifest"]["split"])
    _emit_json(summary)


@eval_app.command("compare")
def eval_compare(
    baseline: Path = typer.Argument(help="Baseline run JSON"),
    candidate: Path = typer.Argument(help="Candidate run JSON"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Optional comparison JSON"),
    vary: Optional[list[str]] = typer.Option(None, "--vary", help="Intentional variable: code, backend, settings or parameters; repeat as needed"),
):
    """Compare runs with matching dataset, knowledge and configuration snapshots."""
    from knowledge_studio.evaluation import compare_runs

    try:
        result = compare_runs(baseline, candidate, output, vary=vary or ())
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(result)
