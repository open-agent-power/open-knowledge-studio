"""Repair regression tests use synthetic instances; no fixture constitutes human approval."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from knowledge_studio import handoff, skills, store, tasks, workspace
from knowledge_studio.cli import app
from knowledge_studio.mail_web import create_server


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / '实例 空格'
    for folder in ('wiki', 'mail', 'drafts', 'profiles/goals'):
        (root / folder).mkdir(parents=True)
    monkeypatch.setenv('OKS_ROOT', str(root))
    return root


@contextmanager
def http(root, **options):
    server = create_server(root, 0, **options)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(route, payload=None, headers=None):
        if payload is not None and route in ('/api/tasks/create', '/api/skills/import-bundled'):
            payload = {'expected_knowledge_base': str(root), **payload}
        req = Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type': 'application/json', 'Origin': base, **(headers or {})})
        with urlopen(req, timeout=35) as response:
            return json.load(response)
    try:
        yield request
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def new(task_id='report'):
    return {'task_id': task_id, 'new_goal': {'title': '写报告', 'text': '保留来源，简洁说明。'}}


def test_commands_preserve_root_port_and_explicit_edit_permission(kb):
    for flags, suffix in [({}, ''), ({'local_review': True}, ' --local-review'), ({'local_edit': True}, ' --local-edit')]:
        result = workspace.diagnostics(kb, port=3195, **flags)
        assert str(kb) in result['commands']['resume'] and '--port 3195' in result['commands']['resume']
        assert result['commands']['resume'] == result['commands']['serve'] + suffix
    with pytest.raises(ValueError):
        create_server(kb, 0, mode='collaboration', local_edit=True)
    cli = CliRunner().invoke(app, ['mail', 'serve', '--path', str(kb), '--local-edit', '--background'])
    assert cli.exit_code != 0 and 'foreground' in cli.output


@pytest.mark.parametrize('options', [{}, {'local_review': True}, {'mode': 'collaboration'}])
def test_existing_modes_cannot_create_task_or_import_bundled(kb, options):
    with http(kb, **options) as request:
        for route in ('/api/tasks/create', '/api/skills/import-bundled'):
            with pytest.raises(HTTPError) as error:
                request(route, new())
            assert error.value.code == 403
    assert not (kb / 'profiles/goals/report.md').exists()


def test_edit_is_local_json_only_and_does_not_open_mail(kb):
    with http(kb, local_edit=True) as request:
        assert request('/api/mail/capabilities')['local_edit']
        for headers in ({'Origin': ''}, {'Origin': 'http://evil.invalid'}, {'Content-Type': 'text/plain'}):
            with pytest.raises(HTTPError) as error:
                request('/api/tasks/create', new(), headers)
            assert error.value.code == 403
        for route in ('/api/mail/send', '/api/mail/team/sync'):
            with pytest.raises(HTTPError) as error:
                request(route, {'push': True})
            assert error.value.code == 403
        with pytest.raises(HTTPError):
            request('/api/tasks/create', {**new(), 'padding': 'x' * 66000})
        with pytest.raises(HTTPError) as error:
            request('/api/tasks/create', {**new(), 'expected_knowledge_base': str(kb.parent / 'other')})
        assert error.value.code == 409 and json.load(error.value)['code'] == 'instance_changed'
        assert not (kb / 'profiles/goals/report.md').exists()
        value = request('/api/tasks/create', new())
        assert value['task_id'] == 'report' and value['status'] == 'current'
    assert tasks._load(kb, 'report')['agreement']['goal']['text'].endswith('保留来源，简洁说明。\n')


def test_existing_goal_and_reviewed_wiki_choices_are_explicit_and_revision_checked(kb):
    workspace.create_task(kb, new('first'))
    wiki = kb / 'wiki/rule.md'
    wiki.write_text("---\ntype: strategy\nstatus: active\ntitle: Cite\nhuman_reviewed_at: 'synthetic-fixture'\noptions: []\n---\nCite sources.\n", encoding='utf-8')
    (kb / 'wiki/pending.md').write_text('---\nstatus: draft\n---\nPending\n', encoding='utf-8')
    choices = workspace.task_options(kb)
    assert len(choices['goals']) == len(choices['wiki']) == 1
    selected = choices['goals'][0]
    request = {'task_id': 'second', 'goal_path': selected['path'], 'expected_goal_sha256': selected['sha256'],
               'wiki': [{key: choices['wiki'][0][key] for key in ('path', 'sha256')}]}
    value = workspace.create_task(kb, request)
    assert value['agreement']['knowledge'][0]['path'] == 'wiki/rule.md'
    with pytest.raises(ValueError, match='Goal changed'):
        workspace.create_task(kb, {**request, 'task_id': 'stale-goal', 'expected_goal_sha256': '0' * 64})
    wiki.write_text(wiki.read_text(encoding='utf-8') + 'Changed\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Wiki source changed'):
        workspace.create_task(kb, {**request, 'task_id': 'stale-wiki'})
    assert not tasks._path(kb, 'stale-goal').exists() and not tasks._path(kb, 'stale-wiki').exists()


def test_concurrent_create_is_single_task_without_overwriting_goal(kb):
    def create():
        try:
            return workspace.create_task(kb, new())['revision']
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert results.count(1) == 1 and sum('Task already exists' in str(v) for v in results) == 1
    before = (kb / 'profiles/goals/report.md').read_bytes()
    with pytest.raises(ValueError):
        workspace.create_task(kb, {**new(), 'new_goal': {'title': 'Overwrite', 'text': 'Overwrite'}})
    assert (kb / 'profiles/goals/report.md').read_bytes() == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows device path alias')
def test_windows_device_alias_never_permits_a_different_target(kb, monkeypatch):
    relative = '.oks/locks/workspace-create.lock'
    path = kb / relative
    original = type(kb).resolve
    target = type(kb)('\\\\?\\' + str(path))
    monkeypatch.setattr(type(kb), 'resolve', lambda self, *a, **kw: target if self == path else original(self, *a, **kw))
    assert tasks._inside(kb, relative) == path
    target = type(kb)('\\\\?\\' + str(kb.parent / 'outside'))
    with pytest.raises(ValueError, match='inside its root'):
        tasks._inside(kb, relative)


@pytest.mark.parametrize('path', ['../outside.md', 'wiki/../outside.md', 'wiki\\a.md', '/wiki/a.md', 'profiles/goals/report.md'])
def test_task_wiki_cannot_escape_bucket(kb, path):
    with pytest.raises(ValueError):
        workspace.create_task(kb, {**new(), 'wiki': [{'path': path, 'sha256': '0' * 64}]})
    assert not (kb / 'profiles/goals/report.md').exists()


def test_create_snapshot_rejects_concurrent_edit_and_preserves_new_goal(kb, monkeypatch):
    prepare = handoff.prepare
    def changed(root, goal, wiki, scope):
        path = root / goal
        path.write_text(path.read_text(encoding='utf-8') + 'Unreviewed change\n', encoding='utf-8')
        return prepare(root, goal, wiki, scope)
    monkeypatch.setattr(handoff, 'prepare', changed)
    with pytest.raises(ValueError, match='Goal preserved'):
        workspace.create_task(kb, new())
    assert not tasks._path(kb, 'report').exists()
    assert 'Unreviewed change' in (kb / 'profiles/goals/report.md').read_text(encoding='utf-8')


def test_title_is_yaml_data_and_unreviewed_sources_do_not_write_goal(kb):
    workspace.create_task(kb, {'task_id': 'quoted', 'new_goal': {'title': 'Report\nstatus: dropped', 'text': 'Goal'}})
    meta = handoff._meta((kb / 'profiles/goals/quoted.md').read_bytes())
    assert meta['status'] == 'active' and meta['title'] == 'Report\nstatus: dropped'
    pending = kb / 'wiki/pending.md'
    pending.write_text('---\nstatus: draft\n---\nPending', encoding='utf-8')
    with pytest.raises(ValueError, match='human-reviewed'):
        workspace.create_task(kb, {**new(), 'wiki': [{'path': 'wiki/pending.md', 'sha256': hashlib.sha256(pending.read_bytes()).hexdigest()}]})
    assert not (kb / 'profiles/goals/report.md').exists()


def test_bundled_compare_import_is_pending_and_preserves_old_wiki(kb, tmp_path):
    source = tmp_path / 'query'
    source.mkdir()
    (source / 'SKILL.md').write_text('---\nname: query\ndescription: old fixture\n---\nOld native instructions.\n', encoding='utf-8')
    old = store.get_wiki_page(store.promote_draft(skills.import_skill(source)['entry']['slug']))
    old_path = kb / old['file_path']
    before = old_path.read_bytes()
    version = old['skill_version']
    with http(kb, local_edit=True) as request:
        diff = request('/api/skills/bundled-diff?id=query&version=' + version)
        assert diff['instructions_differ'] and '-Old native instructions.' in diff['unified_diff']
        payload = {'id': 'query', 'version': version, 'expected_bundled_version': diff['bundled_version']}
        with pytest.raises(HTTPError) as error:
            request('/api/skills/import-bundled', {**payload, 'expected_bundled_version': '0' * 64})
        assert error.value.code == 409
        saved = request('/api/skills/import-bundled', payload)
        assert saved['path'].startswith('drafts/') and saved['review_required'] and not saved['old_wiki_changed']
        assert saved['entry']['skill_version'] == diff['bundled_version']
        assert request('/api/skills/import-bundled', payload)['duplicate']
    assert old_path.read_bytes() == before
    assert len(list((kb / 'wiki').rglob('*.md'))) == 1
    with pytest.raises(ValueError):
        skills.bundled_diff(kb, '../query', version)
    with pytest.raises(ValueError, match='Bundled Skill changed'):
        skills.import_skill(source, expected_version='0' * 64)
