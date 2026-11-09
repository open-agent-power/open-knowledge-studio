"""Additive read contracts used by the approved Studio UI."""
from knowledge_studio import mail
from knowledge_studio.mail_knowledge import knowledge_map, _internal_links
from knowledge_studio.mail_observation import overview_data
from knowledge_studio.mail_web import _memory_item


def test_collaboration_filter_searches_past_ordinary_history(tmp_path):
    handoff = mail.write_message(tmp_path, sender="builder", recipients="human", body="明确交接", record_kind="handoff", title="协作")
    for i in range(55):
        mail.write_message(tmp_path, sender="human", recipients="builder", body=f"普通 {i}", title="历史")
    data = overview_data(tmp_path, filter_kind="collaboration", limit=1)
    assert data["counts"]["threads"] == 56
    assert data["counts"]["matched"] == 1
    assert data["items"][0]["thread_id"] == handoff["thread_id"]
    assert data["items"][0]["record_kinds"] == ["handoff"]
    assert data["items"][0]["latest"]["title"] == "协作"


def test_knowledge_keeps_tag_edges_separate_from_written_links(tmp_path):
    wiki=tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text('---\ntitle: A\ntags: [Java, same, extra]\nrelations:\n  - type: supports\n    target: b\n---\n\n[[B]]\n[read](c.md)\n`[[Missing]]`\n', encoding="utf-8")
    (wiki / "b.md").write_text('---\ntitle: B\ntags: [Java, same, extra]\n---\nB', encoding="utf-8")
    (wiki / "c.md").write_text('---\ntitle: C\ntags: [Java, same, extra]\n---\nC', encoding="utf-8")
    before={p:p.read_bytes() for p in wiki.iterdir()}
    data=knowledge_map(tmp_path)
    assert len(data["edges"]) > len(data["explicit_edges"])
    assert len(data["explicit_edges"]) == 1
    assert data["explicit_edges"][0]["type"] == "supports"
    assert {(link["a"],link["b"]) for link in data["internal_links"]} == {("wiki/a.md","wiki/b.md"),("wiki/a.md","wiki/c.md")}
    assert knowledge_map(tmp_path, limit=1)["internal_links"] == []
    assert before == {p:p.read_bytes() for p in wiki.iterdir()}


def test_internal_links_reject_examples_external_paths_and_ambiguous_names():
    points=[{"id":"wiki/a.md","title":"A"},{"id":"wiki/b.md","title":"B"},{"id":"drafts/b.md","title":"B"}]
    body='[[B]]\n[[wiki/b]]\n<!-- [[drafts/b]] -->\n```md\n[[drafts/b]]\n````\n`[[drafts/b]]`\n[external](https://example.org/wiki/b.md)\n[escape](../../outside.md)\n![image](drafts/b.md)\n[[http://[invalid]]]\n    [[drafts/b]]\n~~~md\n[[drafts/b]]\n'
    links=_internal_links(points,{"wiki/a.md":body})
    assert [(l["a"],l["b"]) for l in links] == [("wiki/a.md","wiki/b.md")]


def test_full_document_preserves_original_markdown_and_safe_html(tmp_path):
    wiki=tmp_path / "wiki"
    wiki.mkdir()
    source='---\ntitle: 原文\ntags: [Java, 自定义]\n---\n\n# 正文\n\n<script>alert(1)</script>\n\n'+'长正文\n'*4000+'END-MARKER\n'
    file=wiki / "long.md"
    file.write_text(source,encoding="utf-8")
    assert _memory_item(tmp_path,"wiki/long.md")["truncated"]
    doc=_memory_item(tmp_path,"wiki/long.md",full=True)
    assert doc["markdown"] == source
    assert 'END-MARKER' in doc["body_html"]
    assert '<script>' not in doc["body_html"]
    assert doc["metadata"]["tags"] == ['Java','自定义']
    assert file.read_text(encoding="utf-8") == source


def test_studio_file_returns_safe_markdown_body_without_frontmatter(tmp_path):
    import json
    from threading import Thread
    from urllib.request import urlopen
    from knowledge_studio.mail_web import create_server

    target = tmp_path / "skill" / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    (tmp_path / "wiki").mkdir()
    (tmp_path / "mail").mkdir()
    original = '---\ntitle: Skill\n---\n# Skill\n\n**正文** <script>alert(1)</script>\n'
    target.write_bytes(original.encode("utf-8"))
    server = create_server(tmp_path, 0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/studio/file?path=skill%2Fdemo%2FSKILL.md') as response:
            result = json.load(response)
        assert result['text'] == original
        assert 'title: Skill' not in result['body_html']
        assert '<strong>正文</strong>' in result['body_html']
        assert '<script>' not in result['body_html']
        assert '&lt;script&gt;' in result['body_html']
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
