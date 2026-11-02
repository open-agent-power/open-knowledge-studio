"""Join native host work to existing Task, Draft review, Mail and recall flows."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from itertools import islice

import frontmatter
import yaml

from . import handoff, store, tasks
from .security.redaction import redact_text, redact_mapping
from .security.sensitive_fields import SENSITIVE_KEYS

CONFIG = 'settings/task-workflow.json'
MAX_RUNS = 100
EXCLUDED = {'raw', 'wiki', 'drafts', 'profiles', 'settings', 'mail', '_meta', '.oks', '.claude', '.codex', '.git'}


def enabled(root, host=None):
    path = tasks._inside(root, CONFIG)
    if not path.exists():
        return False
    value = tasks._read(path)
    return value.get('schema_version') == 'task-workflow/v1' and value.get('enabled') is True and (
        host in value.get('hosts', []) if host else bool(value.get('hosts')))


def instructions(task, root=None):
    goal = frontmatter.loads(task['agreement']['goal']['text']).content
    return (f"当前任务：{task['task_id']}\n{goal[:6000]}\n\n" +
            (f'知识库：{root}\n' if root else '') +
            '请实际写出用户要求的产物，不要把知识直接写入Wiki。'
            '宿主会自动登记实际写出的产物与返回，不需要手写Mail或重复checkpoint。'
            '完成后若确有可复用经验，请在最终回答中用“## 学习建议”单独写出：具体改法、适用条件、依据文件。'
            '没有经验就明确写“无”，不凑建议。建议只会进入待审草稿，不能代签人工审核。')


def _selection(root, cwd):
    selected = tasks.binding(root, Path(cwd))
    if not selected:
        return None, False
    value = tasks.show(root, selected['task_id'])
    return value, bool(selected.get('feedback_subject') or selected.get('feedback_project'))


def _explicit_goal(root, cwd, payload, host):
    """Only an explicit native start intent creates a Goal; ordinary chat does not."""
    text = payload.get('prompt')
    if payload.get('hook_event_name') != 'UserPromptSubmit' or not isinstance(text, str):
        return
    match = re.match(r'^\s*(?:开始任务|新建任务|已确认目标|这项任务目标已经确认)\s*[:：]\s*(\S[\s\S]*)$', text)
    if not match:
        return
    if len(text) > 8000:
        raise ValueError('Confirmed Goal exceeds task capacity; use an explicit source reference')
    session, _, _ = _identity(payload, host)
    identifier = 'task-' + hashlib.sha256(json.dumps([host, session, text]).encode()).hexdigest()[:16]
    from . import workspace
    with store._file_lock(tasks._inside(root, '.oks/locks/workflow-goals.lock')):
        if not tasks._path(root, identifier).exists():
            title = match.group(1).splitlines()[0].strip()[:120]
            workspace.create_task(root, {'task_id': identifier, 'new_goal': {'title': title, 'text': text.strip()}, 'wiki': []})
        tasks.select(root, Path(cwd), identifier)


def _identity(payload, host):
    session = payload.get('session_id')
    child = payload.get('agent_id') or 'main'
    if not isinstance(session, str) or not session or len(session) > 240 or not isinstance(child, str) or len(child) > 240:
        raise ValueError('Missing native execution identity')
    if host not in {'claude', 'codex'}:
        raise ValueError('Unsupported workflow host')
    digest = hashlib.sha256(json.dumps([host, session, child]).encode()).hexdigest()
    return session, child, f'{host}-{digest[:40]}'


def _run_path(root, run_id):
    if not re.fullmatch(r'(claude|codex)-[0-9a-f]{40}', run_id):
        raise ValueError('Invalid native run reference')
    return tasks._inside(root, f'.oks/workflow-runs/{run_id}.json')


def _writes(payload):
    if payload.get('hook_event_name') != 'PostToolUse' or not isinstance(payload.get('tool_input'), dict):
        return []
    if isinstance(payload.get('tool_response'), dict) and payload['tool_response'].get('is_error'):
        return []
    tool = payload.get('tool_name')
    data = payload['tool_input']
    if tool in {'Write', 'Edit', 'MultiEdit', 'write', 'edit'}:
        value = data.get('file_path') or data.get('path')
        return [value] if isinstance(value, str) and value else []
    if tool == 'apply_patch':
        patch = data.get('patch') or data.get('command') or data.get('input') or ''
        return re.findall(r'^\*\*\* (?:Add|Update) File:\s*(.+)$', str(patch), re.M)
    return []


def _sensitive_structure(value):
    if isinstance(value, dict):
        names = {name.casefold().replace('-', '_') for name in SENSITIVE_KEYS}
        return any(str(key).casefold().replace('-', '_') in names or _sensitive_structure(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_sensitive_structure(item) for item in value)
    return False


def _artifact(root, cwd, value, run_id):
    path = Path(value)
    if not path.is_absolute():
        path = Path(cwd) / path
    if path != path.resolve():
        raise ValueError('Output path contains a symlink')
    resolved = path.resolve()
    if resolved.is_relative_to(root.resolve()):
        relative = resolved.relative_to(root.resolve()).as_posix()
        if relative.split('/')[0] in EXCLUDED or any(part.startswith('.') for part in relative.split('/')):
            return None
    else:
        # Only an actual successful write within this explicitly paired workspace
        # can be archived. Never scan unrelated files or follow a supplied URI.
        relative_project = resolved.relative_to(Path(cwd).resolve()).as_posix()
        if any(part.startswith('.') for part in relative_project.split('/')) or relative_project.split('/')[0] in EXCLUDED:
            return None
        if resolved.suffix.lower() not in {'.md', '.txt', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.yaml', '.yml', '.csv'}:
            raise ValueError('External output format needs explicit archival')
        relative = f'outputs/{run_id}/{relative_project}'
    # Registration also makes an in-KB output visible in Studio. Apply the same
    # guard before either registering that file or copying an external output.
    with resolved.open('rb') as handle:
        raw = handle.read(tasks.MAX_BYTES + 1)
    if len(raw) > tasks.MAX_BYTES:
        raise ValueError('Output exceeds size limit')
    text = raw.decode('utf-8-sig')
    if redact_text(text) != text:
        raise ValueError('Output contains credential patterns')
    if resolved.suffix.lower() in {'.json', '.yaml', '.yml'}:
        try:
            data = json.loads(text) if resolved.suffix.lower() == '.json' else yaml.safe_load(text)
        except (ValueError, yaml.YAMLError) as exc:
            raise ValueError('Structured output needs valid content before archival') from exc
        if redact_mapping(data) != data or _sensitive_structure(data):
            raise ValueError('Structured output contains sensitive fields')
    if not resolved.is_relative_to(root.resolve()):
        target = tasks._inside(root, relative)
        store._atomic_write(target, raw)
    if relative.split('/')[0] in EXCLUDED or any(part.startswith('.') for part in relative.split('/')):
        return None
    return tasks._artifact(root, relative)


def _lesson(text):
    if not isinstance(text, str):
        return ''
    match = re.search(r'^##\s+(?:学习建议|可复用经验|Learning)(?:\s*[:：])?\s*\n([\s\S]*?)(?=^##\s|\Z)', text, re.M)
    if not match:
        return ''
    value = redact_text(match.group(1)).strip()[:3000]
    return '' if re.fullmatch(r'(无|暂无|无可复用经验|暂无可复用经验|none)[。.!！\s]*', value, re.I) else value


def _all_outputs(root, run):
    outputs = {ref['path']: ref for ref in run['artifacts']}
    if run['child_id'] == 'main':
        folder = tasks._inside(root, '.oks/workflow-runs')
        for path in sorted(folder.glob('*.json'))[:MAX_RUNS]:
            try:
                child = tasks._read(path)
            except (OSError, ValueError, UnicodeError):
                continue
            if child.get('native_session') == run['native_session'] and child.get('task_id') == run['task_id']:
                outputs.update({ref['path']: ref for ref in child.get('artifacts', [])})
    return list(outputs.values())[:16]


def _propose(root, run, lesson, artifacts):
    basis = [run['task_id'], run['agreement_sha256'], lesson, sorted(artifacts, key=lambda r:r['path'])]
    legacy = 'drafts/task-learning-' + hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:28] + '.md'
    signature = hashlib.sha256(json.dumps([run['run_id'], *basis], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:28]
    relative = f'drafts/task-learning-{signature}.md'
    if legacy in run.get('draft_paths', []):
        relative = legacy  # Replay of that run's pre-upgrade proposal only.
    path = tasks._inside(root, relative)
    meta = {'title': '任务经验 · ' + run['title'][:70], 'status': 'draft', 'draft_type': 'strategy',
            'draft_area': 'computing', 'source_type': 'distilled', 'human_approved': False,
            'drafted_at': datetime.now(UTC).isoformat(), 'tags': ['task-learning'],
            'workflow_source': {'task_id': run['task_id'], 'agreement_sha256': run['agreement_sha256'],
                                'run_id': run['run_id'], 'artifacts': artifacts},
            'sources': [ref['path'] for ref in artifacts]}
    source_lines = '\n'.join(f"- [{ref['path']}](/{ref['path']}) · SHA256 `{ref['sha256']}`" for ref in artifacts)
    content = '---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + '---\n\n' + lesson + '\n\n## 本次依据\n\n' + source_lines + '\n'
    with store._file_lock(path.with_suffix('.lock')):
        if not path.exists():
            if not _promoted(root, relative) and relative not in _rejections(root):
                store._atomic_write(path, content)
    return relative


def _promoted(root, relative):
    matches = _promotions(root).get(relative, [])
    return matches[0]['wiki_path'] if len(matches) == 1 else None


def _promotions(root):
    result = {}
    for path in islice((root / 'wiki').rglob('*.md'), 10000):
        try:
            safe = tasks._inside(root, path.relative_to(root).as_posix())
            meta = store.parse_wiki_file(safe) or {}
            if not meta.get('human_reviewed_at') or not isinstance(meta.get('source_candidates'), list):
                continue
            for relative in meta['source_candidates']:
                if isinstance(relative, str):
                    reviews = [entry for entry in meta.get('workflow_reviews', []) if isinstance(entry, dict) and isinstance(entry.get('reviewed_source'), dict) and entry['reviewed_source'].get('candidate_path') == relative] if isinstance(meta.get('workflow_reviews'), list) else []
                    reviews = reviews or [{'workflow_source': meta.get('workflow_source'), 'reviewed_source': meta.get('reviewed_source'), 'reviewed_at': str(meta['human_reviewed_at'])}]
                    for review in reviews:
                        result.setdefault(relative, []).append({'wiki_path': path.relative_to(root).as_posix(),
                        'title': meta.get('title') or '任务经验',
                        'workflow_source': review.get('workflow_source'), 'reviewed_source': review.get('reviewed_source'), 'reviewed_at': str(review.get('reviewed_at') or meta['human_reviewed_at'])})
        except (OSError, ValueError, TypeError):
            continue
    return result


def _rejections(root):
    result = {}
    folder = tasks._inside(root, 'drafts/rejected')
    for path in islice(folder.glob('*.json'), 10000):
        try:
            receipt = tasks._read(tasks._inside(root, path.relative_to(root).as_posix()))
            slug = receipt.get('draft_slug', '')
            if receipt.get('decision') == 'rejected' and re.fullmatch(r'task-learning-[0-9a-f]{28}', slug):
                result['drafts/' + slug + '.md'] = receipt
        except (OSError, ValueError, TypeError):
            continue
    return result


def candidate_disposition(root, relative, raw=None, *, promotions=None, rejections=None, sha256=None):
    """Classify retained originals by exact reviewed/rejected bytes, not their path."""
    if not re.fullmatch(r'drafts/task-learning-[0-9a-f]{28}\.md', relative):
        return None
    try:
        if sha256 is None and raw is None:
            with tasks._inside(root, relative).open('rb') as handle:
                raw = handle.read(tasks.MAX_BYTES + 1)
            if len(raw) > tasks.MAX_BYTES:
                return None
    except OSError:
        return None
    digest = sha256 if sha256 is not None else hashlib.sha256(raw).hexdigest()
    matches = (promotions if promotions is not None else _promotions(root)).get(relative, [])
    exact = [item for item in matches if isinstance(item.get('reviewed_source'), dict) and item['reviewed_source'].get('sha256') == digest]
    if len(exact) == 1:
        return 'promoted'
    receipt = (rejections if rejections is not None else _rejections(root)).get(relative, {})
    return 'rejected' if receipt.get('draft_bytes_sha256') == digest else None


def preserve_review(root, relative, raw):
    """Content-addressed original evidence; this write does not approve anything."""
    digest = hashlib.sha256(raw).hexdigest()
    snapshot = f'.oks/reviewed-drafts/{digest}.md'
    path = tasks._inside(root, snapshot)
    with store._file_lock(path.with_suffix('.lock')):
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('Original review evidence changed; Draft retained')
        if not path.exists():
            store._atomic_write(path, raw)
    return {'path': snapshot, 'sha256': digest, 'candidate_path': relative}


def reviewed_candidate(root, relative, promotions=None, sha256=None):
    matches = (promotions if promotions is not None else _promotions(root)).get(relative, [])
    if sha256 is not None:
        matches = [item for item in matches if isinstance(item.get('reviewed_source'), dict) and item['reviewed_source'].get('sha256') == sha256]
    if len(matches) != 1:
        return None
    result = dict(matches[0])
    proof = result.get('reviewed_source')
    result.update(review_status='promoted', original_available=False, snapshot_status='legacy_unavailable')
    if not isinstance(proof, dict):
        return result
    digest = proof.get('sha256', '')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or proof.get('path') != f'.oks/reviewed-drafts/{digest}.md' or proof.get('candidate_path') != relative:
        result['snapshot_status'] = 'invalid'
        return result
    try:
        path = tasks._inside(root, proof['path'])
        with path.open('rb') as handle:
            raw = handle.read(tasks.MAX_BYTES + 1)
        if len(raw) > tasks.MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Review evidence changed')
        result.update(original_available=True, snapshot_status='preserved', text=raw.decode('utf-8-sig'), sha256=digest)
    except (OSError, ValueError, UnicodeError):
        result['snapshot_status'] = 'unavailable'
    return result


def observe(root, payload, host, *, thread_id=None):
    if not enabled(root, host):
        return {'status': 'disabled'}
    event = payload.get('hook_event_name')
    paths = _writes(payload)
    if event not in {'SessionStart', 'UserPromptSubmit', 'SubagentStart', 'Stop', 'SubagentStop'} and not paths:
        return {'status': 'skipped'}
    session, child, _ = _identity(payload, host)
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return {'status': 'partial', 'warning': '宿主没有提供工作目录，未自动关联任务。'}
    _explicit_goal(root, cwd, payload, host)
    task, private = _selection(root, cwd)
    if not task:
        context = (f'OKS知识库已接入：{root}。本工作目录尚未选择任务。'
                   '当用户明确确认要执行的目标时，使用一次命令开始并选定任务：'
                   f'oks task begin --title "任务名称" --goal "已确认的目标与验收要求" --path "{root}"。'
                   '普通问答不要自动创建任务；已有任务先检查，不覆盖、不擅自接受来源变化。')
        return {'status': 'no_task', **({'context': context} if event in {'SessionStart','UserPromptSubmit'} else {})}
    if not private and event in {'SessionStart', 'UserPromptSubmit'}:
        from .host_collaboration import _profile
        _profile(root, host, f'{host.title()} 协调者', '执行已确认任务并提交产物与学习建议')
    if event == 'SessionStart':
        # The next user prompt may explicitly select a different task. Merely
        # connecting a session must not leave a phantom running job on the old one.
        return {'status': 'ready', 'context': instructions(task, root)}
    digest = hashlib.sha256(json.dumps([host, session, child, task['task_id'], task['agreement']['sha256']]).encode()).hexdigest()
    run_id = f'{host}-{digest[:40]}'
    path = _run_path(root, run_id)
    with store._file_lock(path.with_suffix('.lock')):
        if path.exists():
            run = tasks._read(path)
        else:
            if len(list(path.parent.glob('*.json'))) >= MAX_RUNS:
                raise ValueError('Workflow history capacity reached; preserve and archive existing runs')
            run = {'schema_version': 'task-native-run/v1', 'run_id': run_id, 'host': host,
                   'native_session': session, 'child_id': child, 'task_id': task['task_id'],
                   'workspace': str(Path(cwd).resolve()),
                   'agreement_sha256': task['agreement']['sha256'], 'title': frontmatter.loads(task['agreement']['goal']['text']).get('title', task['task_id']),
                   'phase': 'working', 'status': 'working', 'artifacts': [], 'draft_paths': [],
                   'draft_path': None, 'thread_id': None, 'learning_status': 'not_proposed', 'return_events': []}
        run['updated_at'] = datetime.now(UTC).isoformat()
        if thread_id:
            run['thread_id'] = thread_id
        if run['task_id'] != task['task_id'] or run['agreement_sha256'] != task['agreement']['sha256'] or task['status'] != 'current' or task['lifecycle'] != 'active':
            run.update(phase='partial', status='source_changed', learning_status='source_changed', warning='任务或来源已变化，自动归档暂停；请先核对。')
            tasks._save(path, run)
            return run
        for output in paths:
            try:
                candidate_path = Path(output)
                if not candidate_path.is_absolute():
                    candidate_path = Path(cwd) / candidate_path
                if private and not candidate_path.resolve().is_relative_to(root.resolve()):
                    run.update(phase='partial', warning='私人范围的外部产物保留在原项目，未自动复制到共享知识库。')
                    continue
                ref = _artifact(root, cwd, output, run_id)
                if ref:
                    existing = {item['path']: item for item in run['artifacts']}
                    existing[ref['path']] = ref
                    if len(existing) > 16:
                        raise ValueError('Output capacity reached')
                    run['artifacts'] = list(existing.values())
            except (OSError, ValueError):
                run.update(phase='partial', warning='部分写入文件不在可归档范围、超出大小限制或已变化；原文件保留。')
        if event in {'Stop', 'SubagentStop'}:
            text = payload.get('last_assistant_message') or ''
            event_id = hashlib.sha256(json.dumps([run_id, text, run['artifacts']], sort_keys=True).encode()).hexdigest()
            if event_id not in run['return_events']:
                refs = _all_outputs(root, run)
                try:
                    # Validate every observed version again immediately before recording it.
                    for ref in refs:
                        if tasks._artifact(root, ref['path']) != ref:
                            raise ValueError('Observed output changed')
                    if refs:
                        captured = tasks.capture_outputs(root, task['task_id'], run['agreement_sha256'], event_id, refs, host=host, run_id=run_id)
                        run['task_revision'] = captured['revision']
                        run['artifacts'] = refs
                    lesson = _lesson(text)
                    if private:
                        run['learning_status'] = 'private_scope'
                    elif lesson and refs:
                        candidate = _propose(root, run, lesson, refs)
                        if candidate not in run['draft_paths']:
                            run['draft_paths'].append(candidate)
                        disposition = candidate_disposition(root, candidate)
                        run.update(draft_path=candidate, learning_status='rejected' if disposition == 'rejected' or candidate in _rejections(root) and not tasks._inside(root, candidate).exists() else 'pending_review')
                    else:
                        run['learning_status'] = 'not_proposed'
                    run['return_events'].append(event_id)
                    run.update(phase='returned' if text else 'partial', status='returned' if text else 'unknown')
                    if not text:
                        run['warning'] = '宿主没有提供返回正文，结果仍待确认。'
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    run.update(phase='partial', status='partial', learning_status='error', warning='自动归档或候选整理未完成；已保存的文件与记录保留，可重试。')
        tasks._save(path, run)
    if event in {'SessionStart', 'UserPromptSubmit', 'SubagentStart'}:
        return {**run, 'context': instructions(task, root)}
    return run


def draft_context(root, text):
    meta = frontmatter.loads(text)
    source = meta.get('workflow_source')
    if not isinstance(source, dict):
        return None
    result = dict(source)
    try:
        task = tasks.show(root, source['task_id'])
        if task['agreement']['sha256'] != source['agreement_sha256'] or task['status'] != 'current':
            raise ValueError('Task sources changed')
        for ref in source['artifacts']:
            if tasks._artifact(root, ref['path']) != ref:
                raise ValueError('Output changed')
        result['source_status'] = 'current'
    except (OSError, ValueError, KeyError, TypeError):
        result['source_status'] = 'changed'
        result['warning'] = '任务依据或产物已变化，请重新整理候选。'
    return result


def require_current_draft(root, text):
    context = draft_context(root, text)
    if context and context['source_status'] != 'current':
        raise ValueError('Task learning sources changed; candidate retained for re-review')


def overview(root, task_id):
    tasks._id(task_id)
    folder = tasks._inside(root, '.oks/workflow-runs')
    runs, connections, drafts, threads, groups = [], [], {}, {}, {}
    promotions, rejections = _promotions(root), _rejections(root)
    unreadable = 0
    for path in sorted(folder.glob('*.json'))[:MAX_RUNS]:
        try:
            value = tasks._read(path)
            if value.get('task_id') != task_id:
                continue
            row = {k: value.get(k) for k in ('run_id', 'host', 'phase', 'status', 'updated_at', 'artifacts', 'draft_path', 'thread_id', 'warning', 'learning_status', 'task_revision')}
            row['role'] = 'main' if value.get('child_id') == 'main' else 'collaborator'
            connection_only = not value.get('artifacts') and not value.get('draft_paths') and not value.get('return_events') and not value.get('thread_id') and value.get('status') == 'working'
            row['evidence_state'] = 'connection_only' if connection_only else 'partial' if value.get('warning') else 'return_observed' if value.get('return_events') else 'output_observed' if value.get('artifacts') else 'handoff_observed'
            (connections if connection_only else runs).append(row)
            if row['thread_id']:
                threads[row['thread_id']] = {'thread_id': row['thread_id'], 'title': '查看协作记录'}
            for relative in value.get('draft_paths', []):
                if not re.fullmatch(r'drafts/task-learning-[0-9a-f]{28}\.md', relative):
                    continue
                target = tasks._inside(root, relative)
                source = {key: value.get(key) for key in ('task_id', 'agreement_sha256', 'artifacts')}
                if target.is_file():
                    with target.open('rb') as handle:
                        raw = handle.read(tasks.MAX_BYTES + 1)
                    if len(raw) > tasks.MAX_BYTES:
                        raise ValueError('Candidate exceeds reader capacity')
                    meta = frontmatter.loads(raw.decode('utf-8-sig'))
                    source = meta.get('workflow_source') if isinstance(meta.get('workflow_source'), dict) else source
                    item = {'path': relative, 'title': meta.get('title') or '任务经验', 'status': 'rejected' if meta.get('status') == 'rejected' else 'draft', 'sha256': hashlib.sha256(raw).hexdigest()}
                    approved = promotions.get(relative, [])
                    disposition = candidate_disposition(root, relative, raw, promotions=promotions, rejections=rejections)
                    if disposition == 'promoted':
                        exact = next(entry for entry in approved if isinstance(entry.get('reviewed_source'), dict) and entry['reviewed_source'].get('sha256') == item['sha256'])
                        item.update(status='promoted', wiki_path=exact['wiki_path'], reviewed_sha256=item['sha256'])
                    elif disposition == 'rejected':
                        item['status'] = 'rejected'
                else:
                    approved = promotions.get(relative, [])
                    if relative in rejections:
                        item = {'path': relative, 'title': rejections[relative].get('draft_title') or '任务经验', 'status': 'rejected'}
                    elif len(approved) == 1:
                        item = {'path': relative, 'title': approved[0]['title'], 'status': 'promoted', 'wiki_path': approved[0]['wiki_path']}
                        if isinstance(approved[0].get('reviewed_source'), dict):item['reviewed_sha256'] = approved[0]['reviewed_source'].get('sha256')
                        source = approved[0].get('workflow_source') if isinstance(approved[0].get('workflow_source'), dict) else source
                    else:
                        item = {'path': relative, 'title': '待核对的任务经验', 'status': 'ambiguous' if approved else 'missing'}
                item['role'] = row['role']
                drafts[relative] = item
                # Provenance grouping only. Never copy decisions, merge text,
                # or treat similar words as interchangeable knowledge.
                key = hashlib.sha256(json.dumps([source.get('task_id'), source.get('agreement_sha256'), sorted(source.get('artifacts') or [], key=lambda ref:ref['path'])], sort_keys=True).encode()).hexdigest()[:20]
                group = groups.setdefault(key, {'group_id': key, 'title': '本次产物的学习建议', 'variants': {}})
                group['variants'][relative] = item
        except (OSError, ValueError, KeyError, TypeError):
            unreadable += 1
            continue
    learning_groups = [{**group, 'variants': list(group['variants'].values())} for group in groups.values()]
    return {'enabled': enabled(root), 'task_id': task_id, 'runs': sorted(runs, key=lambda r:r['updated_at'] or '', reverse=True)[:20],
            'connections': connections, 'learning_groups': learning_groups, 'unreadable_records': unreadable,
            'drafts': list(drafts.values()), 'threads': list(threads.values())}
