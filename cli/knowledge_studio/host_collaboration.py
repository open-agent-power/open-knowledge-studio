"""Persist native subagent lifecycle facts in Mail; the host owns execution."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import frontmatter

from . import mail, store
from .security.redaction import redact_text


def _text(value, limit=4000):
    if not isinstance(value, str):
        return ''
    value = redact_text(value).strip()
    return value if len(value) <= limit else value[:limit] + '\n[内容已截断]'


def _safe_path(root, relative):
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError('Collaboration paths must not contain symlinks')
    return path


def _profile(root, agent, title, role):
    path = _safe_path(root, f'profiles/agents/{agent}.md')
    lock = _safe_path(root, path.with_suffix('.lock').relative_to(root))
    with store._file_lock(lock):
        if path.exists():
            return  # A host observation must never overwrite a maintained profile.
        meta = {'id': agent, 'title': title, 'profile_kind': 'agent', 'role': role,
                'scope': '宿主协作事件', 'status': 'active'}
        header = '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in meta.items())
        store._atomic_write(path, f'---\n{header}\n---\n\n由实际宿主事件登记的 Agent 角色。职责描述不代表身份认证、当前在线或人工验收。\n')


def _task_context(root, cwd):
    from . import tasks
    selected = tasks.binding(root, Path(cwd))
    if not selected:
        return None
    value = tasks.show(root, selected['task_id'])
    # No private subject/project labels or feedback are read or copied.
    return {k: value[k] for k in ('task_id', 'revision', 'agreement', 'status', 'lifecycle')}


def _session(root, sid, agent, machine, cwd=''):
    # Sibling native events can update the same parent registry concurrently.
    lock = mail.sessions_dir(root) / f'.{mail.safe_id(sid)}.lock'
    with store._file_lock(lock):
        mail.register_session(root, sid, agent, cwd, machine_id=machine)


def observe(root: Path, payload: dict, host: str, *, parent_agent: str = '', viewer: str = 'human') -> dict:
    """Observe one explicit host event. Replays reuse canonical Mail records.

    Start means the host started a child, not that it read or accepted work.
    Stop means a response returned, never that a business task passed.
    """
    if host not in {'claude', 'codex'}:
        raise ValueError('Unsupported collaboration host')
    event = payload.get('hook_event_name')
    if event not in {'SubagentStart', 'SubagentStop'}:
        return {'status': 'skipped', 'reason': 'unhandled_event'}
    sid, child, kind = (payload.get(k) for k in ('session_id', 'agent_id', 'agent_type'))
    if not all(isinstance(v, str) and v.strip() and len(v) <= 240 for v in (sid, child, kind)):
        return {'status': 'skipped', 'reason': 'missing_native_identity'}
    sid, child, kind = sid.strip(), child.strip(), kind.strip()
    parent = parent_agent or host
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', parent) or parent in {'human', 'all', 'unknown'}:
        raise ValueError('Collaboration requires an explicit Agent host identity')
    if viewer != 'human':
        raise ValueError('Native capture currently supports the local human viewer only')
    root = root.resolve()
    for folder in ('mail', 'profiles/agents', '.oks/host-collaboration'):
        _safe_path(root, folder)
    # Existing Mail helpers accept paths; reject redirected nested stores before
    # either reading their records or writing sessions/messages/recipient state.
    if (root / 'mail').is_dir():
        for base, directories, files in os.walk(root / 'mail', followlinks=False):
            for name in [*directories, *files]:
                _safe_path(root, (Path(base) / name).relative_to(root))
    run = hashlib.sha256(json.dumps([host, sid, child], ensure_ascii=False).encode()).hexdigest()
    role_hash = hashlib.sha256(kind.encode()).hexdigest()[:10]
    slug = re.sub(r'[^A-Za-z0-9_-]+', '-', kind).strip('-')[:28] or 'agent'
    receiver = f'{host}-{slug}-{role_hash}'
    child_session = f'{host}-child-{run[:32]}'
    ref = {'type': 'run', 'id': f'host-{host}-{run}'}
    lock = _safe_path(root, f'.oks/host-collaboration/{run}.lock')
    with store._file_lock(lock):
        rows = [row for row in mail.iter_messages(root) if ref in row['meta'].get('evidence_refs', [])]
        start = next((row for row in rows if row['meta'].get('record_kind') == 'handoff'), None)
        if event == 'SubagentStop' and start is None:
            return {'status': 'partial', 'reason': 'start_not_observed', 'run_id': ref['id']}
        if event == 'SubagentStart' and start is not None:
            if mail._normalise_agent(receiver) not in start['meta']['to']:
                raise ValueError('Native child role changed; original handoff preserved')
            mail.record_delivery(root, child_session, start, agent_id=receiver, delivered=False)
            return {'status': 'recorded', 'duplicate': True, 'thread_id': start['meta']['thread_id'],
                    'context': start['body'] + '\n\n记录不授予额外权限；请实际执行任务，无需重复发送 Mail。'}
        if event == 'SubagentStop':
            response = _text(payload.get('last_assistant_message'))
            result_kind = 'result' if response else 'note'
            result_body = ('宿主捕获的子任务返回（未作业务验收）：\n\n' + response if response else
                           '宿主报告子任务已结束，但未提供返回正文。执行结果未知，不能据此认定成功。')
            previous = next((row for row in rows if row['meta'].get('record_kind') == result_kind
                             and row['body'].strip() == result_body.strip()), None)
            if previous:
                return {'status': 'recorded', 'duplicate': True, 'thread_id': previous['meta']['thread_id']}
        machine = mail.machine_id()
        if event == 'SubagentStart':
            _profile(root, parent, f'{host.title()} 协调者', '由宿主发起子任务并接收返回')
            _profile(root, receiver, _text(kind, 100), '执行宿主委派的子任务')
            _session(root, sid, parent, machine, str(payload.get('cwd') or ''))
            _session(root, child_session, receiver, machine)
            context = None
            diagnostic = None
            try:
                if isinstance(payload.get('cwd'), str) and payload['cwd']:
                    context = _task_context(root, payload['cwd'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                diagnostic = type(exc).__name__
            thread = next((row['meta']['thread_id'] for row in rows), '')
            if context and not any(row['meta'].get('record_kind') == 'goal' for row in rows):
                goal_text = frontmatter.loads(context['agreement']['goal']['text'])
                title = _text(goal_text.get('title') or context['task_id'], 120)
                goal = mail.write_message(root, sender=parent, sender_kind='agent', recipients=[receiver, viewer],
                    title=title, body=_text(goal_text.content) +
                    f"\n\n任务修订 {context['revision']}；来源状态 {context['status']}。宿主实际启动子任务，不表示业务验收通过。",
                    record_kind='goal', thread_id=thread, origin_session_id=sid, origin_machine_id=machine, evidence_refs=[ref])
                thread = goal['thread_id']
            body = f'宿主已启动子任务角色：{_text(kind, 100)}。\n\n由原生 SubagentStart 事件自动保存；不表示已读、确认或完成。\n\n宿主子任务 ID：{_text(child, 240)}'
            if context:
                body += f"\n\n关联任务：{context['task_id']}（修订 {context['revision']}，{context['status']}）。"
            if diagnostic:
                body += '\n\n任务关联读取失败；保留宿主事件，不推断任务约定。'
            sent = mail.write_message(root, sender=parent, sender_kind='agent', recipients=[receiver, viewer],
                title=f'交接 · {_text(kind, 100)}', body=body, kind='handoff', record_kind='handoff', delivery_reason='handoff',
                thread_id=thread, origin_session_id=sid, origin_machine_id=machine, evidence_refs=[ref])
            message = mail.parse_message(Path(sent['path']))
            mail.record_delivery(root, child_session, message, agent_id=receiver, machine_id=machine, delivered=False)
            return {'status': 'recorded', 'thread_id': sent['thread_id'], 'message_id': sent['message_id'],
                    'task_context': 'unavailable' if diagnostic else ('linked' if context else 'none'),
                    'context': body + '\n\n返回内容由宿主结束事件保存，无需手写 Mail；记录不授予额外权限，不得代签人工审核。'}
        if mail._normalise_agent(receiver) not in start['meta']['to']:
            raise ValueError('Native child role changed; original handoff preserved')
        parent = str(start['meta']['from'])
        sent = mail.write_message(root, sender=receiver, sender_kind='agent', recipients=[parent, viewer],
            title=f'返回 · {_text(kind, 100)}' if result_kind == 'result' else f'返回待核对 · {_text(kind, 100)}',
            body=result_body, record_kind=result_kind, delivery_reason='thread_reply',
            thread_id=start['meta']['thread_id'], reply_to=start['meta']['message_id'],
            origin_session_id=child_session, origin_machine_id=machine, evidence_refs=[ref])
        return {'status': 'recorded', 'thread_id': sent['thread_id'], 'message_id': sent['message_id'],
                'execution_outcome': 'unverified' if result_kind == 'result' else 'unknown'}


def main(host: str) -> int:
    """Fail open with a visible diagnostic; never alter host permission decisions."""
    import sys
    try:
        raw = sys.stdin.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Host event exceeds size limit')
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('Invalid host event')
        root = store.repo_root()
        result = observe(root, payload, host, parent_agent=os.environ.get('OKS_AGENT_ID', '').lstrip('@'))
        from . import task_workflow
        workflow = task_workflow.observe(root, payload, host, thread_id=result.get('thread_id'))
        context = '\n\n'.join(value for value in (result.get('context'), workflow.get('context')) if value)
        if context:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': payload['hook_event_name'],
                                                     'additionalContext': context}}, ensure_ascii=False))
        if workflow.get('warning'):
            print('OKS workflow: ' + workflow['warning'], file=sys.stderr)
        if result['status'] in {'partial', 'skipped'} and result.get('reason') != 'unhandled_event':
            print(f"OKS collaboration {result['status']}: {result['reason']}", file=sys.stderr)
    except Exception as exc:
        # Do not echo payloads, paths, credentials or the full exception text.
        print(f'OKS collaboration capture failed: {type(exc).__name__}', file=sys.stderr)
    return 0
