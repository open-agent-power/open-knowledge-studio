"""Bounded local workspace operations; no host configuration or remote writes."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
    for key, bucket in (('goals', 'goal'), ('goals', 'profiles/goals'), ('wiki', 'wiki')):
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


def _current_wiki(root, relative, mode):
    from .memory_policy import evaluate
    from .decisions import validate_options
    handoff._relative(relative, 'wiki')
    item = _text_file(root, relative, {'.md'})
    meta = handoff._meta(item['text'].encode('utf-8'))
    validate_options(meta.get('options'))
    validity = evaluate(meta.get('applicability'))
    reason = 'not_reviewed' if not handoff._reviewed(meta) else validity['status'] if mode == 'enforce' and not validity['eligible'] else None
    return {**item, 'title': str(meta.get('title') or Path(relative).stem), 'options': meta.get('options'),
            'eligible': reason is None, 'reason': reason, 'time_status': validity['status'], 'time_enforced': mode == 'enforce'}


def task_review(root, task_id):
    """Inspect exact current versions; Wiki history stores metadata, not old bodies."""
    from .recall import load_recall_params
    task = tasks.show(root, task_id)
    old_goal = task['agreement']['goal']
    try:
        current_goal = goal(root, old_goal['path'])
        current_goal['eligible'] = handoff._meta(current_goal['text'].encode('utf-8')).get('type') == 'goal'
    except (OSError, ValueError, UnicodeError):
        current_goal = None
    mode = load_recall_params(root).get('memory_validity', 'shadow')
    if mode not in {'shadow', 'enforce'}:
        raise ValueError('memory_validity must be shadow or enforce')
    old_sources = {v['path']: v for v in task['agreement']['knowledge']}
    paths = list(islice((root / 'wiki').rglob('*.md'), 101))
    candidates = list(dict.fromkeys([*old_sources, *(v.relative_to(root).as_posix() for v in paths[:100])]))
    sources, choices = [], []
    for relative in candidates:
        try:
            current = _current_wiki(root, relative, mode)
        except (OSError, ValueError, TypeError, UnicodeError):
            current = None
        if relative in old_sources:
            before = old_sources[relative]
            sources.append({'path': relative, 'before': before, 'current': current,
                'historical_bytes_available': current is not None and current['sha256'] == before['sha256']})
        if current is not None:
            choices.append({key: current[key] for key in ('path', 'title', 'sha256', 'eligible', 'reason', 'time_status', 'time_enforced')})
    return {'task_id': task_id, 'revision': task['revision'], 'lifecycle': task['lifecycle'],
            'knowledge_base': str(root), 'goal': {'before': old_goal, 'current': current_goal},
            'sources': sources, 'choices': choices, 'truncated': len(paths) > 100,
            'memory_validity_mode': mode, 'state_mutated': False}


def accept_task_sources(root, request):
    from .recall import load_recall_params
    if load_recall_params(root).get('memory_validity', 'shadow') not in {'shadow', 'enforce'}:
        raise ValueError('memory_validity must be shadow or enforce')
    task = tasks.show(root, request.get('task_id'))
    if request.get('accept_changes') is not True or type(request.get('expected_revision')) is not int:
        raise ValueError('Inspect the sources and explicitly confirm the exact task revision')
    chosen = request.get('wiki')
    if not isinstance(chosen, list) or len(chosen) > handoff.MAX_KNOWLEDGE:
        raise ValueError('Choose at most 16 reviewed Wiki sources')
    expected = {task['agreement']['goal']['path']: request.get('expected_goal_sha256')}
    paths = []
    for ref in chosen:
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('Inspect each chosen Wiki version first')
        handoff._relative(ref['path'], 'wiki')
        paths.append(ref['path']); expected[ref['path']] = ref['sha256']
    if len(paths) != len(set(paths)):
        raise ValueError('Choose distinct Wiki sources')
    return tasks.update_sources(root, task['task_id'], request['expected_revision'], paths, expected_sources=expected)


def save_task_progress(root, request):
    task = tasks.show(root, request.get('task_id'))
    if (type(request.get('expected_revision')) is not int
            or request.get('expected_agreement_sha256') != task['agreement']['sha256']):
        raise ValueError('Task agreement changed; inspect before saving progress')
    artifacts = request.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) > 16 or any(not isinstance(v, str) for v in artifacts) or len(set(artifacts)) != len(artifacts):
        raise ValueError('Choose at most 16 distinct artifact paths')
    return tasks.checkpoint(root, task['task_id'], request['expected_revision'], request.get('progress'), request.get('next_action'), artifacts)


def task_handoff(root, task_id, expected_revision):
    task = tasks.show(root, task_id)
    if type(expected_revision) is not int or task['revision'] != expected_revision:
        raise ValueError('Task revision changed; inspect before copying handoff')
    return {'task_id': task_id, 'revision': task['revision'], 'knowledge_base': str(root),
            'text': f'知识库：{root.resolve()}\n\n' + tasks._handoff_text(task), 'state_mutated': False}


def task_sources(root, task_id, expected_revision):
    """Version references, not reconstructed historical bytes or execution evidence."""
    task = tasks.show(root, task_id)
    if type(expected_revision) is not int or task['revision'] != expected_revision:
        raise ValueError('Task revision changed; inspect its sources again')
    versions = {}
    current_paths = {v['path'] for v in task['agreement']['knowledge']} | {v['source_path'] for v in task.get('uses', [])}
    def add(entry, current):
        revision = entry['revision']
        for ref, used in [*( (v, False) for v in entry['agreement']['knowledge']), *( (v, True) for v in entry.get('uses', []))]:
            path = ref.get('source_path') if used else ref.get('path')
            digest = ref.get('source_sha256') if used else ref.get('sha256')
            handoff._relative(path, 'wiki')
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid source version; task record preserved')
            key = (path, digest)
            relation = 'use' if current and used else 'agreement' if current else 'replaced' if path in current_paths else 'history'
            item = versions.setdefault(key, {'path':path, 'sha256':digest, 'title':ref.get('title') or Path(path).stem,
                                            'relation':relation, 'revisions':[], 'use_revisions':[]})
            if revision not in item['revisions']: item['revisions'].append(revision)
            if used and revision not in item['use_revisions']: item['use_revisions'].append(revision)
    add(task, True)
    for entry in reversed(task['history']): add(entry, False)
    return {'task_id':task_id, 'revision':task['revision'], 'knowledge_base':str(root),
            'sources':list(versions.values()), 'state_mutated':False}


def propose_task_correction(root, request):
    """Bridge explicit task feedback to existing private pending review; never approve."""
    from . import store
    path = tasks._path(root, request.get('task_id'))
    # Same ordering as task writes: task lock first, then private feedback lock.
    with store._file_lock(path.with_suffix('.lock')):
        return _propose_task_correction(root, request)


def _propose_task_correction(root, request):
    from . import feedback
    task = tasks.show(root, request.get('task_id'))
    if (type(request.get('expected_revision')) is not int or task['revision'] != request['expected_revision']
            or request.get('expected_agreement_sha256') != task['agreement']['sha256']):
        raise ValueError('Task revision or agreement changed; inspect before recording correction')
    tasks.require_active_scope(root, task['task_id'])
    if task['status'] != 'current': raise ValueError('Task sources need review before recording correction')
    selection = feedback.scope(request.get('scope'))
    if selection['task'] != task['task_id']: raise ValueError('Correction scope differs from task')
    identifier = feedback._id(request.get('request_id'))
    reason = feedback._text(request.get('reason'), 'reason', 2000)
    summary = feedback._text(request.get('summary'), 'summary', 2000)
    source = request.get('source')
    refs = [{'path':v['path'], 'sha256':v['sha256']} for v in task['agreement']['knowledge']]
    refs += [{'path':v['source_path'], 'sha256':v['source_sha256']} for v in task.get('uses', [])]
    if not isinstance(source, dict) or set(source) != {'path','sha256'} or source not in refs:
        raise ValueError('Choose an inspected current task source')
    if feedback._asset(root, source['path'])['sha256'] != source['sha256']:
        raise ValueError('Source changed; inspect before recording correction')
    artifact = request.get('artifact')
    if artifact is not None and (artifact not in task['artifacts'] or tasks._artifact(root, artifact.get('path')) != artifact):
        raise ValueError('Artifact changed; inspect before recording correction')
    context = {'task_id':task['task_id'], 'revision':task['revision'], 'artifact':artifact,
               'source':source, 'proposal_sha256':hashlib.sha256(summary.encode('utf-8')).hexdigest()}
    evidence_reason = reason + '\n\n任务修订与产物引用（仅为记录，不证明执行正确）：\n' + json.dumps(context, ensure_ascii=False)
    feedback.record(root, {'scope':selection, 'event_id':identifier, 'action':'revised', 'reason':evidence_reason,
                          'source':'user_reported', 'agreement':task['agreement'], 'asset_path':source['path']})
    inspected = feedback.inspect(root, selection)
    event = next(v for v in inspected['events'] if v['payload']['event_id'] == identifier)
    if {key:event['payload']['asset'][key] for key in ('path','sha256')} != source:
        return {'status':'partial', 'event_id':identifier, 'candidate_id':None,
                'message':'记录时来源发生变化，未生成学习建议；请重新核对来源。', 'wiki_promoted':False}
    existing = next((v for v in inspected['candidates'] if v['candidate_id'] == identifier), None)
    title = summary.strip().splitlines()[0][:100]
    if existing:
        if existing['summary'] != summary or existing['title'] != title or existing['event_ids'] != [identifier]:
            raise ValueError('Correction ID already has different content; existing record preserved')
        candidate = existing
    else:
        try:
            candidate = feedback.propose(root, {'scope':selection, 'candidate_id':identifier, 'event_ids':[identifier],
                                               'title':title, 'summary':summary})
        except (OSError, ValueError):
            return {'status':'partial', 'event_id':identifier, 'candidate_id':None,
                    'message':'修正记录已保存，学习建议尚未生成；可保留当前输入重试。', 'wiki_promoted':False}
    return {'status':'recorded', 'event_id':identifier, 'candidate_id':candidate['candidate_id'],
            'candidate_status':candidate['effective_status'], 'review_path':'/review?task=' + task['task_id'],
            'wiki_promoted':False}


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
            value = tasks.start(root, task_id, relative, paths, expected_sources=expected)
            if request.get('start_now') is True:
                tasks.select(root, root, task_id)
                value['selected'] = True
            return value
        except (ValueError, OSError):
            raise ValueError('Task not created; Goal preserved. Reload and select that Goal before retrying') from None


def _text_file(root, relative, suffixes):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or any(not s or s.startswith('.') for s in relative.split('/')):
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


def artifact_source_links(root, relative, text):
    """Resolve links for reading; preserve the exact archived output bytes."""
    import posixpath
    import re
    from urllib.parse import urlsplit, unquote
    origin = None
    parts = relative.split('/')
    if len(parts) > 2 and parts[0] == 'outputs' and re.fullmatch(r'(claude|codex)-[0-9a-f]{40}', parts[1]):
        try:
            run = tasks._read(tasks._inside(root, '.oks/workflow-runs/' + parts[1] + '.json'))
            if any(ref.get('path') == relative for ref in run.get('artifacts', [])) and run.get('workspace'):
                origin = Path(run['workspace']).joinpath(*parts[2:]).parent
        except (OSError, ValueError, TypeError):
            pass
    links = {}
    for target in re.findall(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', text):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        value = unquote(parsed.path)
        resolved = posixpath.normpath(value.lstrip('/') if value.startswith('/') else posixpath.join(posixpath.dirname(relative), value))
        if origin and not value.startswith('/'):
            original = (origin / value).resolve()
            if original.is_relative_to(root.resolve()):
                resolved = original.relative_to(root.resolve()).as_posix()
        if resolved.split('/')[0] in {'raw', 'wiki', 'reports', 'outputs', 'artifacts'} and not any(part.startswith('.') for part in resolved.split('/')):
            try:
                local = tasks._inside(root, resolved)
                if local.suffix.lower() in {'.md', '.txt'} and local.is_file():
                    links[target] = resolved
            except (OSError, ValueError):
                continue
    return links


def artifact_source(root, task_id, relative, revision, source):
    """Read only a local source actually linked by a registered task output."""
    output = artifact(root, task_id, relative, revision)
    if source not in artifact_source_links(root, relative, output['text']).values():
        raise ValueError('Source must be linked from this registered output')
    result = _text_file(root, source, {'.md', '.txt'})
    return {**result, 'status': 'current_source', 'notice': '当前引用原文；没有保存该来源的历史正文。'}


def draft(root, relative, review_sha256=None):
    handoff._relative(relative, 'drafts')
    if len(relative.split('/')) != 2:
        raise ValueError('Review a Draft directly under drafts/; nested Draft promotion is unsupported')
    from .task_workflow import draft_context, reviewed_candidate, candidate_disposition
    try:
        result = _text_file(root, relative, {'.md'})
    except FileNotFoundError:
        result = None
    from . import draft_review
    ordinary = draft_review.read_receipt(root, Path(relative).stem,
        review_sha256 or (result['sha256'] if result is not None else None))
    if ordinary is not None:
        original = draft_review.read_original(root, ordinary)
        if original is None:
            raise ValueError('Original review snapshot is unavailable; existing decision retained')
        value = {'path': relative, 'text': original.decode('utf-8-sig'),
                 'sha256': ordinary['draft_sha256'], 'format': 'markdown',
                 'text_role': 'reviewed_draft', 'review_status': ordinary['decision'],
                 'reviewed_at': ordinary['decided_at'], 'original_available': True,
                 'snapshot_status': 'preserved_original'}
        if ordinary.get('wiki_path'):
            value['wiki_path'] = ordinary['wiki_path']
            try:
                value['reuse'] = learning_reuse(root, ordinary['wiki_path'])
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                value['reuse'] = {'status': 'unavailable', 'tasks': []}
        return value
    disposition = candidate_disposition(root, relative, sha256=result['sha256']) if result is not None else None
    if review_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', review_sha256):
        raise ValueError('Choose an exact review revision')
    reviewed = reviewed_candidate(root, relative, sha256=review_sha256 or (result['sha256'] if disposition == 'promoted' else None))
    if review_sha256 is not None and not reviewed:
        raise ValueError('Reviewed revision unavailable; current Draft is not that review')
    if reviewed and (review_sha256 is not None or result is None or disposition == 'promoted'):
        if disposition == 'promoted' and not reviewed['original_available'] and (review_sha256 is None or result['sha256'] == review_sha256):
            reviewed.update(original_available=True, text=result['text'], sha256=result['sha256'], snapshot_status='retained_original')
        if reviewed['original_available']:
            result = {'path': relative, 'text': reviewed['text'], 'sha256': reviewed['sha256'], 'format': 'markdown', 'text_role': 'reviewed_draft'}
        else:
            result = {**_text_file(root, reviewed['wiki_path'], {'.md'}), 'path': relative, 'text_role': 'current_wiki'}
        result.update({key: reviewed.get(key) for key in ('review_status', 'wiki_path', 'reviewed_at', 'snapshot_status', 'original_available')})
        context = reviewed.get('workflow_source')
        if not context:
            # Legacy records link to their actual Task but cannot recover a
            # deleted Draft. Never label the current Wiki as that original.
            for path in islice(tasks._inside(root, '.oks/workflow-runs').glob('*.json'), 100):
                try:
                    run = tasks._read(tasks._inside(root, path.relative_to(root).as_posix()))
                    if relative in run.get('draft_paths', []):
                        context = {key: run[key] for key in ('task_id', 'agreement_sha256', 'run_id', 'artifacts')}
                        break
                except (OSError, ValueError, KeyError):
                    continue
        if isinstance(context, dict):
            result['workflow_context'] = {**context, 'source_status': 'historical'}
        try:
            result['reuse'] = learning_reuse(root, reviewed['wiki_path'], origin_task=context.get('task_id') if isinstance(context, dict) else None)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            result['reuse'] = {'status': 'unavailable', 'tasks': []}
        return result
    if result is None:
        raise FileNotFoundError('Draft or unambiguous reviewed Wiki not found')
    result['review_status'] = disposition if disposition in ('rejected', 'not_proposed') else 'draft'
    context = draft_context(root, result['text'])
    if context is None and relative.startswith('drafts/task-learning-'):
        context = {'task_id': '', 'source_status': 'changed', 'warning': '任务来源标记缺失，请重新整理候选。'}
    if context:
        result['workflow_context'] = context
    return result


def learning_reuse(root, relative, *, origin_task=None):
    """Read-only retained receipts for later tasks; no inferred adoption or writes."""
    from . import retrieval_debug
    handoff._relative(relative, 'wiki')
    source = _text_file(root, relative, {'.md'})
    result = {'source_path': relative, 'source_sha256': source['sha256'],
              'scope': 'retained_records_current_version', 'tasks': [], 'read_count': 0, 'citation_count': 0}
    if not handoff._reviewed(handoff._meta(source['text'].encode('utf-8'))):
        return {**result, 'status': 'not_reviewed'}
    try:
        data = retrieval_debug.overview(root)
        grouped = {}
        for key, count in [('native_reads', 'read_count'), ('native_uses', 'citation_count')]:
            for receipt in data.get(key, []):
                tid = receipt.get('task_id')
                if (not isinstance(tid, str) or not tid or tid == origin_task
                        or receipt.get('source_path') != relative or receipt.get('source_sha256') != source['sha256']):
                    continue
                row = grouped.setdefault(tid, {'task_id': tid, 'read_count': 0, 'citation_count': 0})
                row[count] += 1
                result[count] += 1
        for tid, row in list(grouped.items())[:20]:
            try:
                task = tasks.show(root, tid)
                row['title'] = handoff._meta(task['agreement']['goal']['text'].encode('utf-8')).get('title') or tid
                result['tasks'].append(row)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        result['truncated'] = len(grouped) > 20
        return {**result, 'status': 'ok'}
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, 'status': 'unavailable'}


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
