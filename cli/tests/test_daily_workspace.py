"""Synthetic data exercises the actual HTTP review boundary and global-root isolation."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from knowledge_studio import feedback, store, tasks, workspace
from knowledge_studio.cli import app
from knowledge_studio.mail_web import create_server


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / '中文 知识库'
    for folder in ('mail', 'wiki/computing/strategies', 'profiles/goals', 'drafts', 'reports', 'settings'):
        (root / folder).mkdir(parents=True)
    goal = 'profiles/goals/report.md'
    source = 'wiki/computing/strategies/policy.md'
    (root / goal).write_text('---\ntype: goal\ntitle: Report\nstatus: active\n---\nWrite a sourced report.\n', encoding='utf-8')
    (root / source).write_text("---\ntype: strategy\narea: computing\nstatus: active\ntitle: Citations policy\nhuman_reviewed_at: '2026-10-27'\noptions: []\n---\nUse citations in reports.\n", encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT', str(root))
    monkeypatch.setenv('OKS_FEEDBACK_HOME', str(tmp_path / 'private'))
    monkeypatch.setenv('OKS_TASK_HOME', str(tmp_path / 'bindings'))
    task = tasks.start(root, 'report', goal, [source])
    selection = dict(subject='synthetic', project='trial', task='report')
    feedback.record(root, dict(scope=selection, event_id='e1', action='adopted', reason='Synthetic citation preference', agreement=task['agreement'], asset_path=source))
    candidate = feedback.propose(root, dict(scope=selection, candidate_id='c1', event_ids=['e1'], title='Citations', summary='Always cite report sources.'))
    return root, selection, task, candidate


@contextmanager
def http(root, **kwargs):
    server = create_server(root, 0, **kwargs)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(route, payload=None, headers=None):
        req = Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type': 'application/json', 'Origin': base, **(headers or {})})
        with urlopen(req, timeout=35) as response:
            return json.load(response)
    try:
        yield request
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def review_request(selection, candidate, **extra):
    return dict(scope=selection, candidate_id='c1', expected_revision=candidate['revision'], decision='approve', comment='Synthetic test reviewer', **extra)


def test_reader_and_legacy_modes_do_not_implicitly_allow_review(case):
    root, selection, _, candidate = case
    for mode in ('reader', 'collaboration'):
        with http(root, mode=mode) as request:
            assert not request('/api/mail/capabilities')['local_review']
            for route in ('/api/feedback/review', '/api/feedback/withdraw-candidate', '/api/feedback/export', '/api/learning/promote'):
                with pytest.raises(HTTPError) as error:
                    request(route, review_request(selection, candidate))
                assert error.value.code == 403
    assert feedback.inspect(root, selection)['candidates'][0]['status'] == 'pending'


def test_review_exact_revision_duplicate_and_unsupported_writes(case):
    root, selection, _, candidate = case
    with http(root, local_review=True) as request:
        caps = request('/api/mail/capabilities')
        assert caps['read_only'] and caps['local_review'] and caps['mode'] == 'reader'
        for route in ('/api/mail/send', '/api/mail/team/sync'):
            with pytest.raises(HTTPError) as error:
                request(route, {'push': True, 'to': 'other', 'title': 'x', 'body': 'x'})
            assert error.value.code == 403
        payload = review_request(selection, candidate)
        for headers in ({'Origin': 'http://evil.invalid'}, {'Origin': ''}, {'Content-Type': 'text/plain'}):
            with pytest.raises(HTTPError) as error:
                request('/api/feedback/review', payload, headers)
            assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            request('/api/feedback/review', {**payload, 'expected_revision': '0' * 64})
        assert error.value.code == 409
        assert request('/api/feedback/review', payload)['status'] == 'approved'
        with pytest.raises(HTTPError) as error:
            request('/api/feedback/review', payload)
        assert error.value.code == 409
        assert len(request('/api/feedback/inspect', {'scope': selection})['candidates']) == 1


def test_oversized_review_and_scope_privacy(case):
    root, selection, _, candidate = case
    with http(root, local_review=True) as request:
        with pytest.raises(HTTPError):
            request('/api/feedback/review', {**review_request(selection, candidate), 'comment': 'a' * 66000})
        assert request('/api/feedback/inspect', {})['candidates'] == []
        assert request('/api/feedback/inspect', {'scope': {**selection, 'subject': 'another'}})['candidates'] == []
    assert feedback.inspect(root, selection)['candidates'][0]['status'] == 'pending'


def test_export_inspect_promote_new_task_and_withdrawal(case, monkeypatch, tmp_path):
    root, selection, task, candidate = case
    # Server must use its explicit root even when process/global config selects another KB.
    monkeypatch.setenv('OKS_ROOT', str(tmp_path / 'wrong-root'))
    with http(root, local_review=True) as request:
        approved = request('/api/feedback/review', review_request(selection, candidate))
        export = {**review_request(selection, approved), 'confirm_share': True}
        with pytest.raises(HTTPError):
            request('/api/feedback/export', {**export, 'confirm_share': False})
        shared = request('/api/feedback/export', export)
        document = request('/api/learning/draft?' + urlencode({'path': shared['path']}))
        draft_path = root / shared['path']
        assert selection['subject'] not in document['text'] and 'Synthetic citation preference' not in document['text']
        with pytest.raises(HTTPError):
            request('/api/learning/promote', {'path': shared['path'], 'expected_sha256': '0' * 64, 'confirm_review': True})
        assert draft_path.is_file()
        promoted = request('/api/learning/promote', {'path': shared['path'], 'expected_sha256': document['sha256'], 'confirm_review': True})
        assert (root / promoted['path']).is_file() and not draft_path.exists()
        second = tasks.start(root, 'new-task', 'profiles/goals/report.md', [promoted['path']])
        assert second['agreement']['knowledge'][0]['path'] == promoted['path']
        assert feedback.inspect(root, {**selection, 'task': 'new-task'})['candidates'] == []
        result = request('/api/feedback/withdraw-candidate', {**export, 'expected_revision': approved['revision']})
        assert result['status'] == 'withdrawn' and not result['formal_wiki_changed']
        assert (root / promoted['path']).is_file()
    assert feedback.context(root, selection, task['agreement']) == []


def test_withdrawal_blocks_exported_draft_promotion(case):
    root, selection, _, candidate = case
    approved = feedback.review(root, review_request(selection, candidate))
    shared = feedback.export(root, review_request(selection, approved), confirm_share=True)
    inspected = workspace.draft(root, shared['path'])
    feedback.withdraw_candidate(root, review_request(selection, approved))
    with pytest.raises(ValueError, match='withdrawn'):
        workspace.invoke(root, 'promote', {'path': shared['path'], 'expected_sha256': inspected['sha256'], 'confirm_review': True})
    assert (root / shared['path']).exists()


def test_review_saves_the_inspected_snapshot_and_preserves_concurrent_editor_change(case, monkeypatch):
    root, *_ = case
    path = root / 'drafts/concurrent.md'
    original = '---\ntitle: Reviewed snapshot\ndraft_type: strategy\ndraft_area: computing\n---\nReviewed contents.\n'
    path.write_text(original, encoding='utf-8', newline='\n')
    inspected = workspace.draft(root, 'drafts/concurrent.md')
    write_page = store.write_wiki_page
    def concurrent_editor(**kwargs):
        path.write_text('---\ntitle: Unreviewed\n---\nUnreviewed edit.\n', encoding='utf-8')
        return write_page(**kwargs)
    monkeypatch.setattr(store, 'write_wiki_page', concurrent_editor)
    slug = store.promote_draft('concurrent', expected_sha256=inspected['sha256'])
    page = store.get_wiki_page(slug)
    assert page['body'] == 'Reviewed contents.'
    assert path.exists() and 'Unreviewed edit.' in path.read_text()


def test_registered_artifact_history_never_mislabels_current_bytes(case):
    root, _, _, _ = case
    target = root / 'reports/output.md'
    target.write_text('# Original\n', encoding='utf-8')
    current = tasks.checkpoint(root, 'report', 1, 'written', 'review', ['reports/output.md'])
    result = workspace.artifact(root, 'report', 'reports/output.md', current['revision'])
    assert result['status'] == 'unchanged' and result['historical_bytes_available']
    target.write_text('# Changed\n', encoding='utf-8')
    tasks.checkpoint(root, 'report', 2, 'revised', 'review', ['reports/output.md'])
    result = workspace.artifact(root, 'report', 'reports/output.md', 2)
    assert result['status'] == 'changed' and not result['historical_bytes_available']
    assert result['text'].replace('\r\n', '\n') == '# Changed\n' and result['sha256'] != result['expected_sha256']
    with http(root) as request:
        assert request('/api/tasks/artifact?' + urlencode(dict(id='report', path='reports/output.md', revision=2)))['status'] == 'changed'


@pytest.mark.parametrize('name,content', [('secret.txt', 'unregistered'), ('reports/binary.txt', '\x00'), ('reports/large.txt', 'x' * (workspace.TEXT_LIMIT + 1)), ('reports/code.html', '<script>bad</script>')], ids=['unregistered', 'binary', 'large', 'html'])
def test_artifact_reader_rejects_unregistered_binary_large_and_nontext(case, name, content):
    root, _, _, _ = case
    (root / name).write_text(content, encoding='utf-8')
    if name != 'secret.txt':
        tasks.checkpoint(root, 'report', 1, 'saved', 'check', [name])
    with pytest.raises(ValueError):
        workspace.artifact(root, 'report', name, 2 if name != 'secret.txt' else 1)


def test_path_traversal_and_internal_alias_rejected(case):
    root, _, _, _ = case
    for path in ('../outside.md', '/etc/passwd', 'drafts/../settings/config.md', 'C:/secret.md', 'drafts/a\\b.md'):
        with pytest.raises(ValueError):
            workspace.draft(root, path)
    with pytest.raises(ValueError, match='nested'):
        workspace.draft(root, 'drafts/subdir/same-name.md')
    target = root / 'drafts/real.md'
    target.write_text('test', encoding='utf-8')
    try:
        (root / 'drafts/alias.md').symlink_to(target)
    except OSError:
        return  # Platform lacks symlink permission; traversal checks above still ran.
    with pytest.raises(ValueError):
        workspace.draft(root, 'drafts/alias.md')


def test_first_real_query_has_backend_provenance_and_no_private_context(case):
    root, _, _, _ = case
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*.md')}
    with http(root) as request:
        diag = request('/api/workspace')
        assert diag['instance_valid'] and diag['retrieval']['actual_backend'] == 'not_queried'
        result = request('/api/workspace/query', {'query': 'Citations policy'})
        assert result['diagnostics']['requested_backend'] == 'fts5'
        assert result['diagnostics']['actual_backends']
        assert result['knowledge'] and result['task_context']['status'] == 'not_requested'
        with pytest.raises(HTTPError):
            request('/api/workspace/query', {'query': 'x' * 501})
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*.md')}


def test_explicit_source_change_preserves_previous_agreement_and_artifacts(case):
    root, _, task, _ = case
    extra = root / 'wiki/computing/strategies/extra.md'
    extra.write_text((root / task['agreement']['knowledge'][0]['path']).read_text(), encoding='utf-8')
    value = tasks.update_sources(root, 'report', 1, [extra.relative_to(root).as_posix()])
    assert value['history'][0]['agreement'] == task['agreement']
    assert value['agreement']['knowledge'][0]['path'].endswith('extra.md')
    with pytest.raises(ValueError, match='revision changed'):
        tasks.update_sources(root, 'report', 1, [])


def test_review_cli_option_is_separate_and_foreground_only(case):
    root, *_ = case
    result = CliRunner().invoke(app, ['mail', 'serve', '--path', str(root), '--local-review', '--background'])
    assert result.exit_code == 2 and 'foreground' in result.output
