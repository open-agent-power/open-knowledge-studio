"""Source-to-proposal mechanics. Model answers here are synthetic fixtures."""
import json
from pathlib import Path

import frontmatter
import pytest

from knowledge_studio import daily_capture, daily_learning, daily_sources, store


@pytest.fixture
def captured(tmp_path):
    root = tmp_path / 'kb'; workspace = tmp_path / 'work'
    for folder in ['raw', 'drafts', 'wiki']:
        (root / folder).mkdir(parents=True, exist_ok=True)
    workspace.mkdir()
    source = {'id': 'source-one', 'host': 'claude', 'workspace': str(workspace), 'label': 'Synthetic source', 'kind': 'claude-workspace', 'read_roots': [str(workspace)]}
    daily_sources.connect_source(root, source)
    config = daily_sources.load_config(root); config['learning'] = {'enabled': True}
    store._atomic_write(root / daily_sources.CONFIG, json.dumps(config))
    metadata = {k: source[k] for k in ['id', 'host', 'workspace', 'label']}
    events = [{'id': 'one', 'kind': 'discussion', 'role': 'assistant', 'text': 'Synthetic public discussion about retaining source evidence.',
               'timestamp': '2026-11-02T01:00:00+00:00', 'session_id': 'session-one', 'phase': 'final', 'final': True}]
    records = daily_capture.append_events(root, source['id'], events, source=metadata)
    return root, records[0]


@pytest.fixture
def captured_batch(tmp_path):
    root = tmp_path / 'kb'; workspace = tmp_path / 'work'
    for folder in ['raw', 'drafts', 'wiki']:
        (root / folder).mkdir(parents=True, exist_ok=True)
    workspace.mkdir()
    source = {'id': 'source-one', 'host': 'claude', 'workspace': str(workspace), 'label': 'Synthetic source', 'kind': 'claude-workspace', 'read_roots': [str(workspace)]}
    daily_sources.connect_source(root, source)
    config = daily_sources.load_config(root); config['learning'] = {'enabled': True}
    store._atomic_write(root / daily_sources.CONFIG, json.dumps(config))
    metadata = {k: source[k] for k in ['id', 'host', 'workspace', 'label']}
    events = [
        {'id': 'one', 'kind': 'discussion', 'role': 'assistant', 'text': 'Earlier progress.',
         'timestamp': '2026-11-02T01:00:00+00:00', 'session_id': 'session-one', 'phase': 'commentary'},
        {'id': 'two', 'kind': 'discussion', 'role': 'assistant', 'text': 'Final reusable source statement.',
         'timestamp': '2026-11-02T01:01:00+00:00', 'session_id': 'session-one', 'phase': 'final', 'final': True},
    ]
    records = daily_capture.append_events(root, source['id'], events, source=metadata)
    return root, records


def answer(root, rows):
    return {'keep': True, 'title': 'Keep the source', 'lesson': 'Preserve the original source when proposing reusable knowledge.',
            'conditions': 'When summarizing a source into a reviewable proposal.', 'evidence_ids': [rows[0]['id']]}


def test_normal_discussion_without_goal_or_output_becomes_only_pending(captured):
    root, record = captured
    result = daily_learning.process_pending(root, generator=answer)
    assert result['status'] == 'drafted'
    draft = frontmatter.loads((root / result['draft_path']).read_text(encoding='utf-8'))
    assert draft['human_approved'] is False and draft['daily_sources'][0]['entry_id'] == record['id']
    assert record['content_path'] in draft.content
    assert list((root / 'wiki').rglob('*.md')) == []
    assert not (root / '.oks/tasks').exists()
    assert daily_learning.process_pending(root, generator=lambda *_: pytest.fail('No repeat generation'))['status'] == 'idle'


def test_daily_source_link_is_clickable_and_only_allows_known_route():
    from knowledge_studio.mail_web import md_to_html
    path = '/#collaboration&entry=capture-' + 'a' * 32
    assert f'href="{path.replace("&", "&amp;")}"' in md_to_html(f'[来源]({path})')
    assert '<a ' not in md_to_html('[unsafe](javascript:alert)')
    assert '<a ' not in md_to_html('[unknown](/#collaboration&entry=other)')


def test_promotion_rechecks_actual_daily_source(captured, monkeypatch):
    root, record = captured
    result = daily_learning.process_pending(root, generator=answer)
    monkeypatch.setattr(store, 'repo_root', lambda: root)
    (root / record['content_path']).write_text('Changed after proposal', encoding='utf-8')
    with pytest.raises(ValueError):
        store.promote_draft(Path(result['draft_path']).stem)
    assert (root / result['draft_path']).exists() and not list((root / 'wiki').rglob('*.md'))


def test_interrupted_discussion_can_be_distilled_after_quiet_window(captured, monkeypatch):
    root, record = captured
    path = root / '.oks/daily-capture/entries' / (record['id'] + '.json')
    item = json.loads(path.read_text()); item['phase'] = 'commentary'; item['final'] = False
    path.write_text(json.dumps(item), encoding='utf-8')
    assert daily_learning.process_pending(root, generator=answer)['status'] == 'waiting_for_reply'
    monkeypatch.setattr(daily_learning, 'QUIET_SECONDS', 0)
    assert daily_learning.process_pending(root, generator=answer)['status'] == 'drafted'


def test_failed_extraction_remains_visible_and_can_retry(captured):
    root, record = captured
    def failure(*_):
        raise ValueError('claude_cli_failed_1')
    assert daily_learning.process_pending(root, generator=failure)['status'] == 'failed'
    assert daily_capture.entry(root, record['id'])['learning_error'] == 'claude_cli_failed_1'
    daily_learning.retry(root, record['id'])
    assert daily_learning.process_pending(root, generator=answer)['status'] == 'drafted'


def test_unknown_evidence_never_writes_a_draft(captured):
    root, _ = captured
    def invalid(root, rows):
        value = answer(root, rows); value['evidence_ids'] = ['invented-source']; return value
    assert daily_learning.process_pending(root, generator=invalid)['status'] == 'failed'
    assert not list((root / 'drafts').glob('*.md'))


def test_no_reusable_knowledge_records_skipped(captured):
    root, record = captured
    assert daily_learning.process_pending(root, generator=lambda *_: {'keep': False})['status'] == 'skipped'
    assert daily_capture.entry(root, record['id'])['learning_status'] == 'skipped'


def test_source_integrity_required_after_proposal(captured):
    root, record = captured
    result = daily_learning.process_pending(root, generator=answer)
    meta = frontmatter.loads((root / result['draft_path']).read_text(encoding='utf-8'))
    (root / record['content_path']).write_text('Changed', encoding='utf-8')
    with pytest.raises(ValueError):
        daily_learning.validate_sources(root, meta)


def test_approved_version_does_not_reopen_after_retry_of_state_write(captured, monkeypatch):
    root, record = captured
    original = daily_capture.update_entry
    def crash(root, entry_id, updates):
        if updates.get('learning_status') == 'drafted':
            raise OSError('synthetic crash after Draft persistence')
        return original(root, entry_id, updates)
    monkeypatch.setattr(daily_capture, 'update_entry', crash)
    assert daily_learning.process_pending(root, generator=answer)['status'] == 'partial'
    assert len(list((root / 'drafts').glob('*.md'))) == 1
    monkeypatch.setattr(daily_capture, 'update_entry', original)
    result = daily_learning.process_pending(root, generator=lambda *_: pytest.fail('Must reuse saved model result'))
    assert result['status'] == 'idle'
    assert len(list((root / 'drafts').glob('*.md'))) == 1


def test_done_batch_projection_recovers_all_entries_without_regeneration(captured_batch, monkeypatch):
    root, records = captured_batch
    first, second = records
    original = daily_capture.update_entry
    interrupted = {'done': False}

    def fail_once(root, entry_id, updates):
        if updates.get('learning_status') == 'drafted' and not interrupted['done']:
            interrupted['done'] = True
            raise OSError('synthetic second projection failure')
        return original(root, entry_id, updates)

    monkeypatch.setattr(daily_capture, 'update_entry', fail_once)
    calls = {'count': 0}
    def generator(root, rows):
        calls['count'] += 1
        return {'keep': True, 'title': 'Batch proposal', 'lesson': 'Keep evidence grouped.',
                'conditions': 'When processing a session batch.', 'evidence_ids': [first['id']]}
    assert daily_learning.process_pending(root, generator=generator)['status'] == 'partial'
    assert calls['count'] == 1
    monkeypatch.setattr(daily_capture, 'update_entry', original)
    assert daily_learning.process_pending(root, generator=lambda *_: pytest.fail('Done batch must not regenerate'))['status'] == 'idle'
    assert calls['count'] == 1
    assert daily_capture.entry(root, first['id'])['learning_status'] == 'drafted'
    assert daily_capture.entry(root, second['id'])['learning_status'] == 'drafted'
    assert len(list((root / 'drafts').glob('*.md'))) == 1


def test_failed_batch_projection_recovers_without_regeneration(captured_batch, monkeypatch):
    root, records = captured_batch
    first, second = records
    original = daily_capture.update_entry
    interrupted = {'done': False}

    def fail_once(root, entry_id, updates):
        if updates.get('learning_status') == 'failed' and not interrupted['done']:
            interrupted['done'] = True
            raise OSError('synthetic failed projection interruption')
        return original(root, entry_id, updates)

    monkeypatch.setattr(daily_capture, 'update_entry', fail_once)
    calls = {'count': 0}
    def generator(*_):
        calls['count'] += 1
        raise ValueError('claude_cli_failed_1')
    with pytest.raises(OSError, match='projection interruption'):
        daily_learning.process_pending(root, generator=generator)
    assert calls['count'] == 1
    monkeypatch.setattr(daily_capture, 'update_entry', original)
    assert daily_learning.process_pending(root, generator=lambda *_: pytest.fail('Failed batch must not regenerate'))['status'] == 'idle'
    assert calls['count'] == 1
    for entry_id in (first['id'], second['id']):
        record = daily_capture.entry(root, entry_id)
        assert record['learning_status'] == 'failed'
        assert record['learning_error'] == 'claude_cli_failed_1'


def test_learning_loop_error_is_visible_and_capture_state_does_not_overwrite(captured, monkeypatch):
    root, _ = captured
    monkeypatch.setattr(daily_learning, 'process_pending', lambda *_: (_ for _ in ()).throw(RuntimeError('journal read failed')))

    class OneIteration:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, _seconds):
            self.stopped = True

    service = daily_learning.CaptureService(root)
    service.stop_event = OneIteration()
    daily_learning.CaptureService.learning_loop(service)
    state_path = root / '.oks/daily-capture/service.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['learning_status'] == 'error'
    assert state['learning_error'] == 'RuntimeError'
    service._state(capture='checked', error=None)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['learning_error'] == 'RuntimeError'
    assert state['error'] is None


@pytest.mark.parametrize(('hook_state', 'expected'), [
    ({'status': 'partial', 'error': 'malformed_transcript_line', 'updated_at': '2026-11-02T01:00:00Z'}, 'partial'),
    ({'status': 'ok', 'updated_at': '2026-11-02T01:01:00Z'}, 'ok'),
])
def test_overview_exposes_current_hook_result_not_stale_error(captured, hook_state, expected):
    root, _ = captured
    path = root / '.oks/daily-capture/hook-error.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hook_state), encoding='utf-8')
    assert daily_learning.overview(root)['hook'] == hook_state
    assert daily_learning.overview(root)['hook']['status'] == expected
