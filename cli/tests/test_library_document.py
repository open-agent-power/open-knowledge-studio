"""Graph readers retain the selected library identity and immutable revision."""
import json
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from knowledge_studio import linked_sources, mail_web
from .test_linked_sources import git, commit


@pytest.fixture
def libraries(tmp_path):
    root = tmp_path / 'personal'
    (root / 'wiki').mkdir(parents=True)
    (root / 'mail').mkdir()
    (root / 'wiki/one.md').write_text('# Personal\nPersonal body.', encoding='utf-8')
    repo = tmp_path / 'team'
    (repo / 'wiki').mkdir(parents=True)
    (repo / 'settings').mkdir()
    git(repo, 'init', '-q')
    (repo / 'settings/library.yaml').write_text(
        'schema_version: 1\nlayout: oks\nrepository: org/team\n', encoding='utf-8')
    (repo / 'wiki/one.md').write_text('# Team\nTeam version one.', encoding='utf-8')
    revision = commit(repo)
    linked_sources.link(root, 'team', repo, 'org/team')
    return root, repo, revision


def test_library_reader_preserves_namespace_and_selected_revision(libraries):
    root, repo, first = libraries
    configuration = (root / 'settings/sources.yaml').read_bytes()
    (repo / 'wiki/one.md').write_text('# Team\nTeam version two.', encoding='utf-8')
    second = commit(repo)
    (repo / 'wiki/one.md').write_text('# Uncommitted\nPrivate edit.', encoding='utf-8')

    old = mail_web.library_document(root, 'team', 'wiki/one.md', first)
    current = mail_web.library_document(root, 'team', 'wiki/one.md', second)

    assert old['body'] == '# Team\nTeam version one.'
    assert current['body'] == '# Team\nTeam version two.'
    assert old['revision'] == first and current['revision'] == second
    assert old['id'].startswith('team:team/')
    assert old['uri'] == 'oks://team/team/wiki/one.md'
    assert old['read_only'] is True
    assert old['body_html'] == mail_web.md_to_html(old['body'])
    assert 'Team version one.' in old['body_html']
    assert 'Personal body' not in old['body_html']
    assert (root / 'settings/sources.yaml').read_bytes() == configuration


@pytest.mark.parametrize('library,path,revision', [
    ('missing', 'wiki/one.md', 'a' * 40),
    ('team', '../personal/wiki/one.md', 'a' * 40),
    ('team', 'wiki/one.md', 'HEAD'),
])
def test_library_reader_requires_linked_identity_and_fixed_revision(libraries, library, path, revision):
    root, _, _ = libraries
    with pytest.raises(ValueError):
        mail_web.library_document(root, library, path, revision)


def test_library_document_http_is_read_only_and_returns_selected_body(libraries):
    root, _, revision = libraries
    server = mail_web.create_server(root, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        query = urlencode({'library': 'team', 'path': 'wiki/one.md', 'revision': revision})
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/studio/library-document?' + query) as response:
            result = json.load(response)
        assert result['revision'] == revision
        assert result['body'] == '# Team\nTeam version one.'
        assert result['read_only'] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
