"""Scoped installation must be usable by the shell and preserve existing hooks."""
import json
from pathlib import Path
import shlex

from typer.testing import CliRunner

from knowledge_studio import daily_cli


def test_connect_keeps_existing_hooks_and_installs_one_quoted_command(tmp_path):
    root = tmp_path / 'knowledge'; ws = tmp_path / 'work with spaces'
    for name in ['raw', 'drafts', 'wiki']:
        (root / name).mkdir(parents=True)
    (ws / '.claude').mkdir(parents=True)
    settings = ws / '.claude/settings.local.json'
    settings.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'echo existing'}]}]}}))
    args = ['connect', '--host', 'claude', '--workspace', str(ws), '--path', str(root)]
    assert CliRunner().invoke(daily_cli.app, args).exit_code == 0
    assert CliRunner().invoke(daily_cli.app, args).exit_code == 0
    hooks = json.loads(settings.read_text())['hooks']
    stop = [item for group in hooks['Stop'] for item in group['hooks']]
    assert any(item['command'] == 'echo existing' for item in stop)
    capture = [item for item in stop if 'daily-capture.py' in item['command']]
    assert len(capture) == 1 and 'args' not in capture[0]
    argv = shlex.split(capture[0]['command'])
    assert argv[1] == (ws / '.claude/hooks/daily-capture.py').as_posix()
    assert argv[argv.index('--kb') + 1] == root.as_posix()
    assert list((ws / '.claude').glob('settings.local.before-daily-*.json'))


def test_overlapping_workspace_does_not_write_hooks(tmp_path):
    root = tmp_path / 'work' / 'kb'
    for name in ['raw', 'drafts', 'wiki']:
        (root / name).mkdir(parents=True)
    result = CliRunner().invoke(daily_cli.app, ['connect', '--host', 'claude', '--workspace', str(root.parent), '--path', str(root)])
    assert result.exit_code != 0
    assert not (root.parent / '.claude').exists()
