"""Explicit, workspace-scoped connection commands for daily sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import shlex

import typer

from . import daily_learning, daily_sources, store, tasks

app = typer.Typer(help='Connect actual daily conversations and readings to Raw and pending knowledge.', no_args_is_help=True)


def _wire_claude(root, workspace):
    from .cli import _asset_source
    assets = _asset_source()
    if assets is None:
        raise ValueError('Hook assets unavailable')
    settings_path = tasks._inside(workspace, '.claude/settings.local.json')
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig')) if settings_path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get('hooks', {}), dict):
        raise ValueError('Existing Claude settings require review')
    hook_path = tasks._inside(workspace, '.claude/hooks/daily-capture.py')
    package_root = str(Path(__file__).resolve().parent.parent)
    # Claude's command hooks run through a shell, including Git Bash on Windows.
    # Use forward slashes and shell quoting rather than CreateProcess quoting.
    command = shlex.join([Path(sys.executable).as_posix(), hook_path.as_posix(), '--kb', Path(root).as_posix(), '--package', Path(package_root).as_posix()])
    handler = {'type': 'command', 'command': command}
    hooks = settings.setdefault('hooks', {})
    events = ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop']
    for event in events:
        groups = hooks.get(event, [])
        if not isinstance(groups, list) or any(not isinstance(x, dict) or not isinstance(x.get('hooks', []), list) for x in groups):
            raise ValueError('Existing Claude hook groups require review')
    if settings_path.exists():
        backup = settings_path.with_name('settings.local.before-daily-' + hashlib.sha256(settings_path.read_bytes()).hexdigest()[:12] + '.json')
        if not backup.exists():
            store._atomic_write(backup, settings_path.read_bytes())
    store._atomic_write(hook_path, (assets / 'hooks/daily-capture.py').read_bytes())
    for event in events:
        groups = hooks.setdefault(event, [])
        found = False
        for group in groups:
            for index, item in enumerate(group.get('hooks', [])):
                if isinstance(item, dict) and ('daily-capture.py' in str(item.get('command', '')) or any('daily-capture.py' in str(arg) for arg in item.get('args', []))):
                    group['hooks'][index] = handler.copy(); found = True
        if not found:
            groups.append({'hooks': [handler.copy()]})
    store._atomic_write(settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')


@app.command('connect')
def connect(host: str = typer.Option(...), workspace: Path = typer.Option(...),
            path: Path = typer.Option(..., help='Independent knowledge base'),
            transcript: Path | None = typer.Option(None), from_offset: int | None = typer.Option(None),
            label: str = typer.Option(''), learning: bool = typer.Option(True, '--learning/--no-learning'),
            claude_path: Path | None = typer.Option(None)):
    root, workspace = path.resolve(), workspace.resolve()
    if not workspace.is_dir() or not all((root / x).is_dir() for x in ['raw', 'drafts', 'wiki']):
        raise typer.BadParameter('Existing workspace and knowledge base are required')
    if host not in {'claude', 'codex'}:
        raise typer.BadParameter('Use claude or codex')
    if host == 'codex' and transcript is None:
        raise typer.BadParameter('Provide the exact authorized Codex transcript')
    if host == 'claude' and (workspace == root or workspace in root.parents or root in workspace.parents):
        raise typer.BadParameter('Claude workspace and knowledge base must not overlap')
    daily_sources.load_config(root)  # Validate existing config before installing hooks.
    source_id = host + '-' + hashlib.sha256((str(workspace) + str(transcript or '')).encode()).hexdigest()[:18]
    source = {'id': source_id, 'host': host, 'workspace': str(workspace), 'label': label or workspace.name,
              'kind': 'codex-transcript' if host == 'codex' else 'claude-workspace'}
    if transcript is not None:
        source['path'] = str(transcript.resolve())
    if from_offset is not None:
        source['start_offset'] = from_offset
    if host == 'claude':
        source['read_roots'] = [str(workspace)]
        _wire_claude(root, workspace)
    result = daily_sources.connect_source(root, source)
    config = daily_sources.load_config(root)
    config['enabled'] = True
    config['learning'] = {**config.get('learning', {}), 'enabled': learning,
                          **({'claude_path': str(claude_path.resolve())} if claude_path else {})}
    store._atomic_write(tasks._inside(root, daily_sources.CONFIG), json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command('status')
def status(path: Path = typer.Option(...)):
    typer.echo(json.dumps(daily_learning.overview(path.resolve()), ensure_ascii=False, indent=2))


@app.command('sync')
def sync(path: Path = typer.Option(...)):
    typer.echo(json.dumps(daily_sources.sync(path.resolve()), ensure_ascii=False, indent=2))


@app.command('extract')
def extract(path: Path = typer.Option(...)):
    typer.echo(json.dumps(daily_learning.process_pending(path.resolve(), force=True), ensure_ascii=False, indent=2))


@app.command('retry')
def retry(entry_id: str, path: Path = typer.Option(...)):
    """Requeue the exact failed batch; completed decisions stay closed."""
    typer.echo(json.dumps(daily_learning.retry(path.resolve(), entry_id), ensure_ascii=False))
