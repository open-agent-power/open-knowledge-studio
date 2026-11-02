"""Bounded local workspace operations; no host configuration or remote writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from itertools import islice
import yaml

from . import handoff, tasks

TEXT_LIMIT = 256 * 1024


def quote(value):
    if os.name == 'nt':
        return "'" + str(value).replace("'", "''") + "'"
    import shlex
    return shlex.quote(str(value))


def diagnostics(root, *, port=3182, local_review=False, local_edit=False):
    from .recall import load_recall_params
    root = root.resolve()
    valid = all((root / name).is_dir() for name in ('wiki', 'mail', 'profiles', 'drafts'))
    code_repo = (root / 'cli/knowledge_studio').is_dir() and (root / 'CONSTITUTION.md').is_file()
    with sqlite3.connect(':memory:') as connection:
        try:
            connection.execute('CREATE VIRTUAL TABLE probe USING fts5(body)')
            fts5 = True
        except sqlite3.OperationalError:
            fts5 = False
    requested = load_recall_params(root).get('search_backend', 'fts5')
    command = f'oks mail serve --path {quote(root)} --port {int(port)}'
    return {'schema_version': 'workspace/v1', 'knowledge_base': str(root),
            'local_edit': bool(local_edit), 'local_review': bool(local_review or local_edit),
            'python': sys.version.split()[0], 'instance_valid': valid and not code_repo,
            'checks': [
                {'name': '知识库', 'status': 'ok' if valid and not code_repo else 'warning',
                 'detail': '独立实例' if valid and not code_repo else '请使用独立知识库保存个人资料',
                 'action': '' if valid and not code_repo else 'oks init <新知识库路径> --no-set-default'},
                {'name': '全文检索', 'status': 'ok' if fts5 else 'warning',
                 'detail': 'SQLite FTS5 可用' if fts5 else 'SQLite FTS5 不可用，首次查询将报告实际回退',
                 'action': '' if fts5 else '使用包含 SQLite FTS5 的 Python 后重新安装 OKS'},
                {'name': '接入方式', 'status': 'ok', 'detail': '本服务由 --path 绑定当前实例',
                 'action': 'oks config show'},
            ],
            'commands': {'init': 'oks init <新知识库路径> --no-set-default',
                         'serve': command,
                         'review': command + ' --local-review',
                         'edit': command + ' --local-edit',
                         'resume': command + (' --local-edit' if local_edit else ' --local-review' if local_review else ''),
                         'recall': 'oks recall "你的问题" --knowledge-only --no-task --format json'},
            'retrieval': {'requested_backend': requested, 'actual_backend': 'not_queried', 'fallback_reason': None}}


def task_options(root):
    """List bounded explicit Goal/Wiki choices without global-root or private-scope reads."""
    result = {'goals': [], 'wiki': [], 'truncated': False}
    for key, bucket in (('goals', 'profiles/goals'), ('wiki', 'wiki')):
        paths = list(islice((root / bucket).rglob('*.md'), 101))
        result['truncated'] |= len(paths) > 100
        for path in sorted(paths[:100]):
            relative = path.relative_to(root).as_posix()
            try:
                item = _text_file(root, relative, {'.md'})
                meta = handoff._meta(item['text'].encode('utf-8'))
                if key == 'goals' and meta.get('type') != 'goal':
                    continue
                if key == 'wiki' and not handoff._reviewed(meta):
                    continue
                result[key].append({'path': relative, 'title': str(meta.get('title') or path.stem), 'sha256': item['sha256']})
            except (OSError, ValueError, UnicodeError):
                continue
    return result


def goal(root, relative):
    handoff._relative(relative, 'profiles/goals')
    return _text_file(root, relative, {'.md'})


def create_task(root, request):
    """Create a task using an inspected existing Goal or a new user-authored Goal."""
    from . import store
    task_id = tasks._id(request.get('task_id'))
    chosen = request.get('wiki', [])
    if not isinstance(chosen, list) or len(chosen) > 16:
        raise ValueError('Choose at most 16 reviewed Wiki sources')
    paths = []
    expected = {}
    for ref in chosen:
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('Inspect the chosen Wiki sources first')
        handoff._relative(ref['path'], 'wiki')
        if _text_file(root, ref['path'], {'.md'})['sha256'] != ref['sha256']:
            raise ValueError('Wiki source changed; reload the choices')
        paths.append(ref['path'])
        expected[ref['path']] = ref['sha256']
    if len(paths) != len(set(paths)):
        raise ValueError('Choose distinct Wiki sources')
    lock = tasks._inside(root, '.oks/locks/workspace-create.lock')
    with store._file_lock(lock):
        if tasks._path(root, task_id).exists():
            raise ValueError('Task already exists; choose another task ID')
        existing = request.get('goal_path')
        if existing:
            if request.get('new_goal'):
                raise ValueError('Choose an existing Goal or write a new Goal, not both')
            inspected = goal(root, existing)
            if inspected['sha256'] != request.get('expected_goal_sha256'):
                raise ValueError('Goal changed; read it again before creating a task')
            relative = inspected['path']
            expected[relative] = inspected['sha256']
        else:
            new = request.get('new_goal')
            if not isinstance(new, dict):
                raise ValueError('Write the task title and Goal')
            title, text = new.get('title'), new.get('text')
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
                raise ValueError('Title needs 1-200 characters and Goal needs 1-8000 characters')
            relative = f'profiles/goals/{task_id}.md'
            target = tasks._inside(root, relative)
            if target.exists():
                raise ValueError('A Goal with this task ID exists; select it or choose another ID')
            # Validate all Wiki references before creating a new file.
            for ref in paths:
                if not handoff._reviewed(handoff._meta(handoff._read(root, ref, 'wiki'))):
                    raise ValueError('Wiki sources must be active and human-reviewed')
            source = '---\n' + yaml.safe_dump({'type': 'goal', 'title': title.strip(), 'status': 'active'}, allow_unicode=True) + '---\n\n' + text.strip() + '\n'
            store._atomic_write(target, source.encode('utf-8'))
            expected[relative] = hashlib.sha256(source.encode('utf-8')).hexdigest()
        try:
            return tasks.start(root, task_id, relative, paths, expected_sources=expected)
        except (ValueError, OSError):
            raise ValueError('Task not created; Goal preserved. Reload and select that Goal before retrying') from None


def _text_file(root, relative, suffixes):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or any(s in ('', '.', '..') for s in relative.split('/')):
        raise ValueError('Choose a canonical relative file path')
    target = tasks._inside(root, relative)
    if target.suffix.lower() not in suffixes:
        raise ValueError('Only Markdown or plain text can be read here')
    with target.open('rb') as handle:
        raw = handle.read(TEXT_LIMIT + 1)
    if len(raw) > TEXT_LIMIT:
        raise ValueError('File exceeds the 256 KiB reader limit; open it locally')
    text = raw.decode('utf-8-sig')
    if '\x00' in text:
        raise ValueError('Binary files cannot be previewed')
    return {'path': relative, 'text': text, 'sha256': hashlib.sha256(raw).hexdigest(),
            'format': 'markdown' if target.suffix.lower() == '.md' else 'text'}


def artifact(root, task_id, relative, revision):
    task = tasks._load(root, task_id)
    if type(revision) is not int or revision < 1:
        raise ValueError('Choose a task revision')
    entry = next((entry for entry in [task, *task['history']] if entry['revision'] == revision), None)
    if entry is None:
        raise ValueError('Task revision is unavailable')
    ref = next((item for item in entry['artifacts'] if item['path'] == relative), None)
    if ref is None:
        raise ValueError('File is not registered in this task revision')
    result = _text_file(root, relative, {'.md', '.txt'})
    return {**result, 'revision': revision, 'expected_sha256': ref['sha256'],
            'status': 'unchanged' if ref['sha256'] == result['sha256'] else 'changed',
            'historical_bytes_available': ref['sha256'] == result['sha256']}


def draft(root, relative):
    handoff._relative(relative, 'drafts')
    if len(relative.split('/')) != 2:
        raise ValueError('Review a Draft directly under drafts/; nested Draft promotion is unsupported')
    return _text_file(root, relative, {'.md'})


def invoke(root, operation, payload):
    """Run existing global-root APIs in an isolated process, never swap os.environ in threads."""
    parent = Path(__file__).resolve().parent.parent
    env = {key: value for key, value in os.environ.items() if key.upper() not in {'PYTHONPATH', 'PYTHONHOME'}}
    env.update(OKS_ROOT=str(root.resolve()), PYTHONPATH=str(parent), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run([sys.executable, '-P', '-X', 'utf8', '-m', 'knowledge_studio.workspace_worker', operation],
                                input=json.dumps(payload, ensure_ascii=False), cwd=parent, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=30,
                                **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    except subprocess.TimeoutExpired:
        raise ValueError('Operation timed out; inspect its current state before retrying') from None
    if len(result.stdout.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Response exceeds workspace limit')
    try:
        value = json.loads(result.stdout)
    except ValueError:
        raise ValueError('Local operation failed; check the selected instance and OKS installation') from None
    if result.returncode:
        raise ValueError(value.get('error', 'Local operation failed'))
    return value
