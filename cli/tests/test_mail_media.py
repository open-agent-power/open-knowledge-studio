import struct
import threading
import zlib
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from knowledge_studio import mail_media
from knowledge_studio.mail_web import _memory_item, create_server


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    + _png_chunk(b"IEND", b"")
)


@pytest.fixture
def kb(tmp_path):
    for name in ("wiki", "drafts", "raw", "mail"):
        (tmp_path / name).mkdir()
    (tmp_path / "raw" / "screen shot.png").write_bytes(PNG)
    return tmp_path


def write_note(kb, body, frontmatter=""):
    (kb / "wiki" / "a.md").write_text(
        "---\ntitle: Image note\narea: computing\n" + frontmatter + "---\n\n" + body,
        encoding="utf-8",
    )


def serve(kb):
    server = create_server(kb, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_markdown_image_is_rendered_only_from_a_document_reference(kb):
    write_note(kb, "![原图](../raw/screen%20shot.png)\n\n`![示例](../raw/screen%20shot.png)`")
    item = _memory_item(kb, "wiki/a.md")
    assert item["body_html"].count("<img ") == 1
    assert "/api/mail/knowledge-image?" in item["body_html"]
    assert "<code>![示例](../raw/screen%20shot.png)</code>" in item["body_html"]


def test_image_endpoint_is_read_only_and_rejects_unreferenced_assets(kb):
    write_note(kb, "![原图](../raw/screen%20shot.png)")
    server, thread, base = serve(kb)
    try:
        route = "/api/mail/knowledge-image?" + urlencode({"path": "wiki/a.md", "asset": "raw/screen shot.png"})
        with urlopen(base + route, timeout=5) as response:
            assert response.read() == PNG
            assert response.headers["Content-Type"] == "image/png"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "sandbox" in response.headers["Content-Security-Policy"]
        for document, asset in (("wiki/a.md", "raw/other.png"), ("raw/a.md", "raw/screen shot.png"), ("wiki/a.md", "../outside.png")):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/mail/knowledge-image?" + urlencode({"path": document, "asset": asset}), timeout=5)
            assert error.value.code == 404
    finally:
        stop(server, thread)


def test_ocr_sections_keep_a_readable_transcript_when_the_image_is_missing(kb):
    write_note(
        kb,
        "## external-assets/missing.png\n\n原图：[x](../raw/missing.png)。\n\n<script>alert(1)</script>\n书 写 语 法",
        "source_type: local-ocr-import\n",
    )
    markup = _memory_item(kb, "wiki/a.md")["body_html"]
    assert '<details class="ocr-transcript" open>' in markup
    assert "原图不可用" in markup
    assert "&lt;script&gt;" in markup and "<script>" not in markup
    assert "书 写 语 法" in markup


def test_examples_and_comments_cannot_authorize_images(kb):
    for wrapper in ("`{}`", "```md\n{}\n```", "<!-- {} -->", "~~~md\n{}\n~~~"):
        write_note(kb, wrapper.format("![原图](../raw/screen%20shot.png)"))
        with pytest.raises(FileNotFoundError):
            mail_media.read_image(kb, "wiki/a.md", "raw/screen shot.png")


def test_invalid_magic_prefix_is_not_served(kb):
    (kb / "raw" / "fake.png").write_bytes(b"\x89PNG\r\n\x1a\n<script>alert(1)</script>")
    write_note(kb, "![原图](../raw/fake.png)")
    assert "原图不可用" in _memory_item(kb, "wiki/a.md")["body_html"]
    with pytest.raises(FileNotFoundError):
        mail_media.read_image(kb, "wiki/a.md", "raw/fake.png")


@pytest.mark.parametrize("example", [
    "`{image}`", "``{image}``", "``example ` {image}\ncontinued``",
    "```md\n{image}\n```", "~~~md\n{image}\n~~~",
    "````md\n```\n{image}\n````", "    {image}", "\t{image}",
    "<!-- {image} -->", "<!--\n{image}\n-->", "<!-- {image}",
    "> ~~~md\n> {image}\n> ~~~", "- ```md\n  {image}\n  ```",
    "\\{image}",
])
def test_examples_neither_render_nor_authorize_images(kb, example):
    image = "![example](../raw/screen%20shot.png)"
    example = example.format(image=image)
    write_note(kb, example)
    with pytest.raises(FileNotFoundError):
        mail_media.read_image(kb, "wiki/a.md", "raw/screen shot.png")
    assert "<img " not in _memory_item(kb, "wiki/a.md")["body_html"]
    # A legitimate reference elsewhere must not activate an example image.
    write_note(kb, image + "\n\n" + example)
    assert _memory_item(kb, "wiki/a.md")["body_html"].count("<img ") == 1


def test_reference_scope_and_path_boundaries(kb, tmp_path):
    outside = kb.parent / (kb.name + "-outside.png")
    outside.write_bytes(PNG)
    (kb / "raw" / "other.png").write_bytes(PNG)
    (kb / "raw" / "private.md").write_text("![x](screen%20shot.png)", encoding="utf-8")
    write_note(kb, "![x](../raw/screen%20shot.png)")
    assert mail_media.read_image(kb, "raw/private.md", "raw/screen shot.png")[0] == PNG
    for document, asset in [
        ("wiki/a.md", "raw/other.png"),
        ("../wiki/a.md", "raw/screen shot.png"),
        (str(kb / "wiki" / "a.md"), "raw/screen shot.png"),
        ("wiki/a.md", str(outside)),
        ("wiki/a.md", "../" + outside.name),
        ("wiki/a.md", "%2e%2e/" + outside.name),
        ("wiki/a.md", "..\\" + outside.name),
    ]:
        with pytest.raises((OSError, ValueError)):
            mail_media.read_image(kb, document, asset)
    for target in [str(outside), "https://example.invalid/a.png", "//server/share/a.png", "data:image/png;base64,abc"]:
        write_note(kb, f"![x]({target})")
        with pytest.raises((OSError, ValueError)):
            mail_media.read_image(kb, "wiki/a.md", target)


def test_symlink_cannot_escape_image_or_document_scope(kb):
    outside = kb.parent / (kb.name + "-external")
    outside.mkdir()
    (outside / "outside.png").write_bytes(PNG)
    (outside / "note.md").write_text("![x](../raw/screen%20shot.png)", encoding="utf-8")
    try:
        (kb / "raw" / "linked.png").symlink_to(outside / "outside.png")
        (kb / "wiki" / "linked.md").symlink_to(outside / "note.md")
    except OSError as error:
        pytest.skip(f"Symlinks unavailable: {error}")
    write_note(kb, "![x](../raw/linked.png)")
    for document, asset in [("wiki/a.md", "raw/linked.png"), ("wiki/linked.md", "raw/screen shot.png")]:
        with pytest.raises((OSError, ValueError)):
            mail_media.read_image(kb, document, asset)


@pytest.mark.parametrize("prefix", ["", "--- "])
def test_frontmatter_does_not_authorize_an_image(kb, prefix):
    write_note(kb, "No image reference.", f'preview: "{prefix}![x](../raw/screen%20shot.png)"\n')
    with pytest.raises(FileNotFoundError):
        mail_media.read_image(kb, "wiki/a.md", "raw/screen shot.png")


def test_image_size_limit_fails_closed(kb, monkeypatch):
    write_note(kb, "![x](../raw/screen%20shot.png)")
    monkeypatch.setattr(mail_media, "MAX_IMAGE_BYTES", len(PNG) - 1)
    assert "原图不可用" in _memory_item(kb, "wiki/a.md")["body_html"]
    with pytest.raises(FileNotFoundError):
        mail_media.read_image(kb, "wiki/a.md", "raw/screen shot.png")


def test_http_image_requests_preserve_files_and_reject_writes_and_foreign_host(kb):
    write_note(kb, "![x](../raw/screen%20shot.png)")
    server, thread, base = serve(kb)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in kb.rglob("*") if p.is_file()}
    route = "/api/mail/knowledge-image?" + urlencode({"path": "wiki/a.md", "asset": "raw/screen shot.png"})
    try:
        with urlopen(base + route, timeout=5) as response:
            assert response.read() == PNG
            assert response.headers["Cache-Control"] == "no-store"
        for request, status in [
            (Request(base + route, headers={"Host": "evil.invalid"}), 403),
            (Request(base + route, data=b"{}", headers={"Content-Type": "application/json"}), 404),
        ]:
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=5)
            assert error.value.code == status
        assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in kb.rglob("*") if p.is_file()}
    finally:
        stop(server, thread)


@pytest.mark.parametrize("opening,inner,closing", [
    ("~~~markdown", "```", "~~~"),
    ("````markdown", "```", "````"),
    ("~~~~markdown", "~~~", "~~~~~"),
])
def test_reader_preserves_fenced_examples_without_authorizing_their_images(kb, opening, inner, closing):
    code = f"## Example\n{inner}\n![example](../raw/screen%20shot.png)\n<script>inert</script>"
    body = f"{opening}\n{code}\n{closing}\n\nAfter the example."
    write_note(kb, body)
    before = (kb / "wiki/a.md").read_bytes()
    markup = _memory_item(kb, "wiki/a.md")["body_html"]
    assert markup.count("<pre><code>") == 1
    assert f"<pre><code>{code.replace('<', '&lt;').replace('>', '&gt;')}</code></pre>" in markup
    assert "<p>After the example.</p>" in markup
    assert "<img " not in markup and "<script>" not in markup
    with pytest.raises(FileNotFoundError):
        mail_media.read_image(kb, "wiki/a.md", "raw/screen shot.png")
    assert (kb / "wiki/a.md").read_bytes() == before


@pytest.mark.parametrize("relative", ["../raw/screen shot.png", "raw/screen%20shot.png", "absolute"])
def test_legacy_ocr_images_preserve_paths_transcript_and_fenced_headings(kb, relative):
    target = (kb / "raw/screen shot.png").as_posix() if relative == "absolute" else relative
    example = "## example.png\n原图：[example](../raw/screen%20shot.png)。"
    body = (f"```markdown\n{example}\n```\n\n"
            f"## external-assets/screen shot.png\n\n原图：[screen shot](<{target}>)。\n\n"
            "书 写 语 法\nif(count\nalert(count);\n\n关联笔记：JavaScript。")
    write_note(kb, body, "source_type: local-ocr-import\nocr_review_status: unreviewed\n")
    item = _memory_item(kb, "wiki/a.md")
    markup = item["body_html"]
    assert markup.count('class="ocr-section"') == markup.count("<img ") == 1
    assert f"<pre><code>{example}</code></pre>" in markup
    assert "配图 1 · JavaScript" in markup
    assert "书 写 语 法\nif(count\nalert(count);" in markup
    assert item["body"].strip() == body


def test_jpeg_application_trailer_is_preserved_after_end_marker(kb):
    frame = b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
    scan = b'\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x01\xff\xd9'
    jpeg = b'\xff\xd8' + frame + scan + b'application trailer'
    (kb / "raw/photo.jpg").write_bytes(jpeg)
    write_note(kb, "![photo](../raw/photo.jpg)")
    data, mime = mail_media.read_image(kb, "wiki/a.md", "raw/photo.jpg")
    assert mime == "image/jpeg" and data == jpeg
