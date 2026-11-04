"""Synthetic tests for task source projections and private correction proposals."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from knowledge_studio import feedback, tasks, workspace

# Load the sibling fixture module by path so this works both from the source
# checkout and when installed tests are copied into a standalone tests folder.
_flow_spec = importlib.util.spec_from_file_location('test_task_flow', Path(__file__).with_name('test_task_flow.py'))
_flow = importlib.util.module_from_spec(_flow_spec)
_flow_spec.loader.exec_module(_flow)
acceptance, kb, progress, server, snapshot = (_flow.acceptance, _flow.kb, _flow.progress, _flow.server, _flow.snapshot)

DATA = json.loads((Path(__file__).parent / 'fixtures/task-reuse.json').read_text(encoding='utf-8'))


def correction(root, *, request_id='fix-1', summary='Correct the stated rule'):
    task = tasks.show(root, 'report')
    source = task['agreement']['knowledge'][0]
    return {
        'task_id': 'report', 'expected_revision': task['revision'],
        'expected_agreement_sha256': task['agreement']['sha256'],
        'request_id': request_id, 'scope': {'subject': 'synthetic', 'project': 'trial', 'task': 'report'},
        'reason': 'Synthetic user-reported correction', 'summary': summary,
        'source': {'path': source['path'], 'sha256': source['sha256']},
        'artifact': task['artifacts'][0] if task['artifacts'] else None,
    }


def test_source_projection_keeps_versions_and_use_as_unverified_report(kb):
    root, _ = kb
    first = tasks.show(root, 'report')['agreement']['knowledge'][0]
    tasks.checkpoint(root, 'report', 1, 'Draft', 'Review', ['reports/report.md'])
    task = tasks._load(root, 'report')
    task['uses'] = [{'source_path': first['path'], 'source_sha256': first['sha256'],
                     'verification': 'caller_reported', 'execution_verified': False}]
    tasks._save(tasks._path(root, 'report'), task)
    changed = root / 'wiki/a.md'
    changed.write_text(changed.read_text(encoding='utf-8') + 'replacement\n', encoding='utf-8')
    # Refresh preserves old source in history and captures the new digest.
    updated = tasks.refresh(root, 'report', 2)
    projection = workspace.task_sources(root, 'report', updated['revision'])
    old = next(v for v in projection['sources'] if v['path'] == 'wiki/a.md' and v['sha256'] == first['sha256'])
    current = next(v for v in projection['sources'] if v['path'] == 'wiki/a.md' and v['sha256'] != first['sha256'])
    assert old['relation'] == 'replaced'
    assert old['use_revisions'] == [2]
    assert current['relation'] == 'agreement'
    assert projection['state_mutated'] is False
    assert all('text' not in item for item in projection['sources'])


def test_source_projection_rejects_stale_revision_without_mutation(kb):
    root, _ = kb
    tasks.checkpoint(root, 'report', 1, 'Draft', 'Review', ['reports/report.md'])
    before = snapshot(root)
    with pytest.raises(ValueError, match='revision'):
        workspace.task_sources(root, 'report', 1)
    assert snapshot(root) == before


def test_correction_same_id_is_idempotent_and_summary_conflict_preserves_private_record(kb):
    root, _ = kb
    request = correction(root)
    first = workspace.propose_task_correction(root, request)
    repeated = workspace.propose_task_correction(root, request)
    assert repeated['event_id'] == first['event_id'] and repeated['candidate_id'] == first['candidate_id']
    assert repeated['candidate_status'] == 'pending' and repeated['wiki_promoted'] is False
    before = snapshot(root)
    with pytest.raises(ValueError, match='different content'):
        workspace.propose_task_correction(root, correction(root, summary='Conflicting summary'))
    assert snapshot(root) == before
    private = feedback.inspect(root, request['scope'])
    assert len(private['events']) == len(private['candidates']) == 1
    assert private['candidates'][0]['status'] == 'pending'
    assert not list((root / 'drafts').rglob('*.md'))


def test_propose_failure_is_partial_and_same_request_retry_finishes(kb, monkeypatch):
    root, _ = kb
    real_propose = feedback.propose
    attempts = 0

    def fail_once(root_arg, request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('synthetic transient failure')
        return real_propose(root_arg, request)

    monkeypatch.setattr(feedback, 'propose', fail_once)
    request = correction(root)
    partial = workspace.propose_task_correction(root, request)
    assert partial['status'] == 'partial' and partial['candidate_id'] is None
    assert len(feedback.inspect(root, request['scope'])['events']) == 1
    result = workspace.propose_task_correction(root, request)
    assert result['status'] == 'recorded' and result['candidate_status'] == 'pending'
    assert len(feedback.inspect(root, request['scope'])['events']) == 1
    assert len(feedback.inspect(root, request['scope'])['candidates']) == 1


def test_source_changed_after_record_stays_partial_without_candidate(kb, monkeypatch):
    root, _ = kb
    real_record = feedback.record

    def record_then_change(root_arg, request):
        result = real_record(root_arg, request)
        source = root / request['asset_path']
        source.write_text(source.read_text(encoding='utf-8') + 'changed during correction\n', encoding='utf-8')
        return result

    monkeypatch.setattr(feedback, 'record', record_then_change)
    request = correction(root, request_id='source-race')
    result = workspace.propose_task_correction(root, request)
    assert result['status'] == 'partial' and result['candidate_id'] is None
    private = feedback.inspect(root, request['scope'])
    assert len(private['events']) == 1 and not private['candidates']


@pytest.mark.parametrize('case', DATA['cases'], ids=lambda item: item['name'])
def test_frozen_invalid_correction_inputs_do_not_mutate(kb, case):
    root, _ = kb
    before = snapshot(root)
    with pytest.raises((ValueError, OSError)):
        workspace.propose_task_correction(root, {**correction(root), **case['override']})
    assert snapshot(root) == before


@pytest.mark.parametrize('failure', ['closed', 'stale', 'source', 'artifact', 'scope'])
def test_correction_rejects_closed_stale_source_artifact_and_scope(kb, failure):
    root, _ = kb
    request = correction(root)
    if failure == 'closed':
        tasks.transition(root, 'report', 1, 'complete', 'Synthetic closure')
    elif failure == 'stale':
        (root / 'wiki/a.md').write_text((root / 'wiki/a.md').read_text(encoding='utf-8') + 'changed\n', encoding='utf-8')
    elif failure == 'source':
        request['source'] = {'path': 'wiki/b.md', 'sha256': hashlib.sha256((root / 'wiki/b.md').read_bytes()).hexdigest()}
    elif failure == 'artifact':
        request['artifact'] = {'path': 'reports/report.md', 'sha256': '0' * 64}
    else:
        request['scope']['task'] = 'different-task'
    before = snapshot(root)
    with pytest.raises((ValueError, AttributeError)):
        workspace.propose_task_correction(root, request)
    assert snapshot(root) == before


def test_parallel_same_task_correction_is_single_event_and_candidate(kb):
    root, _ = kb
    request = correction(root, request_id='parallel-fix')
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: workspace.propose_task_correction(root, request), range(12)))
    assert {v['event_id'] for v in results} == {'parallel-fix'}
    assert {v['candidate_id'] for v in results} == {'parallel-fix'}
    private = feedback.inspect(root, request['scope'])
    assert len(private['events']) == len(private['candidates']) == 1


@pytest.mark.parametrize('flags', [{}, {'local_review': True}, {'mode': 'collaboration'}, {'local_edit': True}])
def test_http_sources_and_correction_permission_origin_and_instance(kb, flags):
    root, _ = kb
    with server(root, **flags) as (base, call):
        sources = call('/api/tasks/sources?id=report&revision=1')
        assert sources['knowledge_base'] == str(root)
        assert sources['sources'][0]['relation'] == 'agreement'
        request = correction(root)
        request['expected_knowledge_base'] = str(root)
        if not flags.get('local_edit'):
            with pytest.raises(HTTPError) as error:
                call('/api/tasks/correction', request)
            assert error.value.code == 403
            return
        for value, origin, code in [(request, 'http://evil.invalid', 403),
                                    ({**request, 'expected_knowledge_base': 'other'}, base, 409)]:
            with pytest.raises(HTTPError) as error:
                call('/api/tasks/correction', value, origin)
            assert error.value.code == code
        result = call('/api/tasks/correction', request)
        assert result['candidate_status'] == 'pending'
        assert result['wiki_promoted'] is False


def test_pending_not_in_recall_and_synthetic_approval_exact_scope_then_withdrawal(kb):
    root, _ = kb
    request = correction(root)
    pending = workspace.propose_task_correction(root, request)
    agreement = tasks.show(root, 'report')['agreement']
    assert not feedback.select_context(root, request['scope'], agreement)['candidates']
    private = feedback.inspect(root, request['scope'])
    candidate = private['candidates'][0]
    approved = feedback.review(root, {'scope': request['scope'], 'candidate_id': candidate['candidate_id'],
                                      'expected_revision': candidate['revision'], 'decision': 'approve',
                                      'comment': 'Synthetic test approval only'})
    assert approved['status'] == 'approved'
    assert feedback.select_context(root, request['scope'], agreement)['candidates']
    other_scope = {'subject': 'synthetic', 'project': 'other-trial', 'task': 'report'}
    assert not feedback.select_context(root, other_scope, agreement)['candidates']
    feedback.withdraw_candidate(root, {'scope': request['scope'], 'candidate_id': pending['candidate_id'],
                                       'expected_revision': approved['revision']})
    assert not feedback.select_context(root, request['scope'], agreement)['candidates']
