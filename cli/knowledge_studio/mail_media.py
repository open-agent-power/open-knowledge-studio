"""Document-scoped raster images and a faithful read-only OCR presentation."""
from __future__ import annotations

import html
import re
import zlib
from pathlib import Path
from urllib.parse import unquote, urlencode

IMAGE = re.compile(r'(?<!\\)!\[([^\]]*)\]\((<[^>]+>|&lt;.*?&gt;|[^)\n]+?)(?:\s+(?:"[^"]*"|&quot;.*?&quot;))?\)')
LINK = re.compile(r'(?<![\\!])!?\[[^\]]*\]\((<[^>]+>|[^)\n]+?)(?:\s+"[^"]*")?\)')
RASTER = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
MAX_IMAGE_BYTES = 25 * 1024 * 1024


def prose_only(text: str) -> str:
    """Mask examples/comments without changing offsets used by the OCR view."""
    blank = lambda value: re.sub(r'[^\n]', ' ', value)
    result, fence = [], None
    text = re.sub(r'<!--[\s\S]*?(?:-->|$)', lambda match: blank(match.group()), text)
    for line in text.splitlines(keepends=True):
        # Conservatively mask fenced examples nested in quotes or list items.
        content = re.sub(r'^(?: {0,3}>[ \t]?)+', '', line)
        content = re.sub(r'^ {0,3}(?:[-+*]|\d+[.)])\s+', '', content)
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', content)
        if fence:
            result.append(blank(line))
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*', content):
                fence = None
        elif marker:
            fence = (marker.group(1)[0], len(marker.group(1)))
            result.append(blank(line))
        elif line.startswith(('    ', '\t')):
            result.append(blank(line))
        else:
            result.append(line)
    return re.sub(r'(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)', lambda match: blank(match.group()), ''.join(result))


def document_path(root: Path, relative: str) -> Path:
    from .studio import _path

    path = _path(root, relative)
    if path.suffix.lower() != '.md' or not path.is_file():
        raise FileNotFoundError('Knowledge document unavailable')
    return path


def resolve_image(root: Path, document: Path, target: str) -> Path:
    from .studio import READ_ROOTS

    root = root.resolve()
    value = unquote(html.unescape(target.strip().strip('<>'))).replace('\\', '/')
    if (not value or value.startswith('//') or '\x00' in value
            or (re.match(r'^[a-z][\w+.-]*:', value, re.I)
                and not re.match(r'^[a-z]:/', value, re.I))):
        raise FileNotFoundError('Image unavailable')
    path = Path(value)
    if not path.is_absolute():
        path = (root if value.split('/')[0] in READ_ROOTS else document.parent) / path
    path = path.resolve()
    relative = path.relative_to(root) if path.is_relative_to(root) else None
    if (relative is None or not relative.parts or relative.parts[0] not in READ_ROOTS
            or any(part.startswith('.') for part in relative.parts)
            or path.suffix.lower() not in RASTER or not path.is_file()
            or path.stat().st_size > MAX_IMAGE_BYTES):
        raise FileNotFoundError('Image unavailable')
    return path


def referenced_images(root: Path, document: Path) -> set[Path]:
    text = document.read_text(encoding='utf-8')
    if text.startswith('---\n') or text.startswith('---\r\n'):
        parts = re.split(r'^---[ \t]*\r?$', text, maxsplit=2, flags=re.M)
        text = parts[2] if len(parts) == 3 else ''
    result = set()
    for link in LINK.finditer(prose_only(text)):
        try:
            result.add(resolve_image(root, document, link.group(1)))
        except (OSError, ValueError):
            pass
    return result


def image_info(header: bytes) -> tuple[str, int, int]:
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, image_data, first = 8, False, True
        while offset + 12 <= len(header):
            size = int.from_bytes(header[offset:offset + 4], 'big')
            end = offset + 12 + size
            kind, payload = header[offset + 4:offset + 8], header[offset + 8:offset + 8 + size]
            if end > len(header) or zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(header[end - 4:end], 'big'):
                break
            if first:
                if kind != b'IHDR' or size != 13 or not all(int.from_bytes(payload[i:i + 4], 'big') for i in (0, 4)):
                    break
                width, height = int.from_bytes(payload[:4], 'big'), int.from_bytes(payload[4:8], 'big')
                if width > 30000 or height > 30000 or width * height > 40_000_000:
                    break
                first = False
            image_data |= kind == b'IDAT' and size > 0
            if kind == b'IEND':
                if not size and end == len(header) and image_data:
                    return 'image/png', width, height
                break
            offset = end
        raise FileNotFoundError('Invalid PNG structure')
    if header.startswith(b'\xff\xd8\xff'):
        offset, frame = 2, False
        while offset + 4 <= len(header) and header[offset] == 255:
            marker = header[offset + 1]
            size = int.from_bytes(header[offset + 2:offset + 4], 'big')
            if size < 2 or offset + 2 + size > len(header):
                break
            if marker in {0xc0, 0xc1, 0xc2} and size >= 8:
                height = int.from_bytes(header[offset + 5:offset + 7], 'big')
                width = int.from_bytes(header[offset + 7:offset + 9], 'big')
                frame = 0 < width <= 30000 and 0 < height <= 30000 and width * height <= 40_000_000
            if marker == 0xda:
                if frame and header.find(b'\xff\xd9', offset + 2 + size) >= 0:
                    return 'image/jpeg', width, height
                break
            offset += 2 + size
        raise FileNotFoundError('Invalid JPEG structure')
    if header.startswith((b'GIF87a', b'GIF89a')) and len(header) > 14 and header.endswith(b';') and b',' in header[13:]:
        return 'image/gif', int.from_bytes(header[6:8], 'little'), int.from_bytes(header[8:10], 'little')
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP' and header[12:16] in {b'VP8 ', b'VP8L', b'VP8X'} and int.from_bytes(header[4:8], 'little') + 8 == len(header):
        return 'image/webp', 0, 0
    if header.startswith(b'BM') and len(header) > 54 and int.from_bytes(header[2:6], 'little') == len(header) and 14 <= int.from_bytes(header[10:14], 'little') < len(header):
        return 'image/bmp', 0, 0
    raise FileNotFoundError('Unsupported image content')


def read_image(root: Path, relative: str, asset: str) -> tuple[bytes, str]:
    """Only expose raster assets explicitly linked by the requested document."""
    document = document_path(root, relative)
    if document.stat().st_size > 4_000_000:
        raise FileNotFoundError('Knowledge document exceeds image lookup limit')
    candidate = resolve_image(root, document, asset)
    if candidate not in referenced_images(root, document):
        raise FileNotFoundError('Image is not referenced by this document')
    with candidate.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise FileNotFoundError('Image exceeds display limit')
    return data, image_info(data)[0]


def image_markup(root: Path, relative: str, target: str, label: str = '') -> str:
    name = target.replace('\\', '/').rsplit('/', 1)[-1].strip('<>')
    try:
        document = document_path(root, relative)
        image = resolve_image(root, document, target)
        if image not in referenced_images(root, document):
            raise FileNotFoundError('Image is not referenced by this document')
        with image.open('rb') as stream:
            header = stream.read(MAX_IMAGE_BYTES + 1)
            if len(header) > MAX_IMAGE_BYTES:
                raise FileNotFoundError('Image exceeds display limit')
            _mime, width, height = image_info(header)
        dimensions = f' width="{width}" height="{height}"' if 0 < width <= 30000 and 0 < height <= 30000 else ''
        url = '/api/mail/knowledge-image?' + urlencode({'path': relative, 'asset': image.relative_to(root.resolve()).as_posix()})
    except (OSError, ValueError):
        return '<span class="image-unavailable" role="note">原图不可用 · ' + html.escape(name) + '（缺失、格式不支持或不在知识库内）</span>'
    safe_url = html.escape(url, quote=True)
    return (f'<span class="knowledge-image"><a href="{safe_url}" target="_blank" rel="noopener noreferrer" aria-label="打开原图">'
            f'<img src="{safe_url}" alt="{html.escape(label or name, quote=True)}"{dimensions} loading="lazy" decoding="async"></a>'
            f'<span class="image-caption">原图 · {html.escape(name)} · 点击放大</span></span>')


def render_body(root: Path, relative: str, meta: dict, body: str, render) -> str:
    images = lambda target, label='': image_markup(root, relative, target, label)
    markdown = lambda text: render(text, image_renderer=images)
    if meta.get('source_type') != 'local-ocr-import':
        return markdown(body)
    headings = list(re.finditer(r'^##\s+(.+\.(?:png|jpe?g|gif|webp|bmp))\s*$', prose_only(body), re.M | re.I))
    if not headings:
        return markdown(body)
    out = [markdown(body[:headings[0].start()])]
    for index, heading in enumerate(headings):
        section = body[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(body)].strip()
        original = re.search(r'^原图：\s*\[[^\]]*\]\((<[^>]+>|[^)\n]+)\)[。.]?\s*$', prose_only(section), re.M)
        if not original:
            out.append(markdown(body[heading.start():heading.end()] + '\n\n' + section))
            continue
        linked = re.search(r'^关联笔记：\s*(.+?)。?\s*$', section, re.M)
        title = f'配图 {index + 1}' + (' · ' + linked.group(1).rstrip('。') if linked else '')
        picture = images(original.group(1), title)
        transcript = (section[:original.start()] + section[original.end():]).strip()
        opened = ' open' if 'image-unavailable' in picture else ''
        out.append(f'<section class="ocr-section"><h3>{html.escape(title)}</h3>{picture}'
                   f'<details class="ocr-transcript"{opened}><summary>查看 OCR 识别原文 · 未校对</summary>'
                   f'<p>保留机器识别的原始行序与字符，代码和结论请核对原图。</p><pre>{html.escape(transcript)}</pre></details></section>')
    return '\n'.join(out)
