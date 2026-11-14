"""Discussion section comments preserve their source and use real Mail facts."""
import base64
import hashlib
import json
import struct
import zlib

import pytest

from knowledge_studio import discussion_comments as comments
from knowledge_studio import mail, mail_runtime, studio

PATH = 'profiles/discuss/2026/11/08/comments.md'
SESSION = 'comment-agent'
MACHINE = 'machine_comment_test'
TEXT = '# Discussion\n\n## 人的判断\nOriginal judgment.\n\n## 待确认\nOriginal question.\n'


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


PNG = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / 'knowledge'
    (root / PATH).parent.mkdir(parents=True)
    (root / PATH).write_text(TEXT, encoding='utf-8', newline='')
    mail.register_session(root, SESSION, 'responsible-agent', machine_id=MACHINE)
    return root


def image(name='截图.png', data=PNG):
    return {'name': name, 'data_base64': base64.b64encode(data).decode('ascii')}


def payload(root, **overrides):
    return {'path': PATH, 'expected_sha256': studio.read_file(root, PATH)['sha256'],
            'anchor_id': 'section:3', 'text': '请核对原图中的结论。',
            'agent': '@responsible-agent', 'images': [], **overrides}


def send(root, **overrides):
    return comments.send(root, payload(root, **overrides), session_id='studio-comment-test')


def files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def row(root, record):
    return mail.parse_message(mail.canonical_path(root, record['message_id']))


def receive(root, record, *, session=SESSION, agent='responsible-agent', machine=MACHINE, delivered=True):
    return mail.record_delivery(root, session, row(root, record), agent_id=agent,
                                machine_id=machine, delivered=delivered)


def reply(root, record, **overrides):
    return mail.write_message(
        root, body=overrides.pop('body', '已核对，建议补充来源。'),
        sender=overrides.pop('sender', 'responsible-agent'), sender_kind=overrides.pop('sender_kind', 'agent'),
        recipients=overrides.pop('recipients', ['@human']),
        thread_id=overrides.pop('thread_id', record['thread_id']),
        reply_to=overrides.pop('reply_to', record['message_id']),
        origin_session_id=overrides.pop('origin_session_id', SESSION),
        origin_machine_id=overrides.pop('origin_machine_id', MACHINE), **overrides)


def result_body(record, **overrides):
    return {'schema': comments.RESULT_SCHEMA, 'comment_message_id': record['message_id'],
            'source_sha256': record['source_sha256'], 'result_sha256': record['source_sha256'],
            'status': 'answered', 'reply': '这一段需要补充出处。', 'changed': False, **overrides}


def result_reply(root, record, **overrides):
    return reply(root, record, body=json.dumps(result_body(record, **overrides), ensure_ascii=False),
                 record_kind='result')


def test_document_and_read_are_read_only_and_name_registered_agents(kb):
    before = files(kb)
    document = comments.document(kb, PATH)
    assert document == {
        'knowledge_base': str(kb), 'path': PATH, 'title': 'Discussion', 'text': TEXT,
        'sha256': hashlib.sha256(TEXT.encode()).hexdigest(),
        'sections': [
            {'id': 'section:1', 'title': 'Discussion', 'markdown': '# Discussion\n\n', 'start_line': 1, 'end_line': 2},
            {'id': 'section:3', 'title': '人的判断', 'markdown': '## 人的判断\nOriginal judgment.\n\n',
             'start_line': 3, 'end_line': 5},
            {'id': 'section:6', 'title': '待确认', 'markdown': '## 待确认\nOriginal question.\n',
             'start_line': 6, 'end_line': 7},
        ],
    }
    assert comments.read(kb, PATH) == {
        'knowledge_base': str(kb), 'path': PATH, 'sha256': document['sha256'], 'comments': [],
        'agents': [{'id': '@responsible-agent', 'label': 'responsible-agent'}],
    }
    assert files(kb) == before


def test_sections_keep_frontmatter_offsets_crlf_fences_comments_and_inline_code(kb):
    text = ('---\r\ntitle: Snapshot\r\n---\r\nPreamble `# code`.\r\n\r\n'
            '# First\r\n```markdown\r\n# Not a heading\r\n```\r\n'
            '<!--\r\n## Also not a heading\r\n-->\r\n'
            '  ## Child `__init__`\r\ntext\r\n')
    (kb / PATH).write_bytes(text.encode())
    document = comments.document(kb, PATH)
    sections = document['sections']
    assert document['text'] == text
    assert document['title'] == 'Snapshot'
    assert [(s['id'], s['title'], s['start_line'], s['end_line']) for s in sections] == [
        ('section:4', '前言', 4, 5), ('section:6', 'First', 6, 12),
        ('section:13', 'Child `__init__`', 13, 14),
    ]
    assert ''.join(section['markdown'] for section in sections) == text.split('---\r\n', 2)[2]
    assert '# Not a heading' in sections[1]['markdown']


@pytest.mark.parametrize('text', ['', 'Plain paragraph.\n\nSecond paragraph.', '---\ntitle: Empty\n---\n'])
def test_document_without_heading_always_has_a_commentable_whole_text_anchor(kb, text):
    (kb / PATH).write_bytes(text.encode())
    doc = comments.document(kb, PATH)
    assert len(doc['sections']) == 1
    section = doc['sections'][0]
    assert section['title'] == '全文' and section['end_line'] >= section['start_line']
    assert section['markdown'] == studio._markdown(text)[1]
    record = send(kb, anchor_id=section['id'])['comments'][0]
    assert record['anchor_md'] == section['markdown']


def test_setext_and_nested_fence_do_not_lose_later_sections(kb):
    text = ('Title\n=====\n\n## Work\n- example\n    ```markdown\n'
            '    # not a title\n    ```\n\nNext\n----\nFinal.\n')
    (kb / PATH).write_bytes(text.encode())
    sections = comments.document(kb, PATH)['sections']
    assert [(section['id'], section['title']) for section in sections] == [
        ('section:1', 'Title'), ('section:4', 'Work'), ('section:10', 'Next')]
    assert ''.join(section['markdown'] for section in sections) == text


def test_send_preserves_source_and_uses_human_canonical_mail_and_section_snapshot(kb):
    original = (kb / PATH).read_bytes()
    result = send(kb)
    record = result['comments'][0]
    message = row(kb, record)
    body = comments.comment(kb, message)
    assert body['schema'] == 'oks.discussion-comment.v2'
    assert {key: body[key] for key in ('path', 'anchor_id', 'text', 'agent', 'allow_edit')} == {
        'path': PATH, 'anchor_id': 'section:3', 'text': '请核对原图中的结论。',
        'agent': '@responsible-agent', 'allow_edit': False}
    assert body['anchor_md'] == '## 人的判断\nOriginal judgment.\n\n'
    assert body['snapshot_title'] == 'Discussion' and body['anchor_title'] == '人的判断'
    assert body['start_line'] == 3 and body['end_line'] == 5
    assert body['source_sha256'] == result['sha256']
    assert mail._normalise_agent(message['meta']['from']) == '@human'
    assert message['meta']['sender_kind'] == 'human'
    assert set(message['meta']['to']) == {'@human', '@responsible-agent'}
    assert message['meta']['origin_session_id'] == 'studio-comment-test'
    assert message['meta']['notify'].lower() == 'true' and message['meta']['evidence_refs'] == []
    assert not record['received'] and record['replies'] == []
    assert (kb / PATH).read_bytes() == original
    assert mail.load_state(kb, 'human', record['message_id'])['read_at'] is None
    assert mail.load_state(kb, 'responsible-agent', record['message_id'])['read_at'] is None


def test_image_only_comment_preserves_bytes_and_wait_delivers_real_local_paths(kb):
    record = send(kb, text='', images=[image(), image('same content.jpg')])['comments'][0]
    assert len(record['images']) == 2
    for index, attachment in enumerate(record['images']):
        assert attachment['mime'] == 'image/png' and attachment['path'].endswith(f'/{index}.png')
        assert (kb / attachment['path']).read_bytes() == PNG
        assert f'message_id={record["message_id"]}&index={index}' in attachment['url']
        assert comments.read_image(kb, record['message_id'], index) == (PNG, 'image/png')
    delivered = mail_runtime.FileMailRuntime(kb, 'responsible-agent', SESSION, MACHINE).wait(timeout=0)
    message = next(item for item in delivered['messages'] if item['message_id'] == record['message_id'])
    body = json.loads(message['body'])
    assert (kb / body['images'][0]['path']).read_bytes() == PNG
    assert '宿主读图工具读取原图' in body['instructions']
    assert comments.read(kb, PATH)['comments'][0]['received'] is True


@pytest.mark.parametrize('changes', [
    {'anchor_id': 'section:100'}, {'anchor_id': []}, {'anchor_id': 'human_judgment:1'},
    {'path': '../outside.md'}, {'path': 'wiki/not-discussion.md'},
    {'expected_sha256': '0' * 64}, {'agent': '@missing'}, {'agent': '@human'},
    {'text': ''}, {'text': 'x' * 20001}, {'text': None}, {'allow_edit': 'true'},
    {'images': [image(), image(), image()]},
    {'images': [image(), {'name': 'fake.png', 'data_base64': 'invalid!'}]},
    {'images': [image(data=b'<svg xmlns="http://www.w3.org/2000/svg"/>')]},
    {'images': [image(data=b'\x89PNG\r\n\x1a\n<html>fake</html>')]},
    {'images': [image(name='../escape.png')]},
])
def test_invalid_inputs_never_write_mail_or_attachments(kb, changes):
    before = files(kb)
    with pytest.raises((ValueError, FileNotFoundError)):
        comments.send(kb, payload(kb, **changes))
    assert files(kb) == before


def test_image_limit_and_missing_agent_are_checked_before_any_writes(kb):
    before = files(kb)
    with pytest.raises(ValueError, match='4 MiB'):
        send(kb, images=[image(data=PNG + b'x' * comments.MAX_IMAGE_BYTES)])
    assert files(kb) == before
    for session in mail.sessions_dir(kb).glob('*.json'):
        session.unlink()
    before = files(kb)
    with pytest.raises(ValueError, match='registered Agent'):
        send(kb)
    with pytest.raises(ValueError, match='human viewer'):
        comments.send(kb, payload(kb), requester='responsible-agent')
    assert files(kb) == before


def test_source_changed_during_validation_is_rechecked_under_the_studio_document_lock(kb, monkeypatch):
    decode = comments._decode_images
    def change_source(images):
        result = decode(images)
        (kb / PATH).write_bytes((TEXT + '\nNew text.\n').encode())
        return result
    monkeypatch.setattr(comments, '_decode_images', change_source)
    with pytest.raises(ValueError, match='Discussion changed'):
        send(kb, images=[image()])
    assert list(mail.iter_messages(kb)) == [] and not (kb / 'mail/comment-images').exists()


def test_receipt_requires_assigned_agent_presentation_and_reads_create_no_receipts(kb):
    record = send(kb)['comments'][0]
    receive(kb, record, session='other-session', agent='other')
    receive(kb, record, delivered=False)
    before = files(kb)
    assert comments.read(kb, PATH)['comments'][0]['received'] is False
    assert files(kb) == before
    receive(kb, record)
    assert comments.read(kb, PATH)['comments'][0]['received'] is True
    assert mail.load_state(kb, 'human', record['message_id'])['read_at'] is None


def test_plain_agent_reply_requires_matching_session_receipt_but_does_not_claim_a_result(kb):
    record = send(kb)['comments'][0]
    actual = reply(kb, record)
    assert comments.read(kb, PATH)['comments'][0]['replies'] == []
    receive(kb, record)
    assert comments.read(kb, PATH)['comments'][0]['replies'] == [{
        'from': '@responsible-agent', 'body': '已核对，建议补充来源。',
        'at': actual['meta']['timestamp'], 'message_id': actual['message_id']}]


@pytest.mark.parametrize('status', ['answered', 'needs_info', 'failed', 'updated'])
def test_valid_result_is_readable_and_retains_its_exact_source_revision(kb, status):
    record = send(kb, allow_edit=status == 'updated')['comments'][0]
    receive(kb, record)
    changes = {'status': status}
    if status == 'updated':
        changed_text = TEXT.replace('Original judgment.', 'Corrected judgment.')
        (kb / PATH).write_bytes(changed_text.encode())
        changes.update(changed=True, result_sha256=hashlib.sha256(changed_text.encode()).hexdigest())
    actual = result_reply(kb, record, **changes)
    result = comments.read(kb, PATH)
    answer = result['comments'][0]['replies'][0]
    assert answer['body'] == '这一段需要补充出处。' and answer['message_id'] == actual['message_id']
    assert answer['result'] == result_body(record, **changes)
    assert result['comments'][0]['source_sha256'] == record['source_sha256']
    assert result['comments'][0]['anchor_md'] == '## 人的判断\nOriginal judgment.\n\n'


@pytest.mark.parametrize('changes', [
    {'comment_message_id': 'another-comment'}, {'source_sha256': '0' * 64},
    {'result_sha256': ''}, {'status': 'accepted'}, {'reply': ''}, {'changed': 'true'},
    {'changed': True, 'result_sha256': '1' * 64},
    {'status': 'updated'},
])
def test_invalid_result_never_appears_as_a_completed_response(kb, changes):
    record = send(kb)['comments'][0]
    receive(kb, record)
    result_reply(kb, record, **changes)
    assert comments.read(kb, PATH)['comments'][0]['replies'] == []


@pytest.mark.parametrize('changes', [
    {'thread_id': 'unrelated-thread'}, {'reply_to': 'missing-parent'},
    {'sender': 'other'}, {'sender_kind': 'human'}, {'origin_session_id': 'other-session'},
    {'origin_machine_id': 'machine_other'}, {'recipients': ['private-peer']},
])
def test_result_requires_visible_parent_thread_agent_session_and_machine(kb, changes):
    record = send(kb)['comments'][0]
    receive(kb, record)
    reply(kb, record, body=json.dumps(result_body(record)), record_kind='result', **changes)
    assert comments.read(kb, PATH)['comments'][0]['replies'] == []


def test_result_to_a_human_followup_in_same_chain_is_supported(kb):
    record = send(kb)['comments'][0]
    receive(kb, record)
    followup = mail.write_message(kb, body='请优先处理出处。', sender='human', recipients=['responsible-agent'],
                                  thread_id=record['thread_id'], reply_to=record['message_id'])
    actual = reply(kb, record, body=json.dumps(result_body(record)), record_kind='result',
                   reply_to=followup['message_id'])
    assert comments.read(kb, PATH)['comments'][0]['replies'][0]['message_id'] == actual['message_id']


def test_result_does_not_attach_to_other_comment_or_unrelated_parent_in_same_thread(kb):
    original, second = send(kb)['comments'][0], send(kb)['comments'][1]
    receive(kb, original)
    # Valid payload for the first comment, but actually posted to the second Thread.
    reply(kb, second, body=json.dumps(result_body(original)), record_kind='result')
    unrelated = mail.write_message(kb, body='Unrelated', sender='human', recipients=['responsible-agent'],
                                   thread_id=original['thread_id'])
    reply(kb, original, body=json.dumps(result_body(original)), record_kind='result',
          reply_to=unrelated['message_id'])
    assert all(not item['replies'] for item in comments.read(kb, PATH)['comments'])


def test_old_anchor_snapshot_remains_after_source_edits_and_stale_send_is_rejected(kb):
    record = send(kb)['comments'][0]
    old_sha = record['source_sha256']
    (kb / PATH).write_bytes(('# New heading\n\n' + TEXT.replace('人的判断', 'New title')).encode())
    result = comments.read(kb, PATH)
    assert result['sha256'] != old_sha
    assert result['comments'][0]['anchor_title'] == '人的判断'
    assert result['comments'][0]['anchor_md'] == record['anchor_md']
    with pytest.raises(ValueError, match='Discussion changed'):
        send(kb, expected_sha256=old_sha)


def test_legacy_discussion_path_is_supported_without_moving_source(kb):
    path = 'discuss/2026/11/08/legacy.md'
    (kb / path).parent.mkdir(parents=True)
    (kb / path).write_bytes(b'No headings yet.\n')
    doc = comments.document(kb, path)
    assert doc['path'] == path
    record = send(kb, path=path, expected_sha256=doc['sha256'], anchor_id='section:1')['comments'][0]
    assert record['anchor_md'] == 'No headings yet.\n' and (kb / path).exists()


def test_image_endpoint_requires_human_visible_canonical_v2_comment(kb):
    record = send(kb, images=[image()])['comments'][0]
    message = row(kb, record)
    for message_id, index in [('missing', 0), (record['message_id'], -1), (record['message_id'], 1)]:
        with pytest.raises(FileNotFoundError):
            comments.read_image(kb, message_id, index)
    private = mail.write_message(kb, body=message['body'], sender='other', sender_kind='agent',
                                 recipients=['responsible-agent'])
    with pytest.raises(FileNotFoundError):
        comments.read_image(kb, private['message_id'], 0)
    assert comments.message_projection(kb, mail.parse_message(private['path'])) is None
    body = json.loads(message['body'])
    body['images'][0]['path'] = 'mail/comment-images/../../private.png'
    malformed = mail.write_message(kb, body=json.dumps(body), sender='human', recipients=['responsible-agent', 'human'])
    with pytest.raises(FileNotFoundError):
        comments.read_image(kb, malformed['message_id'], 0)
    (kb / record['images'][0]['path']).write_bytes(b'not an image')
    with pytest.raises(FileNotFoundError):
        comments.read_image(kb, record['message_id'], 0)


@pytest.mark.parametrize('allow_edit', [False, True])
def test_mail_projection_is_plain_text_and_old_schema_is_not_accepted(kb, allow_edit):
    record = send(kb, text='<script>literal comment</script>', images=[image()], allow_edit=allow_edit)['comments'][0]
    before = files(kb)
    projection = comments.message_projection(kb, row(kb, record))
    permission = '允许修改本节' if allow_edit else '仅回复'
    assert projection['text'] == (f'对 {PATH} · 人的判断 的留言\n原文版本 {record["source_sha256"][:12]}\n'
                                  f'权限 {permission}\n\n'
                                  '<script>literal comment</script>')
    assert projection['images'] == record['images'] and files(kb) == before
    old = comments.comment(kb, row(kb, record)).copy()
    old['schema'] = 'oks.discussion-comment.v1'
    message = mail.write_message(kb, body=json.dumps(old), sender='human', recipients=['responsible-agent', 'human'])
    assert comments.comment(kb, mail.parse_message(message['path'])) is None
    assert len(comments.read(kb, PATH)['comments']) == 1


@pytest.mark.parametrize('status,label', [
    ('answered', '已答复'), ('needs_info', '待补充'), ('failed', '处理失败'), ('updated', '已更新原文'),
])
def test_result_mail_projection_is_validated_readable_and_read_only(kb, status, label):
    record = send(kb, allow_edit=status == 'updated')['comments'][0]
    receive(kb, record)
    changes = {'status': status}
    if status == 'updated':
        (kb / PATH).write_bytes(TEXT.replace('Original judgment.', 'Corrected judgment.').encode())
        changes.update(changed=True, result_sha256=studio.read_file(kb, PATH)['sha256'])
    actual = result_reply(kb, record, **changes)
    before = files(kb)
    projection = comments.message_projection(kb, mail.parse_message(actual['path']))
    assert projection == {
        'text': f'@responsible-agent 回报 · {label}\n讨论 {PATH} · 人的判断\n'
                f'原文版本 {record["source_sha256"][:12]}\n'
                f'结果版本 {changes.get("result_sha256", record["source_sha256"])[:12]}\n\n'
                '这一段需要补充出处。',
        'images': [],
    }
    assert files(kb) == before


@pytest.mark.parametrize('changes', [
    {}, {'thread_id': 'another-thread'}, {'reply_to': 'missing-parent'}, {'sender': 'another-agent'},
    {'origin_session_id': 'another-session'}, {'origin_machine_id': 'machine_other'},
    {'recipients': ['private-peer']},
])
def test_result_mail_projection_cannot_infer_completion_from_json_without_its_actual_receipt(kb, changes):
    record = send(kb)['comments'][0]
    actual = reply(kb, record, body=json.dumps(result_body(record)), record_kind='result', **changes)
    result_row = mail.parse_message(actual['path'])
    assert comments.message_projection(kb, result_row) is None
    receive(kb, record)
    if changes:
        assert comments.message_projection(kb, result_row) is None
    else:
        assert '已答复' in comments.message_projection(kb, result_row)['text']
