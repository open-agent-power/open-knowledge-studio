"""Explicit task reminder controls. Times always carry an offset."""
import json
from typing import Optional
import typer
from . import reminders, store

app = typer.Typer(help='Goal-bound session reminders; no background wake.')


def _run(call):
    try:
        typer.echo(json.dumps(call(), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2)


@app.command('add')
def add(task_id: str, reminder_id: str, text: str = typer.Option(..., '--text'), at: str = typer.Option(..., '--at'), agreement: str = typer.Option(..., '--agreement-sha256')):
    _run(lambda: reminders.add(store.repo_root(), dict(task_id=task_id, id=reminder_id, note=text, due_at=at, expected_agreement_sha256=agreement)))


@app.command('list')
def listing(task_id: str):
    _run(lambda: reminders.listing(store.repo_root(), task_id))


@app.command('update')
def update(task_id: str, reminder_id: str, action: str, revision: int = typer.Option(..., '--revision'), at: Optional[str] = typer.Option(None, '--at'), agreement: Optional[str] = typer.Option(None, '--agreement-sha256')):
    _run(lambda: reminders.update(store.repo_root(), dict(task_id=task_id, id=reminder_id, action=action, expected_revision=revision, due_at=at, expected_agreement_sha256=agreement)))
