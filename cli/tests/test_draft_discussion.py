"""The discussion object is a Draft, never an inferred section or promoted log."""
import base64
import hashlib
import json
import sys

import pytest

from knowledge_studio import discussion_agent, discussion_comments, draft_discussion, draft_review, mail, store, studio, studio_history, studio_workflow
from .test_discussion_agent import PNG
from .test_studio_workflow import source_bundle, BUNDLE
from .test_mail_knowledge import raw_bundle


def put(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='')
    return path


def draft(root, slug='one', source='discuss/source.md'):
    return put(root, f'drafts/{slug}.md', f'---\ntitle: Named Draft\ndraft_type: strategy\ndraft_area: computing\nsources: [{source}]\n---\n# Named Draft\n\n## 人的判断\nFirst.\n\n## 待确认\nSecond.\n')


def test_graph_is_one_node_per_draft_with_shared_explicit_source(tmp_path):
    draft(tmp_path)
    draft(tmp_path, 'two')
    put(tmp_path, 'discuss/source.md', '# Original discussion\n## 人的判断\nOriginal.\n')
    put(tmp_path, 'wiki/unrelated.md', '# Separate Wiki\n')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    data = draft_discussion.graph(tmp_path)
    assert [(node['path'], node['type']) for node in data['nodes']] == [
        ('drafts/one.md', 'drafts'), ('drafts/two.md', 'drafts'), ('discuss/source.md', 'source')]
    assert len(data['edges']) == 2
    assert {edge['to'] for edge in data['edges']} == {'discuss/source.md'}
    assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


def test_bundle_source_aliases_share_a_readable_source_node(tmp_path):
    base = raw_bundle(tmp_path, 'captured', '# Original source\nRetained excerpt.', 'partial')
    draft(tmp_path, source=base + '/source/excerpt.txt')
    draft(tmp_path, 'two', source=base + '/content.md')
    put(tmp_path, 'raw/unrelated/bundle.json', '{broken')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}

    graph = draft_discussion.graph(tmp_path)
    assert [(node['path'], node['type']) for node in graph['nodes']] == [
        ('drafts/one.md', 'drafts'), ('drafts/two.md', 'drafts'), (base + '/raw.md', 'source')]
    assert {edge['to'] for edge in graph['edges']} == {base + '/raw.md'}
    detail = draft_discussion.reader(tmp_path, 'drafts/one.md')
    source, = detail['sources']
    assert source['path'] == base + '/raw.md'
    assert source['title'] == 'Original source'
    assert set(source['aliases']) == {base + '/raw.md', base + '/content.md', base + '/source/excerpt.txt'}
    for alias in source['aliases']:
        reading = draft_discussion.reader(tmp_path, alias)
        assert reading['path'] == base + '/raw.md'
        assert reading['body_path'] == base + '/content.md'
        assert reading['text'].splitlines() == ['# Original source', 'Retained excerpt.']
        assert reading['processing_status'] == 'partial'
    assert graph['warnings'] == []
    assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


def test_unlisted_same_name_source_is_not_assigned_to_a_bundle(tmp_path):
    base = raw_bundle(tmp_path, 'captured')
    manifest = tmp_path / base / 'bundle.json'
    bundle = json.loads(manifest.read_text(encoding='utf-8'))
    bundle['sources'] = []
    manifest.write_text(json.dumps(bundle), encoding='utf-8')
    draft(tmp_path, source=base + '/source/excerpt.txt')
    assert draft_discussion.reader(tmp_path, 'drafts/one.md')['sources'] == []
    assert draft_discussion.graph(tmp_path)['edges'] == []


def test_source_without_raw_wrapper_uses_the_manifest_content(tmp_path):
    base = raw_bundle(tmp_path, 'without-wrapper', '# Preserved content', 'failed')
    (tmp_path / base / 'raw.md').unlink()
    draft(tmp_path, source=base + '/source/excerpt.txt')
    source, = draft_discussion.reader(tmp_path, 'drafts/one.md')['sources']
    assert source['path'] == base + '/content.md'
    reading = draft_discussion.reader(tmp_path, source['path'])
    assert reading['text'] == '# Preserved content'
    assert reading['processing_status'] == 'failed'


def test_standalone_raw_source_preserves_its_recorded_processing_status(tmp_path):
    put(tmp_path, 'raw/standalone.md', '---\nprocessing_status: partial\n---\n# Standalone source\n')
    assert draft_discussion.reader(tmp_path, 'raw/standalone.md')['processing_status'] == 'partial'


def test_no_processing_records_does_not_create_a_default_pipeline(tmp_path):
    file = draft(tmp_path)
    studio_history.observe(tmp_path, 'drafts/one.md', file.read_text(encoding='utf-8'))
    result = draft_discussion.reader(tmp_path, 'drafts/one.md')
    assert result['steps'] == []
    assert result['changes'] == ''
    assert result['review_status'] == 'draft'
    assert not result['discussion']['comments']


def test_reader_does_not_construct_discarded_mail_steps(tmp_path, monkeypatch):
    draft(tmp_path)

    def unused_comments(*args):
        raise AssertionError('Reader already has canonical comments')

    monkeypatch.setattr(studio_workflow, '_comment_steps', unused_comments)
    assert draft_discussion.reader(tmp_path, 'drafts/one.md')['steps'] == []


def test_draft_graph_reuses_one_promotion_index(tmp_path, monkeypatch):
    draft(tmp_path)
    draft(tmp_path, 'two')
    calls = []
    original = draft_review.promotions

    def counted(root):
        calls.append(root)
        return original(root)

    monkeypatch.setattr(draft_review, 'promotions', counted)
    assert len(draft_discussion.graph(tmp_path)['nodes']) == 2
    assert len(calls) == 1


def test_draft_process_retains_partial_extraction_and_exact_revision_diff(tmp_path):
    source_bundle(tmp_path, fragment_status='partial')
    draft(tmp_path, source=BUNDLE + '/raw.md')
    before = studio.read_file(tmp_path, 'drafts/one.md')
    studio.save_file(tmp_path, {'path': before['path'], 'text': before['text'].replace('First.', 'Changed.'),
                              'expected_sha256': before['sha256'], 'actor': '@codex'})
    result = draft_discussion.reader(tmp_path, before['path'])
    assert result['steps'][0]['status'] == 'partial'
    assert result['steps'][0]['extractor']['tool'] == 'text-read'
    assert result['steps'][-1]['agent'] == '@codex'
    assert '-First.' in result['changes'] and '+Changed.' in result['changes']
    assert result['steps'][-1]['outputs'][0]['path'] == before['path']


def test_whole_draft_comment_and_image_reach_receiver_preserving_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(discussion_agent.shutil, 'which', lambda name: sys.executable)
    path = draft(tmp_path)
    before = path.read_bytes()
    source = put(tmp_path, 'discuss/source.md', '# Source remains separate\n')
    worker = discussion_agent.DiscussionAgent(tmp_path, 'codex')
    mail.register_session(tmp_path, worker.session_id, worker.agent_id, machine_id=worker.machine_id)
    doc = discussion_comments.document(tmp_path, 'drafts/one.md')
    assert len(doc['sections']) == 1 and doc['sections'][0]['title'] == '全文'
    assert '## 人的判断' in doc['sections'][0]['markdown'] and '## 待确认' in doc['sections'][0]['markdown']
    sent = discussion_comments.send(tmp_path, {'path': doc['path'], 'expected_sha256': doc['sha256'],
        'anchor_id': doc['sections'][0]['id'], 'text': 'Please revise the Draft.', 'agent': '@codex',
        'images': [{'name': 'sample.png', 'data_base64': base64.b64encode(PNG).decode()}], 'allow_edit': True})
    record = sent['comments'][0]
    assert not record['received'] and not record['replies']
    assert discussion_comments.read_image(tmp_path, record['message_id'], 0) == (PNG, 'image/png')
    captured = []
    def answer(body, document, directory):
        captured.append(body)
        return {'reply': 'Updated the Draft.', 'replacement': body['anchor_md'].replace('First.', 'Revised.'), 'needs_info': False}
    monkeypatch.setattr(worker, '_answer', answer)
    worker.scan()
    assert captured[0]['images'][0]['name'] == 'sample.png'
    assert path.read_bytes() == before.replace(b'First.', b'Revised.')
    assert source.read_text() == '# Source remains separate\n'
    read = discussion_comments.read(tmp_path, doc['path'])['comments'][0]
    assert read['received'] and read['replies'][0]['result']['status'] == 'updated'
    assert not list((tmp_path / 'wiki').rglob('*.md'))


def test_comment_requires_current_version_and_cannot_target_source_or_wiki(tmp_path):
    file = draft(tmp_path)
    doc = discussion_comments.document(tmp_path, 'drafts/one.md')
    file.write_bytes(file.read_bytes() + b'new text\n')
    with pytest.raises(ValueError, match='changed'):
        discussion_comments.send(tmp_path, {'path': doc['path'], 'expected_sha256': doc['sha256']})
    for path in ('raw/source.md', 'wiki/page.md'):
        put(tmp_path, path, '# Only read\n')
        with pytest.raises(ValueError, match='Draft or discussion'):
            discussion_comments.document(tmp_path, path)


def test_promotion_only_writes_selected_draft_not_discussion_or_mail(tmp_path, monkeypatch):
    monkeypatch.setenv('OKS_ROOT', str(tmp_path))
    file = draft(tmp_path)
    source = put(tmp_path, 'discuss/source.md', '# SOURCE_ONLY_SECRET_MARKER\n')
    log = put(tmp_path, 'mail/private-log.md', '# COMMENT_ONLY_SECRET_MARKER\n')
    before = {path: path.read_bytes() for path in (file, source, log)}
    digest = hashlib.sha256(before[file]).hexdigest()
    store.promote_draft('one', expected_sha256=digest)
    wiki = list((tmp_path / 'wiki').rglob('*.md'))
    assert len(wiki) == 1
    text = wiki[0].read_text(encoding='utf-8')
    assert 'First.' in text and 'SOURCE_ONLY_SECRET_MARKER' not in text and 'COMMENT_ONLY_SECRET_MARKER' not in text
    assert {path: path.read_bytes() for path in before} == before
    assert draft_discussion.graph(tmp_path)['nodes'][0]['review_status'] == 'promoted'
    file.write_bytes(before[file] + b'\nNew revision\n')
    assert draft_discussion.graph(tmp_path)['nodes'][0]['review_status'] == 'draft'


def test_nested_draft_can_be_read_and_commented_without_offering_unsupported_promotion(tmp_path):
    put(tmp_path, 'drafts/topic/draft.md', '# Nested\n\nText.\n')
    result = draft_discussion.reader(tmp_path, 'drafts/topic/draft.md')
    assert result['kind'] == 'drafts' and not result['promotable']
    assert result['anchor_id'] == 'section:1'
