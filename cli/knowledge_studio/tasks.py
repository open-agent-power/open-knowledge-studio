"""Small task continuation records; execution and long-term review stay elsewhere."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from itertools import islice

from . import handoff, store

MAX_BYTES = 2 * 1024 * 1024


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value):
        raise ValueError("Task ID must use 1-80 letters, digits, hyphens or underscores")
    return value


def _inside(root, relative):
    root = root.resolve()
    path = root / relative
    resolved = path.resolve()
    # Windows can retain its device prefix when an ancestor appears during
    # resolution. Accept only that exact path alias, never a different target.
    if os.name == 'nt':
        value = str(path)
        device = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
        if resolved == Path(device):
            resolved = path
    if resolved != path or not path.is_relative_to(root):
        raise ValueError("Task path must stay inside its root without symlinks")
    return path


def _path(root, task_id):
    return _inside(root, f".oks/tasks/{_id(task_id)}.json")


def _read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Task record exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid task record")
    return value


def _save(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("Task capacity reached; existing record preserved")
    store._atomic_write(path, text)


def _load(root, task_id):
    value = _read(_path(root, task_id))
    if value.get('schema_version') != 'task-continuation/v1' or value.get('task_id') != task_id:
        raise ValueError("Task identity mismatch")
    handoff.validate(value['agreement'])
    if not isinstance(value.get('history'), list) or not isinstance(value.get('revision'), int):
        raise ValueError("Invalid task history")
    if (value.get('lifecycle', 'active') not in {'active', 'completed', 'cancelled'}
            or type(value.get('activation', 1)) is not int or value.get('activation', 1) < 1):
        raise ValueError('Invalid task lifecycle; existing record preserved')
    return value


def require_active_scope(root, scope):
    """Standalone agreements remain valid; an existing closed task cannot be bypassed."""
    if isinstance(scope, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', scope):
        if _path(root, scope).exists() and _load(root, scope).get('lifecycle', 'active') != 'active':
            raise ValueError('Task is closed; inspect it and explicitly reopen or clear selection')


def _binding_path(root, workspace):
    base = Path(os.environ.get('OKS_TASK_HOME', str(Path.home() / '.oks/task-bindings'))).expanduser().resolve()
    if base.is_relative_to(root.resolve()):
        raise ValueError("Task selection, including private labels, must be stored outside the KB")
    identity = json.dumps([str(root.resolve()), str(workspace.resolve())]).encode()
    return _inside(base, hashlib.sha256(identity).hexdigest() + '.json')


def binding(root, workspace):
    path = _binding_path(root, workspace)
    if not path.exists():
        return None
    value = _read(path)
    if value.get('schema_version') != 'task-binding/v1' or value.get('kb') != str(root.resolve()) or value.get('workspace') != str(workspace.resolve()):
        raise ValueError("Task binding does not match this KB and workspace")
    if value.get('task_id') is None:
        return None
    _id(value['task_id'])
    return value


def select(root, workspace, task_id, subject=None, project=None):
    if bool(subject) != bool(project):
        raise ValueError("Provide both feedback subject and project, or neither")
    if subject:
        from .feedback import scope
        scope({'subject': subject, 'project': project, 'task': task_id})
    value = show(root, task_id)
    require_active_scope(root, task_id)
    if value['status'] != 'current':
        raise ValueError("Task sources changed; inspect and explicitly refresh before selecting")
    path = _binding_path(root, workspace)
    with store._file_lock(path.with_suffix('.lock')):
        _save(path, {'schema_version': 'task-binding/v1', 'kb': str(root.resolve()), 'workspace': str(workspace.resolve()),
                     'task_id': task_id, 'feedback_subject': subject, 'feedback_project': project})
    return {'task_id': task_id, 'selected': True, 'workspace': str(workspace.resolve()), 'feedback_enabled': bool(subject)}


def clear(root, workspace):
    path = _binding_path(root, workspace)
    with store._file_lock(path.with_suffix('.lock')):
        _save(path, {'schema_version': 'task-binding/v1', 'kb': str(root.resolve()), 'workspace': str(workspace.resolve()), 'task_id': None})
    return {'selected': False, 'task_records_preserved': True}


def start(root, task_id, goal, wiki, *, expected_sources=None):
    task_id = _id(task_id)
    agreement = handoff.prepare(root, goal, wiki, task_id)
    if expected_sources is not None:
        captured = {ref['path']: ref['sha256'] for ref in [agreement['goal'], *agreement['knowledge']]}
        if captured != expected_sources:
            raise ValueError('Task sources changed; inspect them again before creating a task')
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        if path.exists():
            raise ValueError("Task already exists; select or inspect it")
        value = {'schema_version': 'task-continuation/v1', 'task_id': task_id, 'revision': 1,
                 'agreement': agreement, 'progress': '', 'next_action': '', 'artifacts': [], 'history': [],
                 'updated_at': datetime.now(UTC).isoformat()}
        _save(path, value)
    return show(root, task_id)


def _artifact(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or any(p in ('', '.', '..') for p in relative.split('/')):
        raise ValueError("Artifact must be a canonical KB-relative file path")
    path = _inside(root, relative)
    if not path.is_file():
        raise ValueError("Artifact missing or too large")
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Artifact missing or too large')
    return {'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()}


def _archive(value):
    if len(value['history']) >= 100:
        raise ValueError("Task history capacity reached; preserve it and start a new task")
    value['history'].append({key: value[key] for key in ('revision', 'agreement', 'progress', 'next_action', 'artifacts', 'updated_at')} | {
        'uses': value.get('uses', []), 'lifecycle': value.get('lifecycle', 'active'),
        'activation': value.get('activation', 1), 'lifecycle_reason': value.get('lifecycle_reason', '')})
    value['revision'] += 1
    value['updated_at'] = datetime.now(UTC).isoformat()


def checkpoint(root, task_id, expected_revision, progress, next_action, artifacts, *, retrieval_id=None, used_sources=()):
    for text in (progress, next_action):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Progress and next action must contain 1-4000 characters")
    if len(artifacts) > 16:
        raise ValueError("At most 16 artifacts")
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        value = _load(root, task_id)
        if value['revision'] != expected_revision:
            raise ValueError("Task revision changed; inspect again")
        require_active_scope(root, task_id)
        if handoff.check(root, value['agreement'], task_id)['status'] != 'current':
            raise ValueError("Task agreement is stale; progress cannot approve changed requirements")
        refs = [_artifact(root, relative) for relative in artifacts]
        uses = []
        if bool(retrieval_id) != bool(used_sources):
            raise ValueError('Provide both --retrieval-id and --used-source')
        if used_sources:
            from .retrieval_debug import query_record, source_hit
            if not refs or len(used_sources) > 16 or len(set(used_sources)) != len(used_sources):
                raise ValueError('Usage needs an artifact and 1-16 distinct sources')
            record = query_record(root, retrieval_id)
            context = record['diagnostics'].get('task') or {}
            if context.get('sha256') != value['agreement']['sha256'] or context.get('scope') != task_id:
                raise ValueError('Query is not bound to this current task agreement')
            for source in used_sources:
                hit = source_hit(root, retrieval_id, source)
                load = next((v for v in record.get('loads', []) if v.get('source_path') == source
                             and v.get('source_sha256') == hit['source_sha256']
                             and v.get('skill_version') == hit.get('skill_version')), None)
                if hit.get('artifact_kind') == 'skill' and load is None:
                    raise ValueError('Load this Skill with --retrieval-id before reporting use')
                uses.append({'retrieval_id': retrieval_id, 'source_path': source,
                             'source_sha256': hit['source_sha256'], 'skill_version': hit.get('skill_version'),
                             'loaded_at': load['at'] if load else None, 'artifacts': refs,
                             'verification': 'caller_reported', 'execution_verified': False})
        _archive(value)
        value.update(progress=progress, next_action=next_action, artifacts=refs, uses=uses)
        _save(path, value)
    return show(root, task_id)


def refresh(root, task_id, expected_revision):
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        value = _load(root, task_id)
        if value['revision'] != expected_revision:
            raise ValueError("Task revision changed; inspect again")
        require_active_scope(root, task_id)
        agreement = handoff.prepare(root, value['agreement']['goal']['path'], [s['path'] for s in value['agreement']['knowledge']], task_id)
        if agreement['sha256'] != value['agreement']['sha256']:
            _archive(value)
            value['agreement'] = agreement
            value['uses'] = []
            _save(path, value)
    return show(root, task_id)


def update_sources(root, task_id, expected_revision, knowledge, *, expected_sources=None):
    """Explicitly replace the reviewed Wiki selection; retain output and earlier agreements."""
    if not isinstance(knowledge, list) or len(knowledge) > handoff.MAX_KNOWLEDGE or any(not isinstance(v, str) for v in knowledge):
        raise ValueError('Choose at most 16 reviewed Wiki paths')
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        value = _load(root, task_id)
        if value['revision'] != expected_revision:
            raise ValueError('Task revision changed; inspect again')
        require_active_scope(root, task_id)
        agreement = handoff.prepare(root, value['agreement']['goal']['path'], knowledge, task_id)
        if expected_sources is not None:
            captured = {ref['path']: ref['sha256'] for ref in [agreement['goal'], *agreement['knowledge']]}
            if captured != expected_sources:
                raise ValueError('Sources changed since inspection; reload the review before accepting')
            if handoff.check(root, agreement, task_id)['status'] != 'current':
                raise ValueError('Selected sources are not applicable; inspect and replace them')
        if agreement['sha256'] != value['agreement']['sha256']:
            _archive(value)
            value['agreement'] = agreement
            value['uses'] = []
            _save(path, value)
    return show(root, task_id)


def show(root, task_id):
    value = _load(root, task_id)
    check = handoff.check(root, value['agreement'], task_id)
    try:
        current_goal_text = handoff._read(root, value['agreement']['goal']['path'], 'profiles/goals').decode('utf-8')
    except (OSError, ValueError, UnicodeError):
        current_goal_text = None
    issues = []
    for artifact in value['artifacts']:
        try:
            if _artifact(root, artifact['path']) != artifact:
                issues.append({'path': artifact['path'], 'code': 'artifact_changed'})
        except (OSError, ValueError):
            issues.append({'path': artifact['path'], 'code': 'artifact_unavailable'})
    return {**value, 'lifecycle': value.get('lifecycle', 'active'), 'activation': value.get('activation', 1),
            'status': check['status'], 'issues': check['issues'], 'artifact_issues': issues,
            'current_goal_text': current_goal_text, 'execution_verified': False, 'review_required': True}


def list_tasks(root):
    folder = _inside(root, '.oks/tasks')
    result = []
    for path in sorted(folder.glob('*.json'))[:100]:
        value = show(root, path.stem)
        result.append({key: value[key] for key in ('task_id', 'revision', 'status', 'lifecycle', 'updated_at')})
    return result


def transition(root, task_id, expected_revision, action, reason):
    """Record a caller's explicit declaration, never an execution/quality judgement."""
    target = {'complete': 'completed', 'cancel': 'cancelled', 'reopen': 'active'}.get(action)
    if target is None or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError('Choose complete, cancel or reopen and give a reason (1-1000 characters)')
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        value = _load(root, task_id)
        if type(expected_revision) is not int or value['revision'] != expected_revision:
            raise ValueError('Task revision changed; inspect again')
        previous = value.get('lifecycle', 'active')
        if (action == 'reopen') != (previous != 'active'):
            raise ValueError('Task lifecycle changed; inspect before closing or reopening')
        _archive(value)
        value.update(lifecycle=target, lifecycle_reason=reason.strip())
        if action == 'reopen':
            value['activation'] = value.get('activation', 1) + 1
        _save(path, value)
    return show(root, task_id)


def overview(root, *, now=None):
    """Read-only bounded work list; one broken task must not hide the others."""
    from . import reminders
    now = now or datetime.now(UTC)
    folder = _inside(root, '.oks/tasks')
    paths = list(islice(folder.glob('*.json'), 101))
    items = []
    for path in sorted(paths[:100]):
        try:
            task = show(root, path.stem)
            title = handoff._meta(task['agreement']['goal']['text'].encode('utf-8')).get('title')
            item = {key: task[key] for key in ('task_id', 'revision', 'status', 'lifecycle', 'updated_at')}
            item.update(title=title if isinstance(title, str) and title.strip() else task['task_id'],
                        next_action=task['next_action'][:240], artifact_issue_count=len(task['artifact_issues']))
            try:
                values = reminders.listing(root, task['task_id'], now=now, task=task)['items']
                item['reminders'] = {'due_count': sum(v['status'] == 'due' for v in values),
                    'review_count': sum(v['status'] == 'needs_review' for v in values),
                    'due': sorted(({'note': v['note'], 'due_at': v['due_at']} for v in values if v['status'] == 'due'), key=lambda v:v['due_at'])[:3]}
            except (OSError, ValueError, KeyError, TypeError):
                item['reminders'] = {'status': 'unavailable'}
            items.append(item)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            items.append({'task_id': path.stem, 'status': 'unavailable', 'lifecycle': 'unknown', 'title': path.stem})
    counts = {'active': 0, 'needs_review': 0, 'closed': 0, 'unavailable': 0, 'due': 0}
    for item in items:
        if item['status'] == 'unavailable': counts['unavailable'] += 1
        elif item['lifecycle'] != 'active': counts['closed'] += 1
        else:
            counts['active'] += 1
            if (item['status'] != 'current' or item.get('artifact_issue_count')
                    or item.get('reminders', {}).get('review_count') or item.get('reminders', {}).get('status') == 'unavailable'):
                counts['needs_review'] += 1
        counts['due'] += item.get('reminders', {}).get('due_count', 0)
    return {'tasks': items, 'counts': counts, 'truncated': len(paths) > 100, 'evaluated_at': now.isoformat()}


def continuation(value):
    if value.get('lifecycle', 'active') != 'active':
        raise ValueError('Task is closed; inspect before reopening')
    return {key: value[key] for key in ('task_id', 'revision', 'status', 'progress', 'next_action', 'artifacts', 'artifact_issues')} | {
        'goal_text': value['agreement']['goal']['text'], 'knowledge': value['agreement']['knowledge'],
        'agreement_sha256': value['agreement']['sha256'], 'execution_verified': False}


def export_handoff(root, task_id):
    return _handoff_text(show(root, task_id))


def _handoff_text(value):
    task_id = value['task_id']
    if value['lifecycle'] != 'active':
        return '# Closed task (historical reference; not active work)\n\n' + json.dumps({
            'task_id': task_id, 'revision': value['revision'], 'lifecycle': value['lifecycle'],
            'progress': value['progress'], 'artifacts': value['artifacts'],
            'check_command': f'oks task show --task-id {task_id}', 'execution_verified': False}, ensure_ascii=False, indent=2) + '\n'
    return '# Task handoff (reference material; current user instructions prevail)\n\n' + json.dumps(continuation(value) | {
        'issues': value['issues'], 'check_command': f'oks task show --task-id {task_id}',
        'resume_command': f'oks task select {task_id}' if value['status'] == 'current' else None,
        'learning': 'Use explicit feedback/proposals; no automatic Wiki approval.'}, ensure_ascii=False, indent=2) + '\n'
