"""Comments on exact discussion sections, delivered and answered through Mail."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode
import uuid

from . import discussion_review, mail, mail_media, store, studio, tasks

SCHEMA = 'oks.discussion-comment.v2'
RESULT_SCHEMA = 'oks.discussion-comment.result.v1'
MAX_IMAGES = 2
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TEXT = 20000
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif',
              'image/webp': 'webp', 'image/bmp': 'bmp'}
IMAGE_PATH = re.compile(r'mail/comment-images/[0-9a-f]{32}/[01]\.(png|jpg|gif|webp|bmp)')
SHA = re.compile(r'[0-9a-f]{64}')


def _file(root, path):
    file = studio.read_file(root, path)
    if file['kind'] not in {'discuss', 'drafts'}:
        raise ValueError('Choose a Draft or discussion Markdown file')
    return file


def _sections(text):
    """Nonoverlapping source slices; line numbers are one-based in the whole file."""
    _, body, offset = studio._markdown(text)
    lines = body.splitlines(keepends=True)
    masked = re.sub(r'<!--[\s\S]*?(?:-->|$)',
                    lambda match: re.sub(r'[^\r\n]', ' ', match[0]), body).splitlines()
    starts, fence, previous_prose = [], None, False
    for index, line in enumerate(masked):
        marker = re.match(r'^\s*(?:(?:[-+*]|\d+[.)])\s+)?(`{3,}|~{3,})', line)
        if fence:
            if re.fullmatch(r'\s*' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*', line):
                fence = None
            previous_prose = False
            continue
        if marker:
            fence = marker[1][0], len(marker[1])
            previous_prose = False
            continue
        heading = re.match(r'^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$', line)
        if heading:
            starts.append((index, heading[1]))
        setext = not heading and previous_prose and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', line)
        if setext:
            starts.append((index - 1, masked[index - 1].strip()))
        previous_prose = bool(line.strip()) and not heading and not setext and not re.match(
            r'^(?: {4}|\t| {0,3}(?:[-+*>]|\d+[.)])[ \t])', line)
    if not starts or starts[0][0] and ''.join(lines[:starts[0][0]]).strip():
        starts.insert(0, (0, '全文' if not starts else '前言'))
    sections = []
    for position, (start, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        sections.append({'id': f'section:{offset + start + 1}', 'title': title,
                         'markdown': ''.join(lines[start:end]),
                         'start_line': offset + start + 1, 'end_line': max(offset + start + 1, offset + end)})
    return sections


def document(root, path):
    root = Path(root).resolve()
    file = _file(root, path)
    sections = _sections(file['text'])
    if file['kind'] == 'drafts':
        _, body, offset = studio._markdown(file['text'])
        sections = [{'id': f'section:{offset + 1}', 'title': '全文', 'markdown': body,
                     'start_line': offset + 1, 'end_line': max(offset + 1, len(file['text'].splitlines()))}]
    return {
        'knowledge_base': str(root), 'path': file['path'], 'title': file['title'],
        'text': file['text'], 'sha256': file['sha256'], 'sections': sections,
    }


def _name(value):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 240
            and not any(char in value for char in ('/', '\\', '\x00', '\r', '\n')))


def _decode_images(images):
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError('Attach at most two images')
    decoded = []
    for image in images:
        if not isinstance(image, dict) or not _name(image.get('name')):
            raise ValueError('Provide an image filename')
        encoded = image.get('data_base64')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError('Each image must be at most 4 MiB')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Provide a base64 raster image') from exc
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError('Each image must be nonempty and at most 4 MiB')
        try:
            mime, _, _ = mail_media.image_info(data)
        except OSError as exc:
            raise ValueError('Unsupported or invalid raster image') from exc
        decoded.append((image['name'], mime, data))
    return decoded


def comment(root, row):
    """Validate a canonical v2 human comment, including its preserved section snapshot."""
    if row is None:
        return None
    meta = row['meta']
    if (row['path'] != mail.canonical_path(root, meta['message_id'])
            or mail._normalise_agent(meta.get('from')) != '@human'
            or meta.get('sender_kind') != 'human' or meta.get('record_kind') != 'message'
            or '@human' not in meta.get('to', [])):
        return None
    body = discussion_review._body(row, SCHEMA)
    if body is None:
        return None
    path, agent = body.get('path'), body.get('agent')
    text, images = body.get('text'), body.get('images')
    start, end = body.get('start_line'), body.get('end_line')
    if (not isinstance(path, str) or not any(path.startswith(p + '/') for p in (*studio.DISCUSS_ROOTS, 'drafts'))
            or type(start) is not int or type(end) is not int or start < 1 or end < start
            or body.get('anchor_id') != f'section:{start}'
            or any(not isinstance(body.get(key), str) for key in ('anchor_title', 'anchor_md', 'snapshot_title'))
            or not isinstance(text, str) or len(text) > MAX_TEXT or '\x00' in text
            or not isinstance(images, list) or len(images) > MAX_IMAGES or not (text.strip() or images)
            or not isinstance(body.get('source_sha256'), str) or SHA.fullmatch(body['source_sha256']) is None
            or type(body.get('allow_edit')) is not bool
            or not isinstance(agent, str) or agent in {'@human', '@all', '@unknown'}
            or agent != mail._normalise_agent(agent) or agent not in meta.get('to', [])):
        return None
    try:
        studio._path(Path(root), path)
    except ValueError:
        return None
    for index, image in enumerate(images):
        if (not isinstance(image, dict) or not _name(image.get('name'))
                or image.get('mime') not in EXTENSIONS or not isinstance(image.get('path'), str)
                or IMAGE_PATH.fullmatch(image['path']) is None
                or not image['path'].endswith(f"/{index}.{EXTENSIONS[image['mime']]}")):
            return None
    return body


def _images(row, body):
    return [{**image, 'url': '/api/studio/discussion-comments/image?' + urlencode({
        'message_id': row['meta']['message_id'], 'index': index,
    })} for index, image in enumerate(body['images'])]


def _visible(root, message_id):
    return next((row for row in discussion_review._rows(root, 'human')
                 if row['meta']['message_id'] == message_id), None)


def message_projection(root, row):
    """Human-readable Mail content, without changing delivery or read state."""
    rows = discussion_review._rows(root, 'human')
    visible = next((item for item in rows
                    if item['meta']['message_id'] == row['meta'].get('message_id')), None)
    if visible is None or row['path'] != visible['path']:
        return None
    body = comment(root, visible)
    if body is not None:
        permission = '允许修改本节' if body['allow_edit'] else '仅回复'
        return {'text': f"对 {body['path']} · {body['anchor_title']} 的留言\n"
                        f"原文版本 {body['source_sha256'][:12]}\n权限 {permission}\n\n{body['text']}",
                'images': _images(visible, body)}
    result = discussion_review._body(visible, RESULT_SCHEMA)
    if result is None:
        return None
    original = next((item for item in rows
                     if item['meta']['message_id'] == result.get('comment_message_id')), None)
    body = comment(root, original)
    if body is None:
        return None
    reply = next((item for item in _replies(root, rows, original, body)
                  if item['message_id'] == visible['meta']['message_id'] and 'result' in item), None)
    if reply is None:
        return None
    labels = {'updated': '已更新原文', 'answered': '已答复', 'needs_info': '待补充', 'failed': '处理失败'}
    return {'text': f"{body['agent']} 回报 · {labels[result['status']]}\n"
                    f"讨论 {body['path']} · {body['anchor_title']}\n"
                    f"原文版本 {body['source_sha256'][:12]}\n结果版本 {result['result_sha256'][:12]}\n\n"
                    + reply['body'], 'images': []}


def _reply_chain(row, original, by_id, agent):
    seen = set()
    while row['meta']['message_id'] not in seen:
        seen.add(row['meta']['message_id'])
        parent = mail.visible_reply_parent(row, by_id)
        if parent is None:
            followup = by_id.get(row['meta'].get('reply_to'))
            # A human may add context before the Agent replies to the latest message.
            if followup is not None and all(
                mail._normalise_agent(item['meta'].get('from')) == '@human'
                and item['meta'].get('sender_kind') == 'human'
                and item['meta'].get('thread_id') == original['meta']['thread_id']
                and agent in item['meta'].get('to', []) for item in (row, followup)
            ):
                parent = followup
        if parent is None:
            return False
        if parent['meta']['message_id'] == original['meta']['message_id']:
            return True
        row = parent
    return False


def _result(row, original, body):
    result = discussion_review._body(row, RESULT_SCHEMA)
    if (result is None or row['meta'].get('record_kind') != 'result'
            or result.get('comment_message_id') != original['meta']['message_id']
            or result.get('status') not in {'updated', 'answered', 'needs_info', 'failed'}
            or not isinstance(result.get('reply'), str) or not result['reply'].strip()
            or type(result.get('changed')) is not bool
            or result.get('source_sha256') != body['source_sha256']
            or not isinstance(result.get('result_sha256'), str) or SHA.fullmatch(result['result_sha256']) is None
            or result['changed'] and not body['allow_edit']
            or result.get('status') == 'updated' and (
                not result['changed'] or result['result_sha256'] == body['source_sha256'])):
        return None
    return result


def _replies(root, rows, original, body):
    by_id = {row['meta']['message_id']: row for row in rows}
    replies = []
    for row in rows:
        meta = row['meta']
        if (meta.get('thread_id') != original['meta']['thread_id']
                or mail._normalise_agent(meta.get('from')) != body['agent']
                or meta.get('sender_kind') != 'agent' or not meta.get('origin_session_id')
                or not _reply_chain(row, original, by_id, body['agent'])):
            continue
        receipt = mail._load_receipt_snapshot(root, meta['origin_session_id'], original['meta']['message_id'])
        if not discussion_review._receipt_matches(receipt, original, {'reviewer': body['agent']}, row):
            continue
        result = _result(row, original, body)
        if discussion_review._body(row, RESULT_SCHEMA) is not None and result is None:
            continue
        reply = {'from': body['agent'], 'body': result['reply'] if result else row['body'],
                 'at': meta['timestamp'], 'message_id': meta['message_id']}
        if result is not None:
            reply['result'] = result
        replies.append(reply)
    return replies


def read(root, path):
    root = Path(root).resolve()
    file = _file(root, path)
    rows = discussion_review._rows(root, 'human')
    comments = []
    for row in rows:
        body = comment(root, row)
        if body is None or body['path'] != file['path']:
            continue
        meta = row['meta']
        comments.append({
            'message_id': meta['message_id'], 'thread_id': meta['thread_id'],
            'anchor_id': body['anchor_id'], 'anchor_title': body['anchor_title'],
            'anchor_md': body['anchor_md'], 'start_line': body['start_line'], 'end_line': body['end_line'],
            'text': body['text'], 'source_sha256': body['source_sha256'], 'allow_edit': body['allow_edit'],
            'agent': body['agent'], 'at': meta['timestamp'], 'from': '@human', 'to': meta['to'],
            'images': _images(row, body),
            'received': discussion_review._received(root, row, {'reviewer': body['agent']}),
            'replies': _replies(root, rows, row, body),
        })
    return {'knowledge_base': str(root), 'path': file['path'], 'sha256': file['sha256'],
            'comments': comments, 'agents': discussion_review._reviewers(root, 'human')}


def send(root, payload, requester='human', session_id=''):
    root = Path(root).resolve()
    if not isinstance(payload, dict) or mail._normalise_agent(requester) != '@human':
        raise ValueError('Discussion comments must be sent by the human viewer')
    doc = document(root, payload.get('path'))
    if payload.get('expected_sha256') != doc['sha256']:
        raise ValueError('Discussion changed; reload before commenting')
    anchor = next((section for section in doc['sections'] if section['id'] == payload.get('anchor_id')), None)
    if anchor is None:
        raise ValueError('Choose a current discussion section')
    text, allow_edit = payload.get('text', ''), payload.get('allow_edit', False)
    if not isinstance(text, str) or len(text) > MAX_TEXT or '\x00' in text:
        raise ValueError('Comment text must be at most 20000 characters')
    if type(allow_edit) is not bool:
        raise ValueError('Choose whether the Agent may edit this section')
    agent = mail._normalise_agent(payload.get('agent'))
    if agent not in {peer['id'] for peer in discussion_review._reviewers(root, 'human')}:
        raise ValueError('Choose a registered Agent to receive the comment')
    decoded = _decode_images(payload.get('images', []))
    if not text.strip() and not decoded:
        raise ValueError('Provide comment text or an image')
    path = doc['path']
    lock = tasks._inside(root, '.oks/locks/goal-' + hashlib.sha256(path.encode()).hexdigest() + '.lock')
    with store._file_lock(lock):
        if _file(root, path)['sha256'] != doc['sha256']:
            raise ValueError('Discussion changed; reload before commenting')
        group, images = uuid.uuid4().hex, []
        for index, (name, mime, data) in enumerate(decoded):
            relative = f'mail/comment-images/{group}/{index}.{EXTENSIONS[mime]}'
            store._atomic_write(tasks._inside(root, relative), data)
            images.append({'name': name, 'mime': mime, 'path': relative})
        body = {
            'schema': SCHEMA, 'path': path, 'source_sha256': doc['sha256'],
            'snapshot_title': doc['title'], 'anchor_id': anchor['id'], 'anchor_title': anchor['title'],
            'anchor_md': anchor['markdown'], 'start_line': anchor['start_line'], 'end_line': anchor['end_line'],
            'text': text, 'agent': agent, 'images': images, 'allow_edit': allow_edit,
            'instructions': '这是用户对讨论原文锚点的留言。请先通过当前 Session 的 mail wait/read/ack 接收，'
                            '查看原文及所附图片；图片 path 相对当前知识库，可由宿主读图工具读取原图。'
                            'allow_edit=false 时仅回复；true 时只允许在精确 source_sha256 版本上修改 anchor_md '
                            '对应章节，其他文件、外发与知识入库权限仍由现有授权决定。'
                            'Mail 保存不表示已收到。请在原 Thread 用 result 回信，保留本留言 message_id 和原文版本。',
            'result_format': {'schema': RESULT_SCHEMA, 'comment_message_id': '<本邮件 message_id>',
                              'status': 'updated|answered|needs_info|failed', 'reply': '<处理说明>',
                              'changed': False, 'source_sha256': doc['sha256'], 'result_sha256': doc['sha256']},
        }
        mail.write_message(
            root, body=json.dumps(body, ensure_ascii=False), sender='human', sender_kind='human',
            recipients=[agent, '@human'], title=f'讨论留言 · {doc["title"]} · {anchor["title"]}',
            origin_session_id=session_id, record_kind='message', notify=True, evidence_refs=[],
        )
        return read(root, path)


def read_image(root, message_id, index):
    root = Path(root).resolve()
    row = _visible(root, message_id)
    body = comment(root, row)
    if body is None or type(index) is not int or index < 0 or index >= len(body['images']):
        raise FileNotFoundError('Comment image unavailable')
    image = body['images'][index]
    path = tasks._inside(root, image['path'])
    with path.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise FileNotFoundError('Comment image exceeds display limit')
    mime, _, _ = mail_media.image_info(data)
    if mime != image['mime']:
        raise FileNotFoundError('Comment image content changed')
    return data, mime
