import json
import hashlib

import pytest

from knowledge_studio.studio_workflow import discussion_workflow, workflow
from knowledge_studio import discussion_comments, mail, mail_runtime, studio


def put(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='')
    return target


def test_declared_skill_steps_and_checked_tasks_do_not_manufacture_execution(tmp_path):
    put(tmp_path, 'goal/a.md', '---\nskills: [skills/a/SKILL.md]\n---\n# Goal\n- [x] Finished checkbox\n')
    put(tmp_path, 'skills/a/SKILL.md', '# Skill\n## Search\n## Write\n[[wiki/a]]\n')
    put(tmp_path, 'wiki/a.md', '# Knowledge\n')
    result = workflow(tmp_path, 'goal/a.md')
    assert result['runs'] == []
    assert result['references'] == [
        {'from': 'goal/a.md', 'to': 'skills/a/SKILL.md', 'kind': 'written_reference'},
        {'from': 'skills/a/SKILL.md', 'to': 'wiki/a.md', 'kind': 'written_reference'},
    ]
    assert any(row['checked'] for row in result['outline'])


def test_execution_identity_must_match_full_goal_not_basename(tmp_path):
    put(tmp_path, 'goal/a.md', '# Goal\n')
    for run_id, goal in [('right', 'goal/a.md'), ('wrong', 'profiles/goals/a.md')]:
        put(tmp_path, f'raw/executions/{run_id}/run.json', json.dumps({'run_id': run_id, 'goal_id': goal, 'status': 'running'}))
        put(tmp_path, f'raw/executions/{run_id}/events.jsonl', json.dumps({
            'run_id': run_id, 'event_id': run_id + ':1', 'event_type': 'ai_action',
            'actor': 'agent', 'payload': {'skill_path': 'skills/a/SKILL.md', 'step_id': 'search', 'unrelated': 'do not expose'},
        }))
    result = workflow(tmp_path, 'goal/a.md')
    assert [run['run_id'] for run in result['runs']] == ['right']
    assert result['runs'][0]['events'][0]['payload'] == {'skill_path': 'skills/a/SKILL.md', 'step_id': 'search'}


def test_workflow_rejects_escape_and_reports_corrupt_traces(tmp_path):
    put(tmp_path, 'goal/a.md', '# Goal\n')
    put(tmp_path, 'raw/executions/bad/run.json', '{broken')
    result = workflow(tmp_path, 'goal/a.md')
    assert not result['runs'] and result['warnings']
    with pytest.raises(ValueError):
        workflow(tmp_path, '../other/goal.md')


def test_workflow_rejects_symlinked_trace_directory(tmp_path):
    put(tmp_path, 'goal/a.md', '# Goal\n')
    (tmp_path / 'raw/executions').mkdir(parents=True)
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (outside / 'run.json').write_text('{"goal_id":"goal/a.md"}')
    try:
        (tmp_path / 'raw/executions/escape').symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f'Symlinks unavailable: {error}')
    result = workflow(tmp_path, 'goal/a.md')
    assert any('escape' in warning for warning in result['warnings'])


def test_skill_execution_requires_explicit_full_skill_path(tmp_path):
    put(tmp_path, 'skills/a/SKILL.md', '# Skill\n## Search\n')
    put(tmp_path, 'raw/executions/run/run.json', json.dumps({'run_id': 'run', 'goal_id': 'goal/a.md'}))
    put(tmp_path, 'raw/executions/run/events.jsonl', '\n'.join(json.dumps({
        'run_id': 'run', 'event_id': str(i), 'event_type': 'ai_action', 'actor': 'agent',
        'payload': {'skill_path': skill_path, 'step_id': 'search'},
    }) for i, skill_path in enumerate(['skills/a/SKILL.md', 'skills/b/SKILL.md', 'a'])))
    result = workflow(tmp_path, 'skills/a/SKILL.md')
    assert len(result['runs']) == 1
    assert result['runs'][0]['skill_only']
    assert [event['event_id'] for event in result['runs'][0]['events']] == ['0']


DISCUSSION = 'profiles/discuss/2026/11/08/workflow.md'
BUNDLE = 'raw/2026/11/08/capture/bundle-one'


def discussion(root, body='## 判断\n原文判断。\n'):
    return put(root, DISCUSSION, '# 讨论\n\n' + body)


def source_bundle(root, *, prefix=BUNDLE, fragment_status='partial'):
    content = 'Actual retained extraction.\n'
    digest = hashlib.sha256(content.encode()).hexdigest()
    primary = {'artifact_id': 'art-one', 'path': 'capture.md', 'sha256': digest}
    put(root, prefix + '/raw.md', '# Captured Raw\n')
    put(root, prefix + '/content.md', content)
    put(root, prefix + '/source/capture.md', content)
    bundle = {'schema_version': 'raw-multimodal/v0.2', 'bundle_id': 'bundle-one', 'capture_id': 'src-one',
        'content_hash': digest, 'processing_status': 'partial', 'recipe_version': 'test/v1',
        'files': {'manifest': 'bundle.json', 'content': 'content.md', 'evidence': 'evidence.jsonl',
                  'quality_report': 'quality-report.json', 'processing_runs': 'processing-runs.jsonl',
                  'source_dir': 'source/', 'assets_dir': 'assets/', 'derived_dir': 'derived/'},
        'sources': [{'entity_id': 'art-one', 'path': 'source/capture.md', 'sha256': digest, 'primary_source': True}],
        'derived': [], 'provenance': {'entities': [], 'activities': [], 'agents': [], 'relations': []}, 'warnings': []}
    manifest = {'schema_version': 'oks-evidence-manifest/v0.1', 'manifest_id': 'manifest-one',
        'source_id': 'src-one', 'status': 'partial', 'fragment_refs': ['fragment-one'],
        'primary_artifact': primary, 'supplementary_artifacts': [],
        'steps': [{'provider': 'text-read', 'capability': 'text.extract', 'status': fragment_status, 'reason': '缺少图片内容'}]}
    fragment = {'schema_version': 'oks-evidence-fragment/v0.1', 'fragment_id': 'fragment-one',
        'source_id': 'src-one', 'producer': {'runtime': 'oks', 'provider': 'text-read', 'tool': 'text-read'},
        'status': fragment_status, 'artifacts': [primary]}
    put(root, prefix + '/bundle.json', json.dumps(bundle))
    put(root, prefix + '/evidence-manifest.json', json.dumps(manifest))
    put(root, prefix + '/source-envelope.json', json.dumps({'source_id': 'src-one', 'title': 'Captured page',
        'source_uri': 'https://example.org/source'}))
    put(root, prefix + '/derived/fragments/fragment-one.json', json.dumps(fragment))
    # A Raw commit summary is not another extractor call.
    put(root, prefix + '/processing-runs.jsonl', json.dumps({'run_id': 'raw-commit', 'capture_id': 'src-one', 'status': 'partial'}))
    return bundle, manifest, fragment


def test_discussion_workflow_empty_means_no_matching_record_not_fixed_stages(tmp_path):
    discussion(tmp_path, '## 判断\n- [x] 完成\n[[goal/linked.md]]\n')
    put(tmp_path, 'goal/linked.md', '# Linked goal\n')
    put(tmp_path, 'raw/executions/unrelated/run.json', json.dumps({'run_id': 'unrelated', 'goal_id': 'goal/linked.md'}))
    source_bundle(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    result = discussion_workflow(tmp_path, DISCUSSION)
    assert result['steps'] == []
    assert result['path'] == DISCUSSION and result['sha256'] == studio.read_file(tmp_path, DISCUSSION)['sha256']
    assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


def test_discussion_workflow_real_comment_receipt_result_and_written_version_are_not_an_extractor(tmp_path, monkeypatch):
    monkeypatch.setenv('OKS_MACHINE_ID', 'machine_process_test')
    discussion(tmp_path)
    mail.register_session(tmp_path, 'actual-session', 'codex', machine_id='machine_process_test')
    doc = discussion_comments.document(tmp_path, DISCUSSION)
    record = discussion_comments.send(tmp_path, {'path': DISCUSSION, 'anchor_id': 'section:3',
        'expected_sha256': doc['sha256'], 'agent': '@codex', 'text': '请修订这一段。', 'allow_edit': True})['comments'][0]
    step = discussion_workflow(tmp_path, DISCUSSION)['steps'][0]
    assert step['kind'] == 'comment' and step['extractor'] is None and step['status'] == 'pending'
    assert step['agent'] == '@codex'
    assert step['id'] == 'comment:' + record['message_id'] and step['outputs'] == []
    mail_runtime.FileMailRuntime(tmp_path, 'codex', 'actual-session', 'machine_process_test').wait(timeout=0)
    assert discussion_workflow(tmp_path, DISCUSSION)['steps'][0]['status'] == 'received'
    changed = studio.save_file(tmp_path, {'path': DISCUSSION, 'text': doc['text'].replace('原文判断。', '修订判断。'),
                                        'expected_sha256': doc['sha256']})
    result = {'schema': 'oks.discussion-comment.result.v1', 'comment_message_id': record['message_id'],
        'source_sha256': doc['sha256'], 'result_sha256': changed['sha256'], 'changed': True,
        'status': 'updated', 'reply': '已修订，并保留其余章节。'}
    mail.write_message(tmp_path, body=json.dumps(result), sender='codex', sender_kind='agent', recipients=['human'],
        thread_id=record['thread_id'], reply_to=record['message_id'], origin_session_id='actual-session',
        origin_machine_id='machine_process_test', record_kind='result')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    step = discussion_workflow(tmp_path, DISCUSSION)['steps'][0]
    assert step['status'] == 'updated' and step['source_sha256'] == doc['sha256']
    assert step['inputs'][0]['text'] == '## 判断\n原文判断。\n'
    assert step['inputs'][0]['verification'] == 'changed'
    assert step['outputs'][0]['text'] == result['reply']
    assert step['outputs'][1]['sha256'] == changed['sha256'] and step['outputs'][1]['verification'] == 'verified'
    assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('status', ['succeeded', 'partial', 'degraded', 'failed', 'skipped'])
def test_discussion_workflow_uses_precise_fragment_identity_and_preserves_recorded_status(tmp_path, status):
    discussion(tmp_path, '## 依据\n[[drafts/candidate.md]]\n')
    put(tmp_path, 'drafts/candidate.md', f'---\nsources: [{BUNDLE}/raw.md]\n---\n# Candidate\n')
    source_bundle(tmp_path, fragment_status=status)
    source_bundle(tmp_path, prefix='raw/elsewhere/bundle-one')
    result = discussion_workflow(tmp_path, DISCUSSION)
    assert len(result['steps']) == 1  # Fragment + Manifest + Raw summary are one retained fragment, not three calls.
    step = result['steps'][0]
    assert step['kind'] == 'extraction' and step['status'] == status
    assert step['extractor'] == {'runtime': 'oks', 'provider': 'text-read', 'tool': 'text-read', 'capability': 'text.extract'}
    assert step['agent'] == ''  # A producer runtime is not a verified Agent identity.
    assert step['anchor_id'] == 'section:3' and step['anchor_title'] == '依据'
    assert step['record_path'] == BUNDLE + '/derived/fragments/fragment-one.json'
    assert step['inputs'][0]['uri'] == 'https://example.org/source'
    assert step['outputs'][0]['verification'] == 'verified'
    assert step['outputs'][0]['text'] == 'Actual retained extraction.\n'


@pytest.mark.parametrize('mismatch', ['manifest_source', 'fragment_source', 'fragment_id', 'artifact_id', 'artifact_hash'])
def test_discussion_workflow_does_not_attach_unmatched_fragment_or_source(tmp_path, mismatch):
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/raw.md]]\n')
    _, manifest, fragment = source_bundle(tmp_path)
    if mismatch == 'manifest_source':
        manifest['source_id'] = 'other-source'
    elif mismatch == 'fragment_source':
        fragment['source_id'] = 'other-source'
    elif mismatch == 'fragment_id':
        fragment['fragment_id'] = 'other-fragment'
    else:
        fragment['artifacts'] = [{**fragment['artifacts'][0],
            'artifact_id' if mismatch == 'artifact_id' else 'sha256': 'other-artifact' if mismatch == 'artifact_id' else '0' * 64}]
    put(tmp_path, BUNDLE + '/evidence-manifest.json', json.dumps(manifest))
    put(tmp_path, BUNDLE + '/derived/fragments/fragment-one.json', json.dumps(fragment))
    result = discussion_workflow(tmp_path, DISCUSSION)
    assert result['steps'] == [] and result['warnings']


def test_discussion_workflow_declared_provider_without_fragment_is_not_an_execution(tmp_path):
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/raw.md]]\n')
    _, manifest, _ = source_bundle(tmp_path)
    manifest['fragment_refs'] = []
    put(tmp_path, BUNDLE + '/evidence-manifest.json', json.dumps(manifest))
    result = discussion_workflow(tmp_path, DISCUSSION)
    assert result['steps'] == [] and result['warnings']


def test_discussion_workflow_nearby_unlisted_file_cannot_select_bundle(tmp_path):
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/unrelated.md]]\n')
    source_bundle(tmp_path)
    put(tmp_path, BUNDLE + '/unrelated.md', '# Not declared in this bundle\n')
    assert discussion_workflow(tmp_path, DISCUSSION)['steps'] == []


def test_discussion_workflow_changed_artifact_keeps_partial_record_without_claiming_hash_match(tmp_path):
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/raw.md]]\n')
    source_bundle(tmp_path)
    put(tmp_path, BUNDLE + '/source/capture.md', 'Changed after the captured fragment.\n')
    result = discussion_workflow(tmp_path, DISCUSSION)
    step = result['steps'][0]
    assert step['status'] == 'partial' and step['outputs'][0]['verification'] == 'changed'
    assert step['outputs'][0]['sha256'] != step['outputs'][0]['expected_sha256']
    assert result['warnings']


@pytest.mark.parametrize('capture_id', ['src-one', 'other-source'])
def test_discussion_workflow_native_processing_run_requires_capture_match_and_actual_job(tmp_path, capture_id):
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/raw.md]]\n')
    bundle, manifest, _ = source_bundle(tmp_path)
    manifest['fragment_refs'] = []
    put(tmp_path, BUNDLE + '/evidence-manifest.json', json.dumps(manifest))
    run = {'schema_version': 'oks-processing-run/v0.2', 'run_id': 'run-actual', 'capture_id': capture_id,
        'status': 'partial', 'job': {'name': 'markitdown', 'namespace': 'oks-connector', 'version': '1', 'capability': 'office.extract'},
        'inputs': [{'dataset_id': 'source', 'kind': 'source', 'uri': 'source/capture.md', 'sha256': bundle['content_hash']}],
        'outputs': [{'dataset_id': 'text', 'kind': 'artifact', 'uri': BUNDLE + '/content.md', 'sha256': bundle['content_hash']}],
        'errors': [{'code': 'IMAGE_SKIPPED', 'message': 'Images not extracted'}]}
    put(tmp_path, BUNDLE + '/processing-runs.jsonl', json.dumps(run))
    result = discussion_workflow(tmp_path, DISCUSSION)
    if capture_id != bundle['capture_id']:
        assert result['steps'] == [] and result['warnings']
    else:
        assert len(result['steps']) == 1
        step = result['steps'][0]
        assert step['record_id'] == 'run-actual' and step['status'] == 'partial'
        assert step['extractor']['tool'] == 'markitdown'
        assert step['agent'] == ''  # A software namespace is not an Agent identity.
        assert step['extractor']['runtime'] == 'oks-connector' and step['extractor']['version'] == '1'
        assert step['inputs'][0]['verification'] == step['outputs'][0]['verification'] == 'verified'
        assert step['detail'] == 'Images not extracted'


def test_discussion_workflow_refuses_other_buckets_and_parent_escape(tmp_path):
    put(tmp_path, 'wiki/a.md', '# Wiki\n')
    for path in ('wiki/a.md', '../outside.md'):
        with pytest.raises(ValueError):
            discussion_workflow(tmp_path, path)


@pytest.mark.parametrize('changes', [
    {'recipients': ['private-peer']}, {'origin_session_id': 'another-session'},
    {'origin_machine_id': 'machine_other'}, {'thread_id': 'another-thread'},
])
def test_discussion_workflow_does_not_turn_private_or_unmatched_agent_results_into_steps(tmp_path, monkeypatch, changes):
    monkeypatch.setenv('OKS_MACHINE_ID', 'machine_process_test')
    discussion(tmp_path)
    mail.register_session(tmp_path, 'actual-session', 'codex', machine_id='machine_process_test')
    doc = discussion_comments.document(tmp_path, DISCUSSION)
    record = discussion_comments.send(tmp_path, {'path': DISCUSSION, 'anchor_id': 'section:3',
        'expected_sha256': doc['sha256'], 'agent': '@codex', 'text': '请答复。'})['comments'][0]
    mail_runtime.FileMailRuntime(tmp_path, 'codex', 'actual-session', 'machine_process_test').wait(timeout=0)
    result = {'schema': 'oks.discussion-comment.result.v1', 'comment_message_id': record['message_id'],
        'source_sha256': doc['sha256'], 'result_sha256': doc['sha256'], 'changed': False,
        'status': 'answered', 'reply': 'PRIVATE-OR-UNMATCHED-REPLY'}
    options = {'sender': 'codex', 'sender_kind': 'agent', 'recipients': ['human'],
        'thread_id': record['thread_id'], 'reply_to': record['message_id'],
        'origin_session_id': 'actual-session', 'origin_machine_id': 'machine_process_test',
        'record_kind': 'result', **changes}
    mail.write_message(tmp_path, body=json.dumps(result), **options)
    projection = discussion_workflow(tmp_path, DISCUSSION)
    assert len(projection['steps']) == 1 and projection['steps'][0]['status'] == 'received'
    assert projection['steps'][0]['outputs'] == []
    assert 'PRIVATE-OR-UNMATCHED-REPLY' not in json.dumps(projection)


def test_discussion_workflow_broken_linked_record_does_not_prevent_real_comment_projection(tmp_path, monkeypatch):
    monkeypatch.setenv('OKS_MACHINE_ID', 'machine_process_test')
    discussion(tmp_path, f'## 依据\n[[{BUNDLE}/raw.md]]\n')
    source_bundle(tmp_path)
    put(tmp_path, BUNDLE + '/evidence-manifest.json', '{broken-json')
    mail.register_session(tmp_path, 'actual-session', 'codex', machine_id='machine_process_test')
    doc = discussion_comments.document(tmp_path, DISCUSSION)
    discussion_comments.send(tmp_path, {'path': DISCUSSION, 'anchor_id': 'section:3',
        'expected_sha256': doc['sha256'], 'agent': '@codex', 'text': '请核对来源。'})
    result = discussion_workflow(tmp_path, DISCUSSION)
    assert [step['kind'] for step in result['steps']] == ['comment'] and result['warnings']
