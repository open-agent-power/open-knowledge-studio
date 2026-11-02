"""Reader-mode HTTP contracts: observation must never become a business write."""
import json
import io
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from types import SimpleNamespace

import pytest

from knowledge_studio import mail, team_sync
from knowledge_studio.mail_web import Handler, create_server, md_to_html


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "reader-kb"
    (root / "mail").mkdir(parents=True)
    (root / "wiki").mkdir()
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_MACHINE_ID", "reader-test")
    return root


@contextmanager
def serving(root, **kwargs):
    server = create_server(root, 0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_json(base, route):
    with urlopen(base + route, timeout=5) as response:
        return json.load(response)


def filesystem_snapshot(root):
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize('headers,path,status', [
    ({'Host': 'untrusted.example'}, '/api/mail/send', 403),
    ({'Origin': 'https://untrusted.example'}, '/api/mail/send', 403),
    ({'Content-Type': 'text/plain'}, '/api/mail/send', 403),
    ({}, '/api/mail/removed', 404),
    ({}, '/api/mail/send', 403),
])
def test_rejections_consume_bounded_body_before_reply(headers, path, status):
    """Unread TCP input can discard the rejection on Windows when closing."""
    handler = object.__new__(Handler)
    body = b'{"push":true}'
    handler.server = SimpleNamespace(server_port=3182, mode='reader')
    handler.headers = {'Host': '127.0.0.1:3182', 'Content-Type': 'application/json',
                       'Content-Length': str(len(body)), **headers}
    handler.path = path
    handler.connection = SimpleNamespace(settimeout=lambda timeout: None)
    handler.rfile = io.BytesIO(body)
    replies = []

    def reply(code, payload):
        assert handler.rfile.tell() == len(body), 'unread body can reset the response socket'
        replies.append((code, payload))

    handler.send_json = reply
    handler.read_json = lambda: pytest.fail('Rejected bodies must not execute business parsing')
    handler.do_POST()
    assert replies[0][0] == status
    assert 'error' in replies[0][1]


@pytest.mark.parametrize('length', ['65537', '-1', 'invalid'])
def test_rejection_does_not_drain_unbounded_or_invalid_body(length):
    handler = object.__new__(Handler)
    handler.headers = {'Content-Length': length}
    handler.connection = SimpleNamespace(settimeout=lambda timeout: None)
    handler.rfile = SimpleNamespace(read=lambda *args: pytest.fail('Do not read an unbounded body'))
    replies = []
    handler.send_json = lambda code, payload: replies.append((code, payload))
    handler._reject_post(403, 'denied')
    assert replies == [(403, {'error': 'denied'})]


@pytest.mark.parametrize('headers', [{'Origin': 'https://untrusted.example'},
                                    {'Content-Type': 'text/plain'}, {'Host': 'untrusted.example'}])
def test_invalid_http_requests_return_json_without_business_writes(kb, headers):
    before = filesystem_snapshot(kb)
    with serving(kb) as (base, _):
        request = Request(base + '/api/mail/send', data=b'x' * 8192,
                          headers={'Content-Type': 'application/json', **headers})
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=5)
        with error.value as response:
            assert response.code == 403
            assert json.load(response)['error'] == 'same-origin JSON requests required'
    assert filesystem_snapshot(kb) == before




def test_reader_start_gets_and_legacy_writes_leave_kb_unchanged(kb, monkeypatch):
    message = mail.write_message(kb, sender="writer", recipients="human",
                                 body="## Evidence\n\nRead me.", record_kind="handoff")
    (kb / "wiki" / "evidence.md").write_text("---\ntitle: Evidence\n---\nBody", encoding="utf-8")
    before = filesystem_snapshot(kb)

    def forbid_sync(*args, **kwargs):
        pytest.fail("Reader must never invoke Git sync")

    monkeypatch.setattr(team_sync, "sync", forbid_sync)
    with serving(kb) as (base, server):
        assert server.session_id is None
        capabilities = get_json(base, "/api/mail/capabilities")
        assert capabilities["read_only"] is True
        assert capabilities["mode"] == "reader"
        assert capabilities["viewer"] == "@human"
        for route in (
            "/", "/app.js", "/style.css", "/layout.css",
            "/api/mail/overview", "/api/mail/snapshot", "/api/mail/status",
            "/api/mail/activity", "/api/mail/timeline", "/api/mail/knowledge-map",
            "/api/mail/members", "/api/mail/memory", "/api/connection-guide",
            "/api/mail/thread?id=" + message["thread_id"],
            "/api/mail/wiki-page?path=wiki/evidence.md",
        ):
            with urlopen(base + route, timeout=5) as response:
                assert response.status == 200, route
        for route in ("send", "reply", "invite", "read", "archive", "unarchive", "team/sync"):
            request = Request(base + "/api/mail/" + route, data=b'{"push":true}',
                              headers={"Content-Type": "application/json"})
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=5)
            assert error.value.code == 403
            assert json.load(error.value)["mode"] == "reader"
    assert filesystem_snapshot(kb) == before


def test_collaboration_mode_explicitly_preserves_legacy_send(kb):
    with serving(kb, mode="collaboration") as (base, server):
        assert server.session_id
        assert get_json(base, "/api/mail/capabilities")["read_only"] is False
        request = Request(base + "/api/mail/send",
                          data=json.dumps({"to": "reviewer", "title": "Review", "body": "Please review"}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
            assert response.status == 201
        assert mail.thread_messages(kb, result["thread_id"], "reviewer")


def test_invalid_mode_fails_before_registering_session(kb):
    before = filesystem_snapshot(kb)
    with pytest.raises(ValueError, match="mode"):
        create_server(kb, 0, mode="unknown")
    assert filesystem_snapshot(kb) == before


def test_reader_projections_do_not_disclose_private_agents_or_threads(kb):
    mail.register_session(kb, "private-session", "secret-agent", scope="private-project")
    hidden = mail.write_message(kb, sender="secret-agent", recipients="private-peer",
                                body="private-body-marker", title="private-title-marker",
                                origin_session_id="private-session", record_kind="handoff")
    visible = mail.write_message(kb, sender="writer", recipients="human",
                                 body="Visible", title="Shared review")
    with serving(kb) as (base, _):
        for route in ("/api/mail/overview", "/api/mail/status",
                      "/api/mail/overview?q=private", "/api/mail/snapshot",
                      "/api/mail/activity", "/api/mail/timeline"):
            data = get_json(base, route)
            serialized = json.dumps(data)
            for private in ("secret-agent", "private-peer", "private-session", "private-title-marker", hidden["thread_id"]):
                assert private not in serialized, (route, private)
        with pytest.raises(HTTPError) as error:
            get_json(base, "/api/mail/thread?id=" + hidden["thread_id"])
        assert error.value.code == 404
        thread = get_json(base, "/api/mail/thread?id=" + visible["thread_id"])
        assert thread["messages"][0]["body"] == "Visible"


def test_thread_contains_safe_markdown_and_explicit_observation(kb):
    body = '## Heading\n\n- first\n- second\n\n<script>alert(1)</script>\n\n[bad](javascript:alert)\n\n'
    body += chr(96) * 3 + '\n<x>\n' + chr(96) * 3
    handoff = mail.write_message(kb, sender="writer", recipients=["human", "reviewer"],
                                 body=body, record_kind="handoff")
    with serving(kb) as (base, _):
        data = get_json(base, "/api/mail/thread?id=" + handoff["thread_id"])
    rendered = data["messages"][0]["body_html"]
    assert "<h3>Heading</h3>" in rendered
    assert "<ul><li>first</li><li>second</li></ul>" in rendered
    assert "<pre><code>&lt;x&gt;</code></pre>" in rendered
    assert "<script>" not in rendered
    assert 'href="javascript:' not in rendered
    assert data["messages"][0]["body"] == body
    assert len(data["observation"]["handoffs"]) == 1


def test_status_rejects_registry_identity_collision(kb):
    mail.write_message(kb, sender="writer", recipients="human",
                       origin_session_id="shared-id", body="Visible provenance")
    mail.register_session(kb, "shared-id", "private-identity", machine_id="private-machine")
    with serving(kb) as (base, _):
        data = get_json(base, "/api/mail/status")
    assert data["sessions"] == []
    assert "private-identity" not in json.dumps(data)
    assert "private-machine" not in json.dumps(data)


@pytest.mark.parametrize("invalid_parent", ["missing", "private", "other-thread", "not-recipient", "wrong-destination", "self"])
def test_status_does_not_verify_unsubstantiated_reply(kb, invalid_parent):
    parent = mail.write_message(kb, sender="human", recipients="writer", body="Request")
    if invalid_parent == "private":
        parent = mail.write_message(kb, sender="private-sender", recipients="writer", body="Hidden parent")
    elif invalid_parent == "not-recipient":
        parent = mail.write_message(kb, sender="human", recipients="other-agent", body="Other request")
    elif invalid_parent == "self":
        parent = mail.write_message(kb, sender="writer", recipients="human", body="Own statement")
    elif invalid_parent == "wrong-destination":
        parent = mail.write_message(kb, sender="peer", recipients="writer,human", body="Shared request")
    mail.write_message(kb, sender="writer", recipients="human",
                               thread_id="different-thread" if invalid_parent == "other-thread" else parent["thread_id"],
                               reply_to="does-not-exist" if invalid_parent == "missing" else parent["message_id"], body="Claimed reply")
    with serving(kb) as (base, _):
        data = get_json(base, "/api/mail/status")
    writer = next(row for row in data["agents"] if row["agent_id"] == "@writer")
    assert writer["verification_status"] == "observed"
    assert "verification_evidence" not in writer


@pytest.mark.parametrize("body", [
    '<img src=x onerror=alert(1)>',
    '[<svg/onload=alert(1)>](https://example.org)',
    '[x](https://example.org/"onfocus="x)',
    '[x](data:text/html,evil)',
    '![x](javascript:alert)',
    '<iframe srcdoc="<script>bad</script>"></iframe>',
])
def test_markdown_cannot_introduce_active_markup(body):
    class Tags(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag in {"p", "a", "span", "code", "strong", "em"}
            assert not any(name.startswith("on") for name, _ in attrs)
            for name, value in attrs:
                if name == "href":
                    assert value.startswith(("http://", "https://"))
    Tags().feed(md_to_html(body))


def test_full_wiki_reads_past_preview_and_returns_to_thread(kb):
    (kb / "wiki" / "long.md").write_text(
        "---\ntitle: Long\nstatus: active\n---\n\n" + "a" * 13000 + "\n\nEND-OF-DOCUMENT",
        encoding="utf-8",
    )
    return_to = "/#view=inbox&thread=one&section=evidence"
    with serving(kb) as (base, _):
        preview = get_json(base, "/api/mail/memory/item?path=wiki/long.md")
        assert preview["truncated"]
        assert preview["review"]["state"] == "unknown"
        assert "已审核" not in preview["kind_label"]
        query = urlencode({"path": "wiki/long.md", "return_to": return_to})
        with urlopen(base + "/api/mail/wiki-page?" + query, timeout=5) as response:
            body = response.read().decode()
        assert "END-OF-DOCUMENT" in body
        assert '/#view=inbox&amp;thread=one&amp;section=evidence' in body
        query = urlencode({"path": "wiki/long.md", "return_to": "//evil.example"})
        with urlopen(base + "/api/mail/wiki-page?" + query, timeout=5) as response:
            assert 'href="//evil.example"' not in response.read().decode()


def test_overview_rejects_bad_queries(kb):
    with serving(kb) as (base, _):
        for query in ("limit=oops", "filter=online", "cursor=not-a-cursor"):
            with pytest.raises(HTTPError) as error:
                get_json(base, "/api/mail/overview?" + query)
            assert error.value.code == 400


def test_promoted_candidate_history_opens_reviewed_wiki_without_writes(kb, monkeypatch):
    from knowledge_studio import store
    monkeypatch.setenv("OKS_ROOT", str(kb))
    draft = kb / "drafts/memory.md"
    draft.write_text("---\ntitle: Durable memory\ndraft_type: concept\ndraft_area: computing\nsource_bundle_id: bundle:memory\n---\nRead notes when resuming.", encoding="utf-8")
    slug = store.promote_draft("memory")
    before = filesystem_snapshot(kb)
    with serving(kb) as (base, _):
        item = get_json(base, "/api/mail/memory/item?path=drafts/memory.md")
        assert item["path"].startswith("wiki/")
        assert slug in item["path"]
        assert item["metadata"]["source_bundle_id"] == "bundle:memory"
        with urlopen(base + "/wiki-page?path=drafts/memory.md", timeout=5) as response:
            assert "Read notes when resuming" in response.read().decode()
    assert filesystem_snapshot(kb) == before


def test_edited_retained_candidate_does_not_inherit_old_review(kb, monkeypatch):
    from knowledge_studio import store
    monkeypatch.setenv('OKS_ROOT', str(kb))
    path = kb / 'drafts/memory.md'
    path.write_text('---\ntitle: Memory\ndraft_type: concept\ndraft_area: computing\n---\nOriginal source.', encoding='utf-8')
    store.promote_draft('memory')
    path.write_text(path.read_text(encoding='utf-8') + '\nUnreviewed addition.', encoding='utf-8')
    before = filesystem_snapshot(kb)
    with serving(kb) as (base, _):
        item = get_json(base, '/api/mail/memory/item?path=drafts/memory.md')
        assert item['path'] == 'drafts/memory.md'
        assert 'Unreviewed addition.' in item['body']
    assert filesystem_snapshot(kb) == before


@pytest.mark.parametrize("status,reviewed", [("provisional", True), ("active", False)])
def test_missing_candidate_cannot_resolve_to_unreviewed_page(kb, status, reviewed):
    (kb / "wiki/memory.md").write_text(
        f"---\ntitle: Memory\nstatus: {status}\nsource_candidates: [drafts/memory.md]\nhuman_reviewed_at: {'2026-10-22' if reviewed else 'null'}\n---\nBody", encoding="utf-8")
    with serving(kb) as (base, _):
        with pytest.raises(HTTPError) as error:
            get_json(base, "/api/mail/memory/item?path=drafts/memory.md")
        assert error.value.code == 404


def test_candidate_redirect_refuses_ambiguous_and_unbounded_paths(kb):
    for name in ["first", "second"]:
        (kb / f"wiki/{name}.md").write_text(
            "---\ntitle: Memory\nstatus: active\nsource_candidates: [drafts/memory.md]\nhuman_reviewed_at: 2026-10-22\n---\nBody", encoding="utf-8")
    with serving(kb) as (base, _):
        for path in ["drafts/memory.md", "drafts/../private.md", "drafts/missing.md"]:
            with pytest.raises(HTTPError) as error:
                get_json(base, "/api/mail/memory/item?" + urlencode({"path": path}))
            assert error.value.code in {400, 404}


def test_memory_cannot_escape_through_symlink(kb, tmp_path):
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.md").write_text("private-secret", encoding="utf-8")
    link = kb / "wiki" / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with serving(kb) as (base, _):
        with pytest.raises(HTTPError) as error:
            get_json(base, "/api/mail/memory/item?path=wiki/external/secret.md")
        assert error.value.code == 404


def test_worker_source_refresh_is_read_only_and_ordinary_types_have_no_skill_badge(kb):
    (kb/'wiki/evidence.md').write_text('---\ntitle: Evidence\narea: computing\ntype: strategy\n---\nBody',encoding='utf-8')
    before=filesystem_snapshot(kb)
    calls=[]
    class Source:
        def snapshot(self,force=False):
            calls.append(force)
            return {'state':'live','source':{'base_token_hash':'abc','table_id':'tbl1'},
                    'observed_at':'2026-10-19T00:00:00Z','records':[{'record_id':'r1','fields':{
                        'Wiki路径':'wiki/evidence.md','知识域':'science','质量状态':'partial'}}]}
    with serving(kb,knowledge_source=Source()) as (base,server):
        data=get_json(base,'/api/mail/knowledge-map?refresh=1')
        assert data['worker_source']['linked_records']==1
        assert calls==[True]
        with urlopen(base+'/wiki-page?path=wiki/evidence.md',timeout=5) as response:
            html=response.read().decode('utf-8')
        assert '治理类型' not in html
        assert 'Skill 候选' not in html
    assert filesystem_snapshot(kb)==before
