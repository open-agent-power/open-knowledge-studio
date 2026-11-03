"""Opt-in Goal reminders, presented in a selected task session; no scheduler."""
from datetime import UTC, datetime
from contextlib import contextmanager
import hashlib
import sys

from . import store, tasks
from .memory_policy import instant

MAX_ITEMS = 100


def _path(root, task_id):
    return tasks._inside(root, f'.oks/reminders/{tasks._id(task_id)}.json')


def _load(root, task_id):
    path = _path(root, task_id)
    value = tasks._read(path) if path.exists() else {'schema_version': 'task-reminders/v1', 'task_id': task_id, 'items': {}}
    if (value.get('schema_version') != 'task-reminders/v1' or value.get('task_id') != task_id
            or not isinstance(value.get('items'), dict) or len(value['items']) > MAX_ITEMS):
        raise ValueError('Invalid reminder store; existing data preserved')
    for key, item in value['items'].items():
        tasks._id(key)
        if (not isinstance(item, dict) or item.get('id') != key or type(item.get('revision')) is not int
                or item['revision'] < 1 or item.get('state') not in {'pending', 'completed', 'cancelled'}
                or not isinstance(item.get('presented', {}), dict) or len(item.get('presented', {})) > 32):
            raise ValueError('Invalid reminder item; existing data preserved')
    return path, value


def _clock(now):
    return now or datetime.now(UTC)


def _view(item, task, now):
    if item['state'] != 'pending':
        status = item['state']
    elif task.get('lifecycle', 'active') != 'active':
        status = 'task_closed'
    elif (task['status'] != 'current' or item['agreement_sha256'] != task['agreement']['sha256']
            or item.get('task_activation', 1) != task.get('activation', 1)):
        status = 'needs_review'
    else:
        status = 'due' if instant(item['due_at']) <= now else 'scheduled'
    return {key: value for key, value in item.items() if key != 'presented'} | {
        'status': status, 'execution_verified': False}


def listing(root, task_id, *, now=None, task=None):
    task = task or tasks.show(root, task_id)
    _, state = _load(root, task_id)
    return {'schema_version': 'task-reminders/v1', 'task_id': task_id,
            'items': [_view(item, task, _clock(now)) for item in state['items'].values()],
            'background_wake': False}


def add(root, request, *, now=None):
    task_id = tasks._id(request.get('task_id'))
    identifier = tasks._id(request.get('id'))
    note = request.get('note')
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
        raise ValueError('Reminder needs 1-500 characters')
    due = instant(request.get('due_at')).isoformat()
    path = _path(root, task_id)
    with store._file_lock(tasks._path(root, task_id).with_suffix('.lock')), store._file_lock(path.with_suffix('.lock')):
        task = tasks.show(root, task_id)
        tasks.require_active_scope(root, task_id)
        if task['status'] != 'current' or request.get('expected_agreement_sha256') != task['agreement']['sha256']:
            raise ValueError('Task sources changed; inspect before adding a reminder')
        _, value = _load(root, task_id)
        if identifier in value['items']:
            raise ValueError('Reminder already exists; inspect its revision')
        if len(value['items']) >= MAX_ITEMS:
            raise ValueError('Reminder capacity reached; existing items preserved')
        item = {'id': identifier, 'revision': 1, 'note': note.strip(), 'due_at': due, 'state': 'pending',
                'agreement_sha256': task['agreement']['sha256'], 'task_activation': task.get('activation', 1),
                'created_at': _clock(now).isoformat(), 'presented': {}}
        value['items'][identifier] = item
        tasks._save(path, value)
        return _view(item, task, _clock(now))


def update(root, request, *, now=None):
    task_id, identifier = tasks._id(request.get('task_id')), tasks._id(request.get('id'))
    action = request.get('action')
    if action not in {'complete', 'cancel', 'snooze', 'confirm'}:
        raise ValueError('Choose complete, cancel, snooze or confirm')
    now = _clock(now)
    path = _path(root, task_id)
    with store._file_lock(tasks._path(root, task_id).with_suffix('.lock')), store._file_lock(path.with_suffix('.lock')):
        task = tasks.show(root, task_id)
        _, value = _load(root, task_id)
        item = value['items'].get(identifier)
        if not item or type(request.get('expected_revision')) is not int or request['expected_revision'] != item['revision']:
            raise ValueError('Reminder changed; inspect its current revision')
        if item['state'] != 'pending':
            raise ValueError('Reminder already completed or cancelled')
        if action in {'snooze', 'confirm'}:
            tasks.require_active_scope(root, task_id)
            if task['status'] != 'current' or request.get('expected_agreement_sha256') != task['agreement']['sha256']:
                raise ValueError('Inspect and confirm the current task agreement first')
        if action == 'snooze':
            due = instant(request.get('due_at'))
            if due <= now:
                raise ValueError('Choose a future time for snooze')
            item['due_at'] = due.isoformat()
        elif action == 'confirm':
            item['agreement_sha256'] = task['agreement']['sha256']
            item['task_activation'] = task.get('activation', 1)
        else:
            item['state'] = 'completed' if action == 'complete' else 'cancelled'
        item.update(revision=item['revision'] + 1, updated_at=now.isoformat(), presented={})
        tasks._save(path, value)
        return _view(item, task, now)


def due_for_session(root, task_id, session_id, *, now=None):
    if not isinstance(session_id, str) or not session_id or len(session_id) > 500:
        return []
    task = tasks.show(root, task_id)
    _, value = _load(root, task_id)
    key = hashlib.sha256(session_id.encode()).hexdigest()
    return [_view(item, task, _clock(now)) for item in value['items'].values()
            if _view(item, task, _clock(now))['status'] == 'due' and item.get('presented', {}).get(key) != item['revision']][:3]


def mark_output(root, task_id, session_id, references, *, now=None):
    """Record an observed Hook output, never acknowledgement or task completion."""
    if not session_id or not references:
        return
    task = tasks.show(root, task_id)
    key = hashlib.sha256(session_id.encode()).hexdigest()
    path = _path(root, task_id)
    with store._file_lock(path.with_suffix('.lock')):
        _, value = _load(root, task_id)
        changed = False
        for ref in references[:3]:
            item = value['items'].get(ref['id'])
            if item and item['revision'] == ref['revision'] and _view(item, task, _clock(now))['status'] == 'due':
                item.setdefault('presented', {})[key] = item['revision']
                while len(item['presented']) > 32:
                    item['presented'].pop(next(iter(item['presented'])))
                changed = True
        if changed:
            tasks._save(path, value)


@contextmanager
def output_guard(root, task_id, session_id):
    """Serialize selection, actual stdout flush and dedup receipt across Hooks."""
    path = _path(root, task_id)
    if not session_id or len(session_id) > 500 or not path.exists():
        yield []
        return
    with store._file_lock(tasks._path(root, task_id).with_suffix('.lock')), store._file_lock(path.with_suffix('.lock')):
        task = tasks.show(root, task_id)
        _, value = _load(root, task_id)
        key = hashlib.sha256(session_id.encode()).hexdigest()
        selected = [item for item in value['items'].values()
                    if _view(item, task, _clock(None))['status'] == 'due'
                    and item.get('presented', {}).get(key) != item['revision']][:3]
        yield [_view(item, task, _clock(None)) for item in selected]
        for item in selected:
            item.setdefault('presented', {})[key] = item['revision']
            while len(item['presented']) > 32:
                item['presented'].pop(next(iter(item['presented'])))
        if selected:
            try:
                tasks._save(path, value)
            except OSError:
                print('oks-hook: reminder output was emitted; dedup receipt could not be saved', file=sys.stderr)
