"""Automatic capture must preserve native facts without inventing acceptance."""
from concurrent.futures import ThreadPoolExecutor
import io
import json

import pytest

from knowledge_studio import host_collaboration as capture, mail, tasks


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path/'kb'
    root.mkdir()
    monkeypatch.setenv('OKS_ROOT', str(root))
    monkeypatch.setenv('OKS_TASK_HOME', str(tmp_path/'bindings'))
    monkeypatch.setenv('OKS_MACHINE_ID', 'capture-test-machine')
    monkeypatch.delenv('OKS_AGENT_ID', raising=False)
    return root


def event(kb, name='SubagentStart', child='child1', **kw):
    return dict(session_id='native-parent', agent_id=child, agent_type='report-author',
                hook_event_name=name, cwd=str(kb)) | kw


def rows(kb):
    return list(mail.iter_messages(kb, 'human'))


def test_native_lifecycle_creates_roles_and_same_thread_without_mail_commands(kb):
    first = capture.observe(kb, event(kb), 'claude')
    result = capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='报告与引用已写入 reports/brief.md，仍待审阅。'), 'claude')
    messages = rows(kb)
    assert len(messages) == 2
    start = next(r for r in messages if r['meta']['record_kind'] == 'handoff')
    stop = next(r for r in messages if r['meta']['record_kind'] == 'result')
    assert first['thread_id'] == result['thread_id']
    assert start['body'] in first['context']
    assert stop['meta']['reply_to'] == start['meta']['message_id']
    assert stop['meta']['sender_kind'] == 'agent'
    assert result['execution_outcome'] == 'unverified'
    assert len(list((kb/'profiles/agents').glob('*.md'))) == 2
    sessions = [json.loads(p.read_text(encoding='utf-8')) for p in (kb/'mail/sessions').glob('*.json')]
    assert len(sessions) == 2
    child = next(v for v in sessions if v['session_id'] != 'native-parent')
    receipt = json.loads(mail.receipt_path(kb, child['session_id'], start['meta']['message_id']).read_text(encoding='utf-8'))
    assert receipt['status'] == 'injected'
    assert not receipt.get('delivered_at') and not receipt.get('acknowledged_at')
    assert not (kb/'wiki').exists() and not (kb/'.oks/tasks').exists()


def test_repeated_and_parallel_events_do_not_duplicate_or_mix_children(kb):
    payloads = [event(kb, child=f'child{n}') for n in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        starts = list(pool.map(lambda p: capture.observe(kb, p, 'codex'), payloads))
    assert len({x['thread_id'] for x in starts}) == 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda p: capture.observe(kb, p, 'codex'), [payloads[0]]*4))
    assert len(rows(kb)) == 4
    for n in range(4):
        stop = event(kb, 'SubagentStop', child=f'child{n}', last_assistant_message=f'child result {n}')
        captured = capture.observe(kb, stop, 'codex')
        assert captured['thread_id'] == starts[n]['thread_id']
        assert capture.observe(kb, stop, 'codex')['duplicate']
    assert len(rows(kb)) == 8
    # A shared role is stable; each native child still owns a separate Session.
    assert len(list((kb/'profiles/agents').glob('*.md'))) == 2
    assert len(list((kb/'mail/sessions').glob('*.json'))) == 5


def test_empty_response_and_orphan_stop_preserve_unknown(kb):
    orphan = capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='orphan'), 'claude')
    assert orphan['status'] == 'partial' and not rows(kb)
    capture.observe(kb, event(kb), 'claude')
    result = capture.observe(kb, event(kb, 'SubagentStop'), 'claude')
    assert result['execution_outcome'] == 'unknown'
    assert [r['meta']['record_kind'] for r in rows(kb)].count('result') == 0
    assert any('执行结果未知' in r['body'] for r in rows(kb))


def test_selected_goal_is_linked_without_private_feedback_or_task_mutation(kb):
    goal = kb/'profiles/goals/report.md'
    goal.parent.mkdir(parents=True)
    goal.write_text('---\ntype: goal\ntitle: Write report\nstatus: active\n---\nKeep source citations.\n', encoding='utf-8')
    tasks.start(kb, 'report', 'profiles/goals/report.md', [])
    tasks.select(kb, kb, 'report', 'private-alice', 'private-project')
    before = (kb/'.oks/tasks/report.json').read_bytes()
    first = capture.observe(kb, event(kb), 'claude')
    assert first['task_context'] == 'linked'
    assert len(rows(kb)) == 2
    assert len({r['meta']['thread_id'] for r in rows(kb)}) == 1
    capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='Returned report.'), 'claude')
    assert (kb/'.oks/tasks/report.json').read_bytes() == before
    text = '\n'.join(r['body'] for r in rows(kb))
    assert 'Keep source citations.' in text
    assert 'type: goal' not in text
    assert any(r['title'] == 'Write report' for r in rows(kb))
    assert 'private-alice' not in text and 'private-project' not in text


def test_native_identity_required_and_role_drift_refused(kb):
    assert capture.observe(kb, event(kb, agent_type=''), 'claude')['status'] == 'skipped'
    assert not rows(kb)
    with pytest.raises(ValueError):
        capture.observe(kb, event(kb), 'claude', parent_agent='human')
    capture.observe(kb, event(kb), 'claude')
    with pytest.raises(ValueError, match='role changed'):
        capture.observe(kb, event(kb, 'SubagentStop', agent_type='different'), 'claude')
    assert len(rows(kb)) == 1
    with pytest.raises(ValueError, match='role changed'):
        capture.observe(kb, event(kb, agent_type='different'), 'claude')


def test_resumed_child_keeps_thread_and_preserves_changed_or_late_response(kb):
    start = capture.observe(kb, event(kb), 'claude')
    capture.observe(kb, event(kb, 'SubagentStop'), 'claude')
    assert capture.observe(kb, event(kb), 'claude')['duplicate']
    first = capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='first response'), 'claude')
    later = capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='changed response'), 'claude')
    assert first['thread_id'] == later['thread_id'] == start['thread_id']
    assert len(rows(kb)) == 4


def test_existing_profile_preserved_and_credentials_redacted(kb):
    path = kb/'profiles/agents/claude.md'
    path.parent.mkdir(parents=True)
    path.write_text('Maintained role profile', encoding='utf-8')
    capture.observe(kb, event(kb), 'claude')
    capture.observe(kb, event(kb, 'SubagentStop', last_assistant_message='Authorization: Bearer secret_token_123456789abcdef'), 'claude')
    assert path.read_text(encoding='utf-8') == 'Maintained role profile'
    assert all('secret_token_123456789abcdef' not in r['body'] for r in rows(kb))


def test_replay_recovers_after_message_write_before_receipt(kb, monkeypatch):
    original = mail.record_delivery
    monkeypatch.setattr(mail, 'record_delivery', lambda *a, **k: (_ for _ in ()).throw(OSError('receipt failure')))
    with pytest.raises(OSError):
        capture.observe(kb, event(kb), 'claude')
    assert len(rows(kb)) == 1
    monkeypatch.setattr(mail, 'record_delivery', original)
    assert capture.observe(kb, event(kb), 'claude')['duplicate']
    assert len(rows(kb)) == 1
    assert len(list((kb/'mail/receipts').glob('*/*.json'))) == 1


def test_capture_failure_is_visible_without_blocking_host(kb, monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin', io.StringIO('{broken'))
    assert capture.main('claude') == 0
    stderr = capsys.readouterr().err
    assert 'capture failed: JSONDecodeError' in stderr and 'broken' not in stderr


@pytest.mark.parametrize('relative', ['mail', 'mail/messages', 'mail/sessions', 'mail/inbox', 'mail/receipts/nested', 'mail/receipt-events/nested'])
def test_shared_directory_symlink_is_refused(kb, tmp_path, relative):
    outside = tmp_path/'outside'
    outside.mkdir()
    link = kb/relative
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='symlinks'):
        capture.observe(kb, event(kb), 'claude')
    assert not list(outside.iterdir())
