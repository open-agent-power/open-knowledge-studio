"""Synthetic HTTP decisions bind the exact revision without consuming the Draft."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from knowledge_studio.mail_web import create_server
from knowledge_studio import workspace


@contextmanager
def server(root, *, review=True):
    service = create_server(root, 0, local_review=review)
    thread = Thread(target=service.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{service.server_port}'
    def request(route, body=None, *, origin=True):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = base
        query = Request(base + route, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urlopen(query, timeout=35) as response:
            return json.load(response)
    try:
        yield request
    finally:
        service.shutdown(); service.server_close(); thread.join(timeout=5)


@pytest.fixture
def ordinary(tmp_path, monkeypatch):
    root = tmp_path / '中文知识库'
    for name in ('wiki', 'raw', 'drafts', 'mail', 'profiles/goals', 'settings'):
        (root / name).mkdir(parents=True, exist_ok=True)
    candidate = root / 'drafts/ordinary.md'
    candidate.write_bytes(b'---\ntitle: Synthetic review\ndraft_type: strategy\ndraft_area: computing\nstatus: draft\n---\n\nKeep explicit sources.\n')
    monkeypatch.setenv('OKS_ROOT', str(tmp_path / 'unrelated-root'))
    return root, candidate


def test_rejection_checks_origin_and_exact_version_and_retains_history(ordinary):
    root, candidate = ordinary
    original = candidate.read_bytes()
    with server(root) as request:
        document = request('/api/learning/draft?path=drafts/ordinary.md')
        assert document['knowledge_base'] == str(root)
        body = {'path': document['path'], 'expected_sha256': document['sha256'],
                'expected_knowledge_base': document['knowledge_base'], 'confirm_reject': True}
        with pytest.raises(HTTPError) as missing_origin:
            request('/api/learning/reject', body, origin=False)
        assert missing_origin.value.code == 403
        with pytest.raises(HTTPError) as stale:
            request('/api/learning/reject', {**body, 'expected_sha256': '0' * 64})
        assert stale.value.code == 409
        assert candidate.read_bytes() == original and not list((root / 'drafts/rejected').glob('*.json'))
        assert request('/api/learning/reject', body)['status'] == 'rejected'
        history = request('/api/learning/draft?path=drafts/ordinary.md')
        assert history['review_status'] == 'rejected' and history['original_available']
        assert candidate.read_bytes() == original
        assert hashlib.sha256(original).hexdigest() == history['sha256']
        candidate.write_bytes(original + b'\nA new, unreviewed change.\n')
        current = request('/api/learning/draft?path=drafts/ordinary.md')
        assert current['review_status'] == 'draft'
        prior = request('/api/learning/draft?' + urlencode({'path': document['path'], 'revision': document['sha256']}))
        assert prior['review_status'] == 'rejected' and prior['sha256'] == document['sha256']
        assert b'new, unreviewed' not in prior['text'].encode()


def test_read_only_server_rejects_decision_without_writing(ordinary):
    root, candidate = ordinary
    original = candidate.read_bytes()
    with server(root, review=False) as request:
        body = {'path': 'drafts/ordinary.md', 'expected_sha256': hashlib.sha256(original).hexdigest(), 'confirm_reject': True}
        with pytest.raises(HTTPError) as denied:
            request('/api/learning/reject', body)
        assert denied.value.code == 403
    assert candidate.read_bytes() == original and not (root / '.oks/draft-reviews').exists()


@pytest.mark.parametrize('route', ['/api/learning/promote', '/api/learning/reject'])
@pytest.mark.parametrize('expected_root', [None, 'another-knowledge-base'])
def test_draft_decisions_reject_missing_or_changed_instance(ordinary, route, expected_root):
    root, candidate = ordinary
    original = candidate.read_bytes()
    with server(root) as request:
        body = {'path': 'drafts/ordinary.md', 'expected_sha256': hashlib.sha256(original).hexdigest(),
                'confirm_review': True, 'confirm_reject': True}
        if expected_root is not None:
            body['expected_knowledge_base'] = expected_root
        with pytest.raises(HTTPError) as denied:
            request(route, body)
        assert denied.value.code == 409
        assert json.load(denied.value)['code'] == 'instance_changed'
    assert candidate.read_bytes() == original
    assert not (root / '.oks/draft-reviews').exists()
    assert not list((root / 'wiki').rglob('*.md'))


def test_workspace_overview_and_audit_are_bound_to_server_root(ordinary):
    root, _ = ordinary
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with server(root) as request:
        home = request('/api/workspace/overview')
        audit = request('/api/workspace/retrieval')
    assert Path(home['knowledge_base']) == root and home['counts']['pending_drafts'] == 1
    assert Path(audit['knowledge_base']) == root and audit['actual_backend'] == 'not_probed'
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
