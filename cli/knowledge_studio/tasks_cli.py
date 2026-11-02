"""Agent-friendly task selection and handoff, with no new execution runtime."""
import json
from pathlib import Path
from typing import Optional
import typer
from . import tasks, store

app = typer.Typer(help='Select a task once, save progress, and resume with checked sources.')
from .reminders_cli import app as reminders_app
app.add_typer(reminders_app, name='remind')


def _run(call):
    try:
        value = call()
        typer.echo(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)


@app.command('start')
def start(task_id: str, goal: str = typer.Option(..., '--goal'), wiki: list[str] = typer.Option([], '--wiki')):
    """Create a task from an existing Goal and optional reviewed Wiki paths."""
    _run(lambda: tasks.start(store.repo_root(), task_id, goal, wiki))


@app.command('select')
def select(task_id: str, subject: Optional[str] = None, project: Optional[str] = None):
    """Bind this workspace to a task; optional private feedback needs both labels."""
    _run(lambda: tasks.select(store.repo_root(), Path.cwd(), task_id, subject, project))


@app.command('clear')
def clear():
    _run(lambda: tasks.clear(store.repo_root(), Path.cwd()))


@app.command('show')
def show(task_id: Optional[str] = None):
    def read():
        root = store.repo_root()
        selected = tasks.binding(root, Path.cwd()) if task_id is None else None
        identifier = task_id or (selected or {}).get('task_id')
        return tasks.show(root, identifier) if identifier else {'status': 'no_task_selected'}
    _run(read)


@app.command('list')
def list_cmd():
    _run(lambda: {'tasks': tasks.list_tasks(store.repo_root())})


@app.command('overview')
def overview():
    """Read the bounded task work list, including due reminders and source changes."""
    _run(lambda: tasks.overview(store.repo_root()))


@app.command('complete')
def complete(task_id: str, revision: int = typer.Option(..., '--revision'), reason: str = typer.Option(..., '--reason')):
    """Declare a task completed; does not approve its outputs or Wiki."""
    _run(lambda: tasks.transition(store.repo_root(), task_id, revision, 'complete', reason))


@app.command('cancel')
def cancel(task_id: str, revision: int = typer.Option(..., '--revision'), reason: str = typer.Option(..., '--reason')):
    _run(lambda: tasks.transition(store.repo_root(), task_id, revision, 'cancel', reason))


@app.command('reopen')
def reopen(task_id: str, revision: int = typer.Option(..., '--revision'), reason: str = typer.Option(..., '--reason')):
    """Reopen explicitly, retaining source-review gates and reminder confirmation."""
    _run(lambda: tasks.transition(store.repo_root(), task_id, revision, 'reopen', reason))


@app.command('checkpoint')
def checkpoint(task_id: str, revision: int = typer.Option(..., '--revision'), progress: str = typer.Option(..., '--progress'), next_action: str = typer.Option(..., '--next'), artifact: list[str] = typer.Option([], '--artifact'), retrieval_id: Optional[str] = typer.Option(None, '--retrieval-id'), used_source: list[str] = typer.Option([], '--used-source')):
    """Save progress; optional source/output links are explicit use reports, not execution verification."""
    _run(lambda: tasks.checkpoint(store.repo_root(), task_id, revision, progress, next_action, artifact,
                                  retrieval_id=retrieval_id, used_sources=used_source))


@app.command('refresh')
def refresh(task_id: str, revision: int = typer.Option(..., '--revision'), accept_changes: bool = typer.Option(False, '--accept-changes')):
    def update():
        if not accept_changes:
            raise ValueError('Inspect source changes first; --accept-changes is required')
        return tasks.refresh(store.repo_root(), task_id, revision)
    _run(update)


@app.command('handoff')
def handoff(task_id: str):
    """Print a local handoff document; does not send a message or alter selection."""
    _run(lambda: tasks.export_handoff(store.repo_root(), task_id))


@app.command('sources')
def sources(task_id: str, revision: int = typer.Option(..., '--revision'), wiki: list[str] = typer.Option([], '--wiki'), accept_changes: bool = typer.Option(False, '--accept-changes')):
    """Explicitly change this task's reviewed Wiki references; preserve past revisions."""
    def update():
        if not accept_changes:
            raise ValueError('Inspect the reviewed sources first; --accept-changes is required')
        return tasks.update_sources(store.repo_root(), task_id, revision, wiki)
    _run(update)
