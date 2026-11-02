"""Calendar reviews must preserve the difference between work and completion."""
from datetime import datetime
import json

import pytest

from knowledge_studio import tasks, work_review


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / 'kb'
    folder = root / 'profiles/goals'
    folder.mkdir(parents=True)
    (folder / 'report.md').write_text('---\ntype: goal\ntitle: Weekly brief\nstatus: active\n---\nWrite a useful brief.\n', encoding='utf-8')
    return root


def at(monkeypatch, local_time):
    instant = datetime.fromisoformat(local_time).astimezone()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(tasks, 'datetime', Clock)


@pytest.mark.parametrize('period,date,start,end', [
    ('day', '2026-10-29', '2026-10-29', '2026-10-29'),
    ('week', '2026-10-29', '2026-10-26', '2026-11-01'),
    ('week', '2027-01-01', '2026-12-28', '2027-01-03'),
    ('month', '2028-02-18', '2028-02-01', '2028-02-29'),
])
def test_calendar_windows_and_empty_kb_do_not_create_storage(tmp_path, period, date, start, end):
    root = tmp_path / 'absent'
    result = work_review.build(root, period=period, date=date)
    assert result['window']['start'] == start and result['window']['end'] == end
    assert result['window']['end_inclusive'] is True
    assert result['knowledge_base'] == str(root.resolve())
    assert not any(result['counts'].values()) and not result['truncated']
    assert not root.exists()


@pytest.mark.parametrize('kwargs', [
    {'period': 'year'}, {'date': '2026-02-30'}, {'date': '2026-1-1'},
    {'date': '2026-10-29T00:00:00Z'}, {'date': 20261029},
])
def test_invalid_calendar_selection_is_explicit(tmp_path, kwargs):
    with pytest.raises(ValueError, match='Review (date|period)'):
        work_review.build(tmp_path, **kwargs)


def test_past_review_keeps_period_progress_separate_from_later_updates(kb, monkeypatch):
    at(monkeypatch, '2026-10-29T09:00:00')
    tasks.start(kb, 'brief', 'profiles/goals/report.md', [])
    at(monkeypatch, '2026-10-29T10:00:00')
    tasks.checkpoint(kb, 'brief', 1, '本期完成提纲', '补来源', [])
    at(monkeypatch, '2026-10-30T09:00:00')
    tasks.checkpoint(kb, 'brief', 2, '次日写完正文', '审稿', [])
    review = work_review.build(kb, period='day', date='2026-10-29')
    assert review['counts']['updated'] == 1
    item = review['changes']['updated'][0]
    assert item['progress'] == '次日写完正文'
    assert item['window_snapshot']['progress'] == '本期完成提纲'
    assert item['window_snapshot']['revision'] == 2
    assert review['current']['unfinished'][0]['next_action'] == '审稿'


def test_update_and_host_return_stay_unfinished_and_preserve_date_sources(kb, monkeypatch):
    at(monkeypatch, '2026-10-25T23:59:59')
    task = tasks.start(kb, 'brief', 'profiles/goals/report.md', [])
    at(monkeypatch, '2026-10-26T00:00:00')
    (kb / 'result.md').write_text('Actual output awaiting review.', encoding='utf-8')
    tasks.capture_outputs(kb, 'brief', task['agreement']['sha256'], 'return-1',
                          [tasks._artifact(kb, 'result.md')], host='claude', run_id='run-1')
    before = {str(p.relative_to(kb)): p.read_bytes() for p in kb.rglob('*') if p.is_file()}
    review = work_review.build(kb, period='week', date='2026-10-29')
    assert review['counts'] == {'created': 0, 'updated': 1, 'ended': 0,
                                'unfinished': 1, 'awaiting_confirmation': 1,
                                'pending_learning': 0, 'unavailable': 0}
    updated = review['changes']['updated'][0]
    assert updated['title'] == 'Weekly brief' and updated['lifecycle'] == 'active'
    assert updated['artifacts'][0]['path'] == 'result.md'
    assert updated['date_sources'][0]['local_date'] == '2026-10-26'
    assert updated['date_sources'][0]['field'] == 'updated_at'
    assert updated['date_sources'][0]['revision'] == 2
    after = {str(p.relative_to(kb)): p.read_bytes() for p in kb.rglob('*') if p.is_file()}
    assert before == after


def test_declared_end_in_window_is_separate_from_current_reopened_state(kb, monkeypatch):
    at(monkeypatch, '2026-10-26T09:00:00')
    tasks.start(kb, 'brief', 'profiles/goals/report.md', [])
    at(monkeypatch, '2026-11-01T23:59:59')
    tasks.transition(kb, 'brief', 1, 'complete', 'Explicitly declared complete.')
    at(monkeypatch, '2026-11-02T00:00:00')
    tasks.transition(kb, 'brief', 2, 'reopen', 'New work remains.')
    review = work_review.build(kb, period='week', date='2026-10-29')
    assert review['counts']['created'] == review['counts']['ended'] == 1
    ended = review['changes']['ended'][0]
    assert ended['lifecycle'] == 'active' and ended['execution_verified'] is False
    assert ended['date_sources'][0]['lifecycle'] == 'completed'
    assert ended['date_sources'][0]['declaration_only'] is True
    assert review['current']['unfinished'][0]['task_id'] == 'brief'


def test_bad_records_are_visible_and_do_not_hide_other_work(kb, monkeypatch):
    at(monkeypatch, '2026-10-29T09:00:00')
    tasks.start(kb, 'brief', 'profiles/goals/report.md', [])
    (kb / '.oks/tasks/broken.json').write_text('{truncated', encoding='utf-8')
    review = work_review.build(kb, date='2026-10-29')
    assert review['counts']['created'] == review['counts']['unavailable'] == 1
    assert review['unavailable'][0]['task_id'] == 'broken'
    path = kb / '.oks/tasks/brief.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['updated_at'] = 'not a date'
    path.write_text(json.dumps(value), encoding='utf-8')
    review = work_review.build(kb, date='2026-10-29')
    assert not review['changes']['created']
    assert review['counts']['unfinished'] == 1
    assert any(item['code'] == 'invalid_task_history_or_date' for item in review['issues'])
    assert review['counts_are_lower_bounds']


def test_task_capacity_is_reported_instead_of_a_complete_count(tmp_path):
    root = tmp_path / 'kb'
    folder = root / '.oks/tasks'
    folder.mkdir(parents=True)
    for i in range(101):
        (folder / f'broken-{i:03}.json').write_text('{}', encoding='utf-8')
    review = work_review.build(root, date='2026-10-29')
    assert review['truncated'] and review['counts_are_lower_bounds']
    assert review['counts']['unavailable'] == 100


def test_public_learning_uses_its_creation_date_and_returns_metadata_only(kb, monkeypatch):
    at(monkeypatch, '2026-10-20T09:00:00')
    task = tasks.start(kb, 'brief', 'profiles/goals/report.md', [])
    relative = 'drafts/task-learning-' + 'a' * 28 + '.md'
    candidate = kb / relative
    candidate.parent.mkdir()
    candidate.write_text('---\ntitle: Preserve citations\nstatus: draft\ndrafted_at: "2026-10-29T12:00:00"\nworkflow_source:\n  task_id: brief\n  artifacts: []\n---\nPrivate-looking body is never returned by review.\n', encoding='utf-8')
    folder = kb / '.oks/workflow-runs'
    folder.mkdir()
    (folder / 'run.json').write_text(json.dumps({'task_id': 'brief', 'run_id': 'run', 'host': 'claude',
        'child_id': 'main', 'draft_paths': [relative], 'artifacts': [],
        'agreement_sha256': task['agreement']['sha256'], 'updated_at': '2026-11-02T09:00:00'}), encoding='utf-8')
    before = candidate.read_bytes()
    review = work_review.build(kb, date='2026-10-29')
    assert review['counts']['created'] == review['counts']['updated'] == 0
    assert review['pending_learning'][0]['path'] == relative
    assert review['pending_learning'][0]['task_id'] == 'brief'
    assert review['pending_learning'][0]['date_source']['field'] == 'drafted_at'
    assert 'Private-looking body' not in json.dumps(review)
    assert candidate.read_bytes() == before
