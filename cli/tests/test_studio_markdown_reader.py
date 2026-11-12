"""The graph reader renders retained Markdown and document-scoped local images."""
import html
import json
import re
import struct
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
import zlib

import pytest

from knowledge_studio import studio
from knowledge_studio.mail_web import create_server


def png_chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


PNG = (b'\x89PNG\r\n\x1a\n'
       + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + png_chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff'))
       + png_chunk(b'IEND', b''))


@pytest.fixture
def reader(tmp_path):
    root = tmp_path / 'kb'
    for bucket in studio.READ_ROOTS:
        (root / bucket).mkdir(parents=True, exist_ok=True)
    server = create_server(root, 0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield root, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def get_document(base, path, endpoint='file'):
    with urlopen(base + '/api/studio/' + endpoint + '?' + urlencode({'path': path}), timeout=5) as response:
        return json.load(response)


def test_studio_markdown_reader_preserves_source_and_renders_images_in_readable_buckets(reader):
    root, base = reader
    for bucket in studio.READ_ROOTS:
        source = ('---\ntitle: 图文笔记\n---\n# 原始标题\n\n'
                  '**重点**与 `代码`\n\n- [ ] 待完成\n- [x] 已完成\n\n'
                  '| 项目 | 内容 |\n| --- | --- |\n| 图示 | 原文 |\n\n'
                  '```md\n![示例](other.png)\n```\n\n'
                  '![本地配图](<diagram image.png> "图示")\n\n<script>inert</script>')
        note = root / bucket / 'note.md'
        note.write_text(source, encoding='utf-8', newline='\n')
        image = note.with_name('diagram image.png')
        image.write_bytes(PNG)
        before = (note.read_bytes(), note.stat().st_mtime_ns, image.read_bytes(), image.stat().st_mtime_ns)
        document = get_document(base, f'{bucket}/note.md')
        assert document['path'] == f'{bucket}/note.md'
        assert document['text'] == source and document['format'] == 'markdown'
        assert document['title'] in {'图文笔记', '原始标题'} and isinstance(document['outline'], list)
        assert len(document['sha256']) == 64 and document['body'].startswith('# 原始标题')
        markup = document['body_html']
        assert '<h2>原始标题</h2>' in markup and '<strong>重点</strong>' in markup
        assert '<table>' in markup and '<code>代码</code>' in markup
        assert '<input type="checkbox" disabled>' in markup
        assert '<input type="checkbox" disabled checked>' in markup
        assert '<pre><code>![示例](other.png)</code></pre>' in markup
        assert '<script>' not in markup and '&lt;script&gt;inert&lt;/script&gt;' in markup
        assert markup.count('<img ') == 1 and 'class="knowledge-image"' in markup
        image_url = html.unescape(re.search(r'<img src="([^"]+)"', markup)[1])
        with urlopen(base + image_url, timeout=5) as response:
            assert response.read() == PNG and response.headers['Content-Type'] == 'image/png'
        assert before == (note.read_bytes(), note.stat().st_mtime_ns, image.read_bytes(), image.stat().st_mtime_ns)


def test_studio_reader_rejects_hidden_outside_unreferenced_and_non_image_assets(reader):
    root, base = reader
    (root / 'profiles' / '.hidden').mkdir()
    (root / 'settings').mkdir()
    for path in ['profiles/.hidden/figure.png', 'profiles/.private.png', 'profiles/other.png', 'settings/figure.png']:
        (root / path).write_bytes(PNG)
    (root / 'profiles/fake.png').write_text('<script>not an image</script>', encoding='utf-8')
    (root / 'profiles/vector.svg').write_text('<svg/>', encoding='utf-8')
    (root.parent / 'outside.png').write_bytes(PNG)
    (root / 'profiles/.hidden/note.md').write_text('![x](figure.png)', encoding='utf-8')
    body = ('![hidden](.hidden/figure.png)\n![hidden](.private.png)\n'
            '![outside](../../outside.png)\n![settings](../settings/figure.png)\n'
            '![fake](fake.png)\n![svg](vector.svg)\n'
            '![remote](https://example.invalid/figure.png)\n'
            '`![example](other.png)`\n<!-- ![comment](other.png) -->')
    (root / 'profiles/note.md').write_text(body, encoding='utf-8')
    document = get_document(base, 'profiles/note.md')
    assert '<img ' not in document['body_html'] and '原图不可用' in document['body_html']
    for path in ['profiles/.hidden/note.md', 'profiles/../profiles/note.md', '../outside.md', 'settings/a.md']:
        with pytest.raises(HTTPError) as error:
            get_document(base, path)
        assert error.value.code == 400
    for path, asset in [
        ('profiles/note.md', 'profiles/.hidden/figure.png'),
        ('profiles/note.md', 'profiles/.private.png'),
        ('profiles/note.md', '../outside.png'),
        ('profiles/note.md', 'settings/figure.png'),
        ('profiles/note.md', 'profiles/other.png'),
        ('profiles/note.md', 'profiles/fake.png'),
        ('profiles/note.md', 'profiles/vector.svg'),
        ('profiles/.hidden/note.md', 'profiles/.hidden/figure.png'),
    ]:
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/api/mail/knowledge-image?' + urlencode({'path': path, 'asset': asset}), timeout=5)
        assert error.value.code == 404


@pytest.mark.parametrize('endpoint', ['file', 'draft-reader'])
def test_raw_text_reader_preserves_complete_plain_text_without_markdown_interpretation(reader, endpoint):
    root, base = reader
    text = '---\n[invalid: yaml\n---\n# Literal heading\n\n<script>inert</script>\n'
    text += '![not an image](figure.png)\n[[wiki/missing]]\n' + '完整原文\n' * 3500 + 'END-OF-SOURCE'
    source = root / 'raw/source.txt'
    source.write_text(text, encoding='utf-8', newline='\n')
    before = source.read_bytes(), source.stat().st_mtime_ns
    document = get_document(base, 'raw/source.txt', endpoint)
    assert document['format'] == 'text' and document['kind'] == 'raw'
    assert document['text'] == document['body'] == text
    assert document['body_html'] == '<pre>' + html.escape(text) + '</pre>'
    assert document['outline'] == [] and '<img ' not in document['body_html']
    if endpoint == 'draft-reader':
        assert document['sources'] == [] and document['steps'] == []
    assert before == (source.read_bytes(), source.stat().st_mtime_ns)


@pytest.mark.parametrize('suffix', ['md', 'txt'])
def test_raw_bundle_reader_uses_actual_content_path_and_format(reader, suffix):
    root, base = reader
    bundle = root / 'raw/bundle'
    (bundle / 'pages').mkdir(parents=True)
    (bundle / 'raw.md').write_text('# Bundle metadata\n', encoding='utf-8')
    source = '# 原始正文\n\n![页面配图](figure.png)\n\n完整结尾'
    (bundle / 'pages' / f'content.{suffix}').write_text(source, encoding='utf-8', newline='\n')
    (bundle / 'pages/figure.png').write_bytes(PNG)
    (bundle / 'bundle.json').write_text(json.dumps({
        'files': {'content': f'pages/content.{suffix}'}, 'processing_status': 'partial', 'sources': []}), encoding='utf-8')
    document = get_document(base, 'raw/bundle/raw.md', 'draft-reader')
    assert document['path'] == 'raw/bundle/raw.md'
    assert document['body_path'] == f'raw/bundle/pages/content.{suffix}'
    assert document['processing_status'] == 'partial'
    assert document['text'] == document['body'] == source
    if suffix == 'txt':
        assert document['format'] == 'text'
        assert document['body_html'] == '<pre>' + html.escape(source) + '</pre>'
    else:
        assert document['format'] == 'markdown' and '<h2>原始正文</h2>' in document['body_html']
        image_url = html.unescape(re.search(r'<img src="([^"]+)"', document['body_html'])[1])
        assert 'content.md' in image_url
        with urlopen(base + image_url, timeout=5) as response:
            assert response.read() == PNG
