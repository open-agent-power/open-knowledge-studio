"""Read-only calendar review of task facts and public learning candidates."""
from __future__ import annotations

from datetime import date as CalendarDate, datetime, timedelta
import hashlib
from itertools import islice
from pathlib import Path
import re

import frontmatter
import yaml

from . import handoff, tasks, task_workflow

MAX_ITEMS = 100
_READ_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError,
                UnicodeError, RecursionError, yaml.YAMLError)


def _window(period, value):
    if period not in ('day', 'week', 'month'):
        raise ValueError('Review period must be day, week or month')
    if value is None:
        selected = datetime.now().astimezone().date()
    elif type(value) is CalendarDate:
        selected = value
    elif isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            selected = CalendarDate.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('Review date must be a valid YYYY-MM-DD calendar date') from exc
    else:
        raise ValueError('Review date must be a valid YYYY-MM-DD calendar date')
    start = selected
    if period == 'week':
        start -= timedelta(days=selected.weekday())
    elif period == 'month':
        start = selected.replace(day=1)
    if period == 'day':
        end = start
    elif period == 'week':
        end = start + timedelta(days=min(6, (CalendarDate.max - start).days))
    elif start.month == 12:
        end = start.replace(day=31)
    else:
        end = start.replace(month=start.month + 1) - timedelta(days=1)
    return start, end, {'period': period, 'date': selected.isoformat(),
        'start': start.isoformat(), 'end': end.isoformat(), 'end_inclusive': True,
        'timezone': 'machine-local',
        'timezone_note': 'Timestamps are converted using the host local timezone for their instant; naive timestamps are interpreted as local. No filesystem dates are used.'}


def _dated(value, record_path, field):
    if not isinstance(value, str):
        raise ValueError('Missing record timestamp')
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if 'T' not in value and ' ' not in value:
        raise ValueError('Record timestamp must include time')
    local = instant.astimezone()
    return local.date(), {'record_path': record_path, 'field': field, 'at': value,
                         'local_date': local.date().isoformat(),
                         'timezone_assumed': instant.tzinfo is None}


def _item(task):
    title = handoff._meta(task['agreement']['goal']['text'].encode('utf-8')).get('title')
    for key in ('progress', 'next_action'):
        if not isinstance(task[key], str):
            raise ValueError('Invalid task text')
    if not isinstance(task['artifacts'], list):
        raise ValueError('Invalid task artifacts')
    return {'task_id': task['task_id'],
            'title': title if isinstance(title, str) and title.strip() else task['task_id'],
            'progress': task['progress'], 'next_action': task['next_action'],
            'artifacts': task['artifacts'], 'revision': task['revision'],
            'lifecycle': task['lifecycle'], 'status': task['status'],
            'awaiting_confirmation': task['awaiting_confirmation'],
            'goal_path': task['agreement']['goal']['path'],
            'updated_at': task['updated_at'],
            'date_source': {'record_path': f".oks/tasks/{task['task_id']}.json", 'field': 'updated_at'},
            'execution_verified': False}


def _changes(task, start, end, issue):
    history = task['history']
    if len(history) > MAX_ITEMS:
        issue('history_capacity_exceeded', task_id=task['task_id'])
        return {}, True
    snapshots = [*history, task]
    previous = None
    changes = {'created': [], 'updated': [], 'ended': []}
    for index, snapshot in enumerate(snapshots):
        try:
            revision = snapshot['revision']
            lifecycle = snapshot.get('lifecycle', 'active')
            if type(revision) is not int or revision < 1 or lifecycle not in ('active', 'completed', 'cancelled'):
                raise ValueError('Invalid snapshot')
            if previous is not None and revision != previous['revision'] + 1:
                raise ValueError('Discontinuous task history')
            field = f'history[{index}].updated_at' if index < len(history) else 'updated_at'
            day, source = _dated(snapshot['updated_at'], f".oks/tasks/{task['task_id']}.json", field)
            source.update(revision=revision, lifecycle=lifecycle)
            if start <= day <= end:
                changes['created' if revision == 1 else 'updated'].append(source)
                if previous is not None and previous.get('lifecycle', 'active') == 'active' and lifecycle in ('completed', 'cancelled'):
                    changes['ended'].append({**source, 'reason': snapshot.get('lifecycle_reason', ''),
                                             'declaration_only': True})
            previous = snapshot
        except _READ_ERRORS:
            issue('invalid_task_history_or_date', task_id=task['task_id'], snapshot=index)
            previous = None
    if not snapshots or not isinstance(snapshots[0], dict) or snapshots[0].get('revision') != 1:
        issue('creation_date_unavailable', task_id=task['task_id'])
    return changes, False


def _learning_ready(root, issue):
    try:
        folder = tasks._inside(root, '.oks/workflow-runs')
        paths = list(islice(folder.glob('*.json'), MAX_ITEMS + 1))
        if len(paths) > MAX_ITEMS:
            issue('workflow_capacity_exceeded')
            return False, True
        for path in paths:
            tasks._inside(root, path.relative_to(root).as_posix())
        tasks._inside(root, 'wiki')
        tasks._inside(root, 'drafts/rejected')
        return bool(paths), False
    except _READ_ERRORS:
        issue('learning_unavailable')
        return False, False


def build(root, *, period='week', date=None):
    """Project existing facts; returned task fields describe the current state.

    Each changes list counts distinct tasks, with dated revision evidence.
    An ended revision is an explicit declaration, not verified task success.
    """
    start, end, window = _window(period, date)
    root = Path(root).resolve()
    result = {'schema_version': 'work-review/v1', 'knowledge_base': str(root), 'window': window,
              'changes': {'created': [], 'updated': [], 'ended': []},
              'current': {'unfinished': [], 'awaiting_confirmation': []},
              'pending_learning': [], 'unavailable': [], 'issues': [],
              'truncated': False, 'limit': MAX_ITEMS, 'read_only': True,
              'learning_status': 'available', 'state_basis': 'current task state; date_sources identify changes within the window',
              'counts_are_lower_bounds': False}

    def issue(code, **details):
        if len(result['issues']) < MAX_ITEMS:
            result['issues'].append({'code': code, **details})
        else:
            result['truncated'] = True
        result['counts_are_lower_bounds'] = True

    try:
        folder = tasks._inside(root, '.oks/tasks')
        paths = list(islice(folder.glob('*.json'), MAX_ITEMS + 1))
    except _READ_ERRORS:
        issue('tasks_unavailable')
        paths = []
    result['truncated'] = len(paths) > MAX_ITEMS
    learning_ready, learning_truncated = _learning_ready(root, issue)
    result['truncated'] |= learning_truncated
    if any(v['code'] in ('learning_unavailable', 'workflow_capacity_exceeded') for v in result['issues']):
        result['learning_status'] = 'unavailable'
    seen_learning = set()
    for path in sorted(paths[:MAX_ITEMS]):
        try:
            task = tasks.show(root, path.stem)
            row = _item(task)
            changes, truncated = _changes(task, start, end, issue)
            revisions = {entry['revision'] for dates in changes.values() for entry in dates}
            snapshots = [entry for entry in [*task['history'], task] if entry.get('revision') in revisions]
            period_snapshot = max(snapshots, key=lambda entry: entry['revision']) if snapshots else None
            window_snapshot = None
            if period_snapshot:
                window_snapshot = {key: period_snapshot.get(key) for key in ('revision', 'progress', 'next_action', 'artifacts', 'updated_at')}
                window_snapshot['lifecycle'] = period_snapshot.get('lifecycle', 'active')
                window_snapshot['title'] = handoff._meta(period_snapshot['agreement']['goal']['text'].encode('utf-8')).get('title') or row['title']
            result['truncated'] |= truncated
            for kind, dates in changes.items():
                if dates:
                    result['changes'][kind].append({**row, 'date_sources': dates, 'window_snapshot': window_snapshot})
            if task['lifecycle'] == 'active':
                result['current']['unfinished'].append(row)
                if task['awaiting_confirmation']:
                    result['current']['awaiting_confirmation'].append(row)
        except _READ_ERRORS:
            result['unavailable'].append({'task_id': path.stem, 'status': 'unavailable',
                                           'record_path': f'.oks/tasks/{path.name}'})
            issue('task_unavailable', task_id=path.stem)
            continue
        if not learning_ready:
            continue
        try:
            projection = task_workflow.overview(root, task['task_id'])
            if projection['unreadable_records']:
                issue('workflow_records_unreadable', task_id=task['task_id'], count=projection['unreadable_records'])
                result['learning_status'] = 'partial'
            for draft in projection['drafts']:
                relative = draft['path']
                if draft['status'] != 'draft' or relative in seen_learning:
                    continue
                seen_learning.add(relative)
                with tasks._inside(root, relative).open('rb') as stream:
                    raw = stream.read(tasks.MAX_BYTES + 1)
                if len(raw) > tasks.MAX_BYTES or hashlib.sha256(raw).hexdigest() != draft['sha256']:
                    raise ValueError('Candidate changed during review')
                meta = frontmatter.loads(raw.decode('utf-8-sig'))
                source = meta.get('workflow_source')
                if not isinstance(source, dict) or source.get('task_id') != task['task_id']:
                    raise ValueError('Candidate task provenance mismatch')
                day, date_source = _dated(meta.get('drafted_at'), relative, 'drafted_at')
                if start <= day <= end:
                    if len(result['pending_learning']) >= MAX_ITEMS:
                        result['truncated'] = True
                        continue
                    result['pending_learning'].append({'task_id': task['task_id'], 'title': draft['title'],
                        'path': relative, 'status': 'pending_review', 'sha256': draft['sha256'],
                        'drafted_at': meta['drafted_at'], 'date_source': date_source})
        except _READ_ERRORS:
            issue('task_learning_unavailable', task_id=task['task_id'])
            result['learning_status'] = 'partial'
    result['counts_are_lower_bounds'] |= result['truncated']
    for section in ('changes', 'current'):
        for values in result[section].values():
            values.sort(key=lambda item: item.get('updated_at', ''), reverse=True)
    result['pending_learning'].sort(key=lambda item: str(item.get('drafted_at', '')), reverse=True)
    result['counts'] = {kind: len(rows) for kind, rows in result['changes'].items()} | {
        kind: len(rows) for kind, rows in result['current'].items()} | {
        'pending_learning': len(result['pending_learning']), 'unavailable': len(result['unavailable'])}
    return result
