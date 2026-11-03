"""Explicit JSON requests keep feedback/review operations reproducible."""
from pathlib import Path
import json
from typing import Optional

import typer

from . import feedback, store
from .handoff_cli import load_agreement

app = typer.Typer(help="Explicit private feedback, candidate review and withdrawal. Scope labels are not authentication.")


def _request(path):
    with path.open("rb") as handle:
        raw = handle.read(feedback.MAX_BYTES + 1)
    if len(raw) > feedback.MAX_BYTES:
        raise ValueError("Request exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Request must be a JSON object")
    return value


def _run(call):
    try:
        result = call()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False), err=True)
        raise typer.Exit(2)


@app.command("record")
def record(request: Path):
    """Record explicit adopted/revised/rejected/observed feedback from a JSON file."""
    _run(lambda: feedback.record(store.repo_root(), _request(request)))


@app.command("propose")
def propose(request: Path):
    """Create a private pending candidate from explicit event IDs."""
    _run(lambda: feedback.propose(store.repo_root(), _request(request)))


@app.command("review")
def review(request: Path):
    """Approve/reject the exact inspected revision; never promote automatically."""
    _run(lambda: feedback.review(store.repo_root(), _request(request)))


@app.command("withdraw")
def withdraw(request: Path):
    """Withdraw one event; dependent candidates immediately become ineligible."""
    _run(lambda: feedback.withdraw(store.repo_root(), _request(request)))


@app.command("list")
def inspect(subject: Optional[str] = None, project: Optional[str] = None, task: Optional[str] = None):
    """Inspect one exact scope; never enumerate other subjects/projects/tasks."""
    selection = {"subject": subject, "project": project, "task": task} if any((subject, project, task)) else None
    _run(lambda: feedback.inspect(store.repo_root(), selection))


@app.command("context")
def context(agreement: Path, subject: str, project: str, task: str):
    """Read current approved candidates; no persisted consumption cache."""
    _run(lambda: {"candidates": feedback.context(store.repo_root(), {"subject": subject, "project": project, "task": task}, load_agreement(agreement))})


@app.command("export")
def export(request: Path, confirm_share: bool = typer.Option(False, "--confirm-share")):
    """Explicitly share candidate summary as a Draft for normal human promotion."""
    _run(lambda: feedback.export(store.repo_root(), _request(request), confirm_share=confirm_share))


@app.command("forget")
def forget(request: Path, confirm: bool = typer.Option(False, "--confirm")):
    """Erase private content in an exact scope; disclose retained/exported copies."""
    def execute():
        if not confirm:
            raise ValueError("--confirm is required to erase this scope's private content")
        return feedback.forget(store.repo_root(), _request(request).get("scope"))
    _run(execute)
