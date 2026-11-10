import json
from pathlib import Path
import subprocess
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from knowledge_studio import config, studio_libraries as libraries
from knowledge_studio.mail_web import create_server


def personal(path):
    for name in ('wiki', 'mail'):
        (path / name).mkdir(parents=True)
    return path.resolve()


def team(path):
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    (path / 'catalog').mkdir()
    (path / 'sources').mkdir()
    (path / 'catalog/knowledge.yaml').write_text(yaml.safe_dump({
        'schema_version': 1, 'repository': 'example/team', 'knowledge': []}))
    (path / 'sources/index.json').write_text('{"sources": []}')
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    return path


def test_team_config_validates_all_rows_before_replacing_and_rejects_stale(tmp_path):
    root = personal(tmp_path / 'personal')
    shared = team(tmp_path / 'team')
    original = libraries.libraries(root)
    row = {'name': 'shared', 'path': str(shared)}
    payload = {'sources_version': original['sources_version'], 'sources': [row]}
    current = libraries.save_sources(root, payload)
    before = (root / 'settings/sources.yaml').read_bytes()
    assert current['sources'][0]['repository'] == 'example/team'
    with pytest.raises(ValueError, match='已有更新'):
        libraries.save_sources(root, payload)
    with pytest.raises(ValueError):
        libraries.save_sources(root, {'sources_version': current['sources_version'], 'sources': [row, {'name': 'bad', 'path': str(tmp_path / 'missing')}]})
    assert (root / 'settings/sources.yaml').read_bytes() == before
    with pytest.raises(ValueError, match='独立目录'):
        libraries.save_sources(root, {'sources_version': current['sources_version'], 'sources': [{'name': 'bad', 'path': str(root / 'nested')}]})
    libraries.save_sources(root, {'sources_version': current['sources_version'], 'sources': []})
    assert libraries.libraries(root)['sources'] == []
    assert (shared / 'catalog/knowledge.yaml').is_file()
    assert subprocess.check_output(['git', '-C', str(shared), 'status', '--porcelain']) == b''


@pytest.mark.parametrize('editable', [False, True])
def test_library_http_capabilities_switch_and_stale_client(tmp_path, monkeypatch, editable):
    monkeypatch.setattr(config, 'config_dir', lambda: tmp_path / 'global-config')
    root = personal(tmp_path / 'first')
    second = personal(tmp_path / 'second')
    server = create_server(root, 0, local_edit=editable)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'

    def request(route, payload=None, origin=True):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = base
        req = Request(base + route, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    try:
        assert request('/api/studio/libraries')['personal_path'] == str(root)
        data = {'action': 'switch', 'personal_path': str(second), 'expected_knowledge_base': str(root)}
        with pytest.raises(HTTPError) as exc:
            request('/api/studio/libraries', data, origin=False)
        assert exc.value.code == 403
        if not editable:
            with pytest.raises(HTTPError) as exc:
                request('/api/studio/libraries', data)
            assert exc.value.code == 403
            assert server.kb_root == root
            return
        with pytest.raises(HTTPError) as exc:
            request('/api/studio/libraries', {**data, 'personal_path': str(tmp_path / 'missing')})
        assert exc.value.code == 400 and server.kb_root == root
        assert not config.config_path().exists()
        old_watcher = server.history_service
        assert request('/api/studio/libraries', data)['knowledge_base'] == str(second)
        assert old_watcher.stop_event.is_set()
        assert server.history_service.root == second
        assert config.load_config()['knowledge_base_path'] == str(second)
        assert request('/api/studio/libraries')['personal_path'] == str(second)
        with pytest.raises(HTTPError) as exc:
            request('/api/studio/file', {'expected_knowledge_base': str(root), 'path': 'profiles/goals/new.md', 'create': True, 'text': '# wrong root'})
        assert exc.value.code == 409
        assert not (root / 'profiles/goals/new.md').exists()
        assert not (second / 'profiles/goals/new.md').exists()
        with pytest.raises(HTTPError) as exc:
            request('/api/studio/libraries', data)
        assert exc.value.code == 409
    finally:
        server.shutdown(); server.server_close(); worker.join(5)


def test_switch_failure_keeps_previous_root_and_watcher(tmp_path, monkeypatch):
    root = personal(tmp_path / 'first')
    second = personal(tmp_path / 'second')
    monkeypatch.setattr(config, 'config_dir', lambda: tmp_path / 'global-config')
    server = create_server(root, 0, local_edit=True)
    previous = server.history_service

    def fail(_value):
        raise OSError('disk is read-only')

    monkeypatch.setattr(config, 'save_config', fail)
    try:
        with pytest.raises(OSError, match='read-only'):
            libraries.switch_personal(server, {'expected_knowledge_base': str(root), 'personal_path': str(second)})
        assert server.kb_root == root
        assert server.history_service is previous
        assert not previous.stop_event.is_set()
    finally:
        server.server_close()


def test_folder_names_need_no_manual_alias_and_existing_ids_stay_stable(tmp_path):
    root = personal(tmp_path / 'personal')
    first = team(tmp_path / 'team-knowledge')
    second_parent = tmp_path / 'another'; second_parent.mkdir()
    second = team(second_parent / 'team-knowledge')
    initial = libraries.libraries(root)
    saved = libraries.save_sources(root, {'sources_version': initial['sources_version'], 'sources': [{'path': str(first)}, {'path': str(second)}]})
    names = [row['name'] for row in saved['sources']]
    assert names[0] == 'team-knowledge'
    assert names[1].startswith('team-knowledge-') and names[0] != names[1]
    # An older short alias must not be replaced with the new display label.
    path = root / 'settings/sources.yaml'
    old = yaml.safe_load(path.read_text()); old['sources'][0]['name'] = 'legacy'
    path.write_text(yaml.safe_dump(old))
    current = libraries.libraries(root)
    saved = libraries.save_sources(root, {'sources_version': current['sources_version'], 'sources': [{'path': str(first)}, {'path': str(second)}]})
    assert [r['name'] for r in saved['sources']] == ['legacy', names[1]]


def test_native_folder_picker_uses_fixed_commands_and_cancel_is_not_a_setting_change(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(libraries.sys, 'platform', 'darwin')
    calls = []
    folder = tmp_path / '我的知识库'; folder.mkdir()
    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout=str(folder) + '/\n', stderr='')
    monkeypatch.setattr(libraries.subprocess, 'run', run)
    result = libraries.choose_folder()
    assert result == {'cancelled': False, 'path': str(folder), 'name': folder.name}
    assert calls[0][0][0] == 'osascript' and 'shell' not in calls[0][1]
    monkeypatch.setattr(libraries.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='User canceled. (-128)'))
    assert libraries.choose_folder() == {'cancelled': True, 'path': None}
    monkeypatch.setattr(libraries.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='permission denied'))
    with pytest.raises(ValueError, match='未能完成'):
        libraries.choose_folder()


@pytest.mark.parametrize('editable', [False, True])
def test_folder_picker_endpoint_requires_local_edit_origin_and_current_instance(tmp_path, monkeypatch, editable):
    root = personal(tmp_path / '个人库')
    calls = []
    monkeypatch.setattr(libraries, 'choose_folder', lambda: calls.append(True) or {'cancelled': True, 'path': None})
    server = create_server(root, 0, local_edit=editable)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(payload, origin=True):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = base
        req = Request(base + '/api/studio/libraries', data=json.dumps(payload).encode(), headers=headers)
        with urlopen(req, timeout=5) as response:
            return json.load(response)
    try:
        assert libraries.libraries(root)['personal_name'] == '个人库'
        payload = {'action': 'choose_folder', 'expected_knowledge_base': str(root)}
        with pytest.raises(HTTPError) as error:
            request(payload, origin=False)
        assert error.value.code == 403 and not calls
        if not editable:
            with pytest.raises(HTTPError) as error:
                request(payload)
            assert error.value.code == 403 and not calls
        else:
            with pytest.raises(HTTPError) as error:
                request({**payload, 'expected_knowledge_base': '/stale'})
            assert error.value.code == 409 and not calls
            server.folder_picker_lock.acquire()
            with pytest.raises(HTTPError):
                request(payload)
            server.folder_picker_lock.release()
            assert not calls
            assert request(payload)['cancelled'] and calls == [True]
            assert server.kb_root == root and not (root / 'settings/sources.yaml').exists()
    finally:
        server.shutdown(); server.server_close(); worker.join(5)
