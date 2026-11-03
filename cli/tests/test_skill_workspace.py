"""Synthetic local-instance API acceptance, not evidence of real human approval."""
from contextlib import contextmanager
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from knowledge_studio import skills, store
from knowledge_studio.cli import app
from knowledge_studio.mail_web import create_server


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-kb'
    for name in ('wiki', 'drafts', 'mail', 'profiles/goals'):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv('OKS_ROOT', str(root))
    source = tmp_path / 'standard'
    source.mkdir()
    (source / 'SKILL.md').write_text('---\nname: standard\ndescription: Synthetic fixture\n---\nKeep sources.\n', encoding='utf-8', newline='\n')
    imported = skills.import_skill(source)
    slug = store.promote_draft(imported['entry']['slug'])  # Synthetic fixture approval only.
    page = store.get_wiki_page(slug)
    return root, {'id': page['skill_id'], 'version': page['skill_version']}


@contextmanager
def server(root, *, edit=False):
    service = create_server(root, 0, local_edit=edit)
    thread = Thread(target=service.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{service.server_port}'
    def request(path, payload=None, origin=None):
        req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type':'application/json', 'Origin':origin or base})
        with urlopen(req, timeout=35) as response:
            return json.load(response)
    try:
        yield request
    finally:
        service.shutdown(); service.server_close(); thread.join(timeout=5)


def test_reader_can_inspect_skill_and_cannot_derive(sample):
    root, ref = sample
    with server(root) as request:
        assert request('/api/skills/catalog')['items'][0]['id'] == 'standard'
        detail = request('/api/skills/source?id=standard&version=' + ref['version'])
        assert 'Keep sources.' in detail['instructions']
        with pytest.raises(HTTPError) as error:
            request('/api/skills/derive', {'expected_knowledge_base':str(root), 'base':ref, 'changes':{}})
        assert error.value.code == 403
    assert not store.list_drafts()


def test_local_skill_derivation_is_instance_bound_pending_and_preserves_base(sample):
    root, ref = sample
    before = {p:p.read_bytes() for p in (root/'wiki').rglob('*.md')}
    with server(root, edit=True) as request:
        detail = request('/api/skills/source?id=standard&version=' + ref['version'])
        payload = {'expected_knowledge_base':str(root), 'base':ref, 'changes':{'SKILL.md':detail['instructions']+'\nPrefer short answers.\n'}}
        with pytest.raises(HTTPError) as error:
            request('/api/skills/derive', {**payload, 'expected_knowledge_base':str(root/'other')})
        assert error.value.code == 409
        with pytest.raises(HTTPError) as error:
            request('/api/skills/derive', payload, origin='https://outside.invalid')
        assert error.value.code == 403
        created = request('/api/skills/derive', payload)
        assert created['review_state'] == 'pending_review'
        draft = request('/api/learning/draft?path='+created['draft_path'])
        assert draft['review_status'] == 'draft'
        assert 'Prefer short answers.' in draft['text']
    assert {p:p.read_bytes() for p in (root/'wiki').rglob('*.md')} == before


def test_cli_personal_notes_create_a_separate_unreviewed_variant(sample):
    root, ref = sample
    result = CliRunner().invoke(app, ['skills','derive','standard','--version',ref['version'],'--id','my-standard','--notes','Use short sentences.'])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value['ref']['id'] == 'my-standard' and value['review_state'] == 'pending_review'
    assert len(list((root/'wiki').rglob('*.md'))) == 1
