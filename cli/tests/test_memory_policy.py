"""Synthetic frozen-clock controls; approval below is a test fixture only."""
from datetime import UTC, datetime
import json
from pathlib import Path
import pytest
from knowledge_studio import feedback, handoff, memory_policy, store
from knowledge_studio.recall import recall

DATA = json.loads((Path(__file__).parent / 'fixtures/memory-lifecycle.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', DATA['cases'], ids=lambda c: c['id'])
def test_fixed_clock_matrix(case):
    assert memory_policy.evaluate(case['policy'], now=memory_policy.instant(DATA['now'])) == {
        'status': case['status'], 'eligible': case['eligible']}


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / 'kb'
    for path in ('wiki/computing/strategies', 'profiles/goals', 'settings', 'mail'):
        (root / path).mkdir(parents=True)
    monkeypatch.setenv('OKS_ROOT', str(root)); monkeypatch.setenv('OKS_FEEDBACK_HOME', str(tmp_path / 'private'))
    (root / 'profiles/goals/work.md').write_text('---\ntype: goal\n---\nCite report sources.\n', encoding='utf-8')
    source = 'wiki/computing/strategies/report.md'
    (root / source).write_text("---\ntitle: Report sources\ntype: strategy\narea: computing\nstatus: active\nhuman_reviewed_at: synthetic-fixture\noptions: []\n---\nReport sources.\n", encoding='utf-8')
    return root, source


@pytest.mark.parametrize('backend', ['fts5', 'native'])
def test_wiki_shadow_and_enforce_do_not_mutate_pin_or_access(kb, backend):
    root, source = kb
    path = root / source
    text = path.read_text(encoding='utf-8').replace('options: []', "options: []\npinned: true\naccess_count: 100\napplicability:\n  valid_until: '2020-01-01T00:00:00Z'")
    path.write_text(text, encoding='utf-8'); before = path.read_bytes()
    args = dict(query='Report sources', knowledge_only=True, use_task=False, search_backend=backend)
    shadow = recall(**args)
    assert shadow['knowledge'] and shadow['diagnostics']['memory_validity']['would_exclude'] == 1
    (root / 'settings/recall.yaml').write_text('memory_validity: enforce\n', encoding='utf-8')
    enforced = recall(**args)
    assert not enforced['knowledge'] and path.read_bytes() == before
    assert enforced['diagnostics']['memory_validity']['state_mutated'] is False


def candidate(kb, identifier, policy=None):
    root, source = kb
    scope = {'subject': 'fixture', 'project': 'report', 'task': 'work'}
    agreement = handoff.prepare(root, 'profiles/goals/work.md', [source], 'work')
    feedback.record(root, dict(scope=scope, agreement=agreement, event_id='e-' + identifier,
        action='adopted', reason='Synthetic test preference', asset_path=source))
    request = dict(scope=scope, candidate_id=identifier, event_ids=['e-' + identifier], title=identifier, summary='Synthetic requirement')
    if policy is not None: request['applicability'] = policy
    return scope, agreement, feedback.propose(root, request)


def approve(kb, identifier, **extra):
    scope, agreement, item = candidate(kb, identifier)
    return scope, agreement, feedback.review(kb[0], dict(scope=scope, candidate_id=identifier, decision='approve',
        expected_revision=item['revision'], comment='Synthetic reviewer fixture', **extra))


def test_private_expiry_future_legacy_and_scope_are_independent(kb):
    root, _ = kb
    scope, agreement, _ = approve(kb, 'legacy')
    approve(kb, 'expired', applicability={'valid_until': '2020-01-01T00:00:00Z'})
    approve(kb, 'future', applicability={'valid_from': '2099-01-01T00:00:00Z'})
    selected = feedback.select_context(root, scope, agreement)
    assert [c['candidate_id'] for c in selected['candidates']] == ['legacy']
    assert selected['excluded_counts'] == {'expired': 1, 'not_yet_valid': 1}
    assert feedback.select_context(root, {**scope, 'subject': 'other'}, agreement)['candidates'] == []
    assert feedback.select_context(root, None, agreement)['status'] == 'not_requested'


def test_replacement_is_approved_explicitly_and_never_resurrects_old_candidate(kb):
    root, _ = kb
    scope, agreement, old = approve(kb, 'old')
    _, _, pending = candidate(kb, 'new')
    assert [c['candidate_id'] for c in feedback.context(root, scope, agreement)] == ['old']
    approved = feedback.review(root, dict(scope=scope, candidate_id='new', expected_revision=pending['revision'],
        decision='approve', comment='Synthetic replacement approval', replaces_candidates=['old']))
    assert [c['candidate_id'] for c in feedback.context(root, scope, agreement)] == ['new']
    feedback.withdraw_candidate(root, dict(scope=scope, candidate_id='new', expected_revision=approved['revision']))
    assert feedback.context(root, scope, agreement) == []
    with pytest.raises(ValueError):
        feedback.export(root, dict(scope=scope, candidate_id='old', expected_revision=old['revision']), confirm_share=True)


def test_future_replacement_and_timeless_export_preserve_existing_review(kb):
    root, _ = kb
    scope, agreement, _ = approve(kb, 'old')
    _, _, pending = candidate(kb, 'new')
    with pytest.raises(ValueError, match='already be applicable'):
        feedback.review(root, dict(scope=scope, candidate_id='new', expected_revision=pending['revision'], decision='approve',
            comment='Synthetic fixture', applicability={'valid_from':'2099-01-01T00:00:00Z'}, replaces_candidates=['old']))
    assert [c['candidate_id'] for c in feedback.context(root, scope, agreement)] == ['old']
    _, _, timed = approve(kb, 'timed', applicability={'valid_until': '2099-01-01T00:00:00Z'})
    with pytest.raises(ValueError, match='stay private'):
        feedback.export(root, dict(scope=scope, candidate_id='timed', expected_revision=timed['revision']), confirm_share=True)
    assert not list((root / 'drafts').glob('*.md'))


def test_measurements_are_numeric_and_private_details_do_not_enter_debug(kb):
    root, _ = kb
    scope, agreement, _ = approve(kb, 'private', applicability={'valid_until': '2099-01-01T00:00:00Z'})
    response = recall('Report sources', knowledge_only=True, use_task=False, agreement=agreement, task_scope='work',
        feedback_subject=scope['subject'], feedback_project=scope['project'], debug_record=True)
    measured = response['diagnostics']['measurements']
    assert measured['query_utf8_bytes'] == len('Report sources'.encode())
    assert measured['context_utf8_bytes'] > 0 and measured['total_ms'] >= 0
    assert all(value >= 0 for value in measured['phase_ms'].values())
    assert measured['host_execution_ms'] is None and measured['model_tokens'] is None
    text = (root / '.oks/retrieval-debug.json').read_text(encoding='utf-8')
    assert 'Synthetic requirement' not in text and '2099-01-01' not in text


def test_skill_routing_obeys_the_same_opt_in_time_policy(kb, tmp_path):
    from knowledge_studio import skills
    import frontmatter
    root, _ = kb
    source = tmp_path / 'report-skill'; source.mkdir()
    (source / 'SKILL.md').write_text('---\nname: report\ndescription: Report sources\n---\nWrite a report with sources.\n', encoding='utf-8')
    imported = skills.import_skill(source)
    page = store.get_wiki_page(store.promote_draft(imported['entry']['slug']))
    path = Path(page['file_path']); data = frontmatter.load(path)
    data['applicability'] = {'valid_until':'2020-01-01T00:00:00Z'}
    path.write_text(frontmatter.dumps(data), encoding='utf-8')
    assert skills.search('Report sources')
    (root / 'settings/recall.yaml').write_text('memory_validity: enforce\n', encoding='utf-8')
    assert not skills.search('Report sources')


def test_invalid_mode_and_unrepresentable_utc_times_fail_clearly(kb):
    root, _ = kb
    (root / 'settings/recall.yaml').write_text('memory_validity: unknown-mode\n', encoding='utf-8')
    with pytest.raises(ValueError, match='shadow or enforce'):
        recall('Report sources', knowledge_only=True, use_task=False)
    with pytest.raises(ValueError, match='UTC range'):
        memory_policy.instant('0001-01-01T00:00:00+08:00')


def test_expired_pinned_source_cannot_survive_through_task_or_private_context(kb):
    from knowledge_studio import tasks
    root, source = kb
    path = root / source
    path.write_text(path.read_text(encoding='utf-8').replace('options: []', "options: []\napplicability:\n  valid_until: '2020-01-01T00:00:00Z'"),encoding='utf-8')
    scope, agreement, _ = approve(kb,'derived')
    tasks.start(root,'work','profiles/goals/work.md',[source])
    assert tasks.show(root,'work')['status']=='current'
    (root/'settings/recall.yaml').write_text('memory_validity: enforce\n',encoding='utf-8')
    checked=handoff.check(root,agreement,'work')
    assert any(i['code']=='source_expired' for i in checked['issues'])
    with pytest.raises(ValueError,match='needs review'):
        feedback.context(root,scope,agreement)
    with pytest.raises(ValueError,match='needs review'):
        recall('Report sources',agreement=agreement,task_scope='work',use_task=False)
    assert tasks.show(root,'work')['status']=='needs_review'
    updated=tasks.update_sources(root,'work',1,[])
    assert updated['status']=='current'
