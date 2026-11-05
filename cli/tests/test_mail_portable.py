import json
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from knowledge_studio.cli import app
from knowledge_studio import mail
from knowledge_studio.mail_setup import install_skill
from knowledge_studio.resources import asset_root
from knowledge_studio.mail_web import create_server


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "共享知识库"
    (root / "mail").mkdir(parents=True)
    (root / "wiki").mkdir()
    monkeypatch.setenv("OKS_MACHINE_ID", "portable-test-machine")
    return root


def test_skill_setup_is_bound_and_non_destructive(kb, tmp_path):
    folder = tmp_path / "host" / "skills"
    result = CliRunner().invoke(app, ["mail", "setup", "--path", str(kb), "--agent", "reviewer", "--skills-dir", str(folder)])
    assert result.exit_code == 0, result.output
    dest = folder / "oks-mail"
    assert json.loads((dest / "binding.json").read_text(encoding="utf-8"))["agent_id"] == "reviewer"
    assert install_skill(kb, "reviewer", folder) == dest
    with pytest.raises(ValueError, match="Existing skill differs"):
        install_skill(kb, "other", folder)
    assert json.loads((dest / "binding.json").read_text(encoding="utf-8"))["agent_id"] == "reviewer"


@pytest.mark.parametrize("identity", ["human", "all", "unknown", "../escape", "", "x/y"])
def test_invalid_agent_binding(kb, tmp_path, identity):
    with pytest.raises(ValueError):
        install_skill(kb, identity, tmp_path / "skills")


def test_independent_skill_sessions_roundtrip(kb, tmp_path):
    # Uses the actual installed oks executable; PYTHONPATH selects this checkout.
    a = install_skill(kb, "writer", tmp_path / "writer-skills") / "scripts" / "mail.py"
    b = install_skill(kb, "reviewer", tmp_path / "reviewer-skills") / "scripts" / "mail.py"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONIOENCODING="utf-8", OKS_ROOT=str(tmp_path / "wrong"), OKS_AGENT_ID="human")

    def run(helper, *args, success=True):
        result = subprocess.run([sys.executable, str(helper), *args], env=env, cwd=tmp_path,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout

    first = json.loads(run(a, "--session", "writer-s1", "send", "--to", "@reviewer", "--title", "中文讨论", "--body", "保留上下文", "--format", "json"))
    snapshot = json.loads(run(b, "snapshot"))
    thread = snapshot["threads"][0]
    assert thread["thread_id"] == first["thread_id"]
    assert "保留上下文" in run(b, "thread", first["thread_id"])
    run(b, "--session", "reviewer-s1", "reply", first["thread_id"], "--body", "检查完毕", "--format", "json")
    run(a, "--session", "writer-s2", "reply", first["thread_id"], "--body", "新会话继续", "--format", "json")
    rows = json.loads(run(b, "snapshot"))["threads"][0]["messages"]
    assert len(rows) == 3
    assert {r["origin_session_id"] for r in rows} == {"writer-s1", "reviewer-s1", "writer-s2"}
    assert all(r["sender_kind"] == "agent" for r in rows)
    assert {r["from"].lstrip("@") for r in rows} == {"writer", "reviewer"}
    run(a, "send", "--to", "reviewer", "--body", "missing session", success=False)
    run(a, "snapshot", "--path", str(tmp_path / "wrong"), success=False)


def test_web_generic_recipient_and_origin(kb):
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(route, payload=None, headers=None):
        req = Request(base + route, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", **(headers or {})})
        return urlopen(req, timeout=5)

    try:
        with request("/") as response:
            page = response.read()
        # Phase 1 面板：收件人概念依旧通用 —— 身份一律由 API 投影提供，页面里不写死任何收件人。
        # （旧断言 `b"recipient" in page` 依赖旧版英文文案，随 Phase 1 重做作废；
        #   这里守的是同一个不变量，换成对当前实现的断言。）
        assert "讨论".encode() in page and "主导航".encode() in page
        assert b"reviewer" not in page
        assert b"custom-agent" not in page
        with request("/favicon.svg") as response:
            assert response.headers["Content-Type"].startswith("image/svg+xml")
            assert b"<svg" in response.read()
        (kb / "wiki" / "memory.md").write_text("---\ntitle: 团队记忆\narea: engineering\ntype: concept\n---\n# Memory\n", encoding="utf-8")
        (kb / "profiles" / "agents").mkdir(parents=True)
        (kb / "profiles" / "agents" / "reviewer.md").write_text("---\ntitle: 审核助手\nrole: 候选知识初审\nscope: engineering\n---\n负责审查候选知识。\n", encoding="utf-8")
        (kb / "profiles" / "agents" / "_template.md").write_text("---\ntitle: 不应显示\n---\n", encoding="utf-8")
        (kb / "raw" / "executions" / "run-1").mkdir(parents=True)
        (kb / "raw" / "executions" / "run-1" / "trace.md").write_text("# Trace\n", encoding="utf-8")
        with request("/api/memory") as response:
            memory = json.load(response)
        assert memory["schema"] == "memory.snapshot.v1"
        assert memory["counts"]["wiki"] == 1
        assert memory["counts"]["raw"] == 0
        assert memory["lifecycle"][-1] == "explicit_feedback"
        with request("/api/mail/memory") as response:
            assert json.load(response)["schema"] == "memory.snapshot.v1"
        with request("/api/mail/members") as response:
            members = json.load(response)
        assert members["schema"] == "oks.members.v1"
        assert members["profiles"][0]["id"] == "reviewer"
        assert members["profiles"][0]["role"] == "候选知识初审"
        assert members["profiles"][0]["profile_kind"] == "agent"
        assert all(profile["id"] != "_template" for profile in members["profiles"])
        with request("/api/mail/team") as response:
            team = json.load(response)
        assert team["schema"] == "oks.team-sync.v1"
        assert team["state"] == "not_git"
        with pytest.raises(HTTPError) as error:
            request("/api/mail/team/sync", {"push": True})
        assert error.value.code == 409
        with request("/api/mail/send", {"to": "custom-agent,reviewer", "title": "Hi", "body": "hello", "record_kind": "knowledge_ref", "delivery_reason": "review_request", "evidence_refs": [{"type": "wiki", "path": "wiki/memory.md"}]}) as response:
            result = json.load(response)
        assert result["record_kind"] == "knowledge_ref"
        assert result["evidence_refs"] == [{"type": "wiki", "path": "wiki/memory.md"}]
        assert len(mail.snapshot_data(kb, "custom-agent")["threads"]) == 1
        long_body = "全文" * 3000
        mail.write_message(kb, sender="custom-agent", recipients="human", body=long_body, thread_id=result["thread_id"])
        with request("/api/mail/thread?id=" + result["thread_id"]) as response:
            full = json.load(response)
        assert full["messages"][-1]["body"] == long_body
        assert full["messages"][0]["record_kind"] == "knowledge_ref"
        assert full["messages"][0]["evidence_refs"] == [{"type": "wiki", "path": "wiki/memory.md"}]
        mail.write_message(kb, sender="custom-agent", recipients="human", body="reply", thread_id=result["thread_id"])
        with request("/api/mail/reply", {"thread_id": result["thread_id"], "body": "continue"}) as response:
            assert response.status == 201
        with request("/api/mail/invite", {"thread_id": result["thread_id"], "to": "new-agent", "body": "请加入这段对话"}) as response:
            invited = json.load(response)
        assert invited["thread_id"] == result["thread_id"]
        assert "@new-agent" in invited["recipients"]
        invited_thread = mail.thread_messages(kb, result["thread_id"], "new-agent")
        assert len(invited_thread) == 1
        assert invited_thread[-1]["meta"]["from"] == "human"
        assert invited_thread[-1]["body"] == "请加入这段对话"
        for invalid_invite in ["new-agent", "all", "human", "unknown"]:
            with pytest.raises(HTTPError) as error:
                request("/api/mail/invite", {"thread_id": result["thread_id"], "to": invalid_invite, "body": "再次邀请"})
            assert error.value.code == 400
        for invalid_payload in [
            {"thread_id": result["thread_id"], "to": "another-agent", "body": ""},
            {"thread_id": "missing-thread", "to": "another-agent", "body": "加入"},
        ]:
            with pytest.raises(HTTPError) as error:
                request("/api/mail/invite", invalid_payload)
            assert error.value.code == 400
        sender_only = mail.write_message(
            kb, sender="sender-only", recipients="human", body="我先发起这段对话", title="仅发件人"
        )
        with pytest.raises(HTTPError) as error:
            request("/api/mail/invite", {"thread_id": sender_only["thread_id"], "to": "sender-only", "body": "重复邀请"})
        assert error.value.code == 400
        for route, payload, headers in [
            ("/api/mail/send", {"to": "../escape", "title": "bad", "body": "bad"}, {}),
            ("/api/mail/send", {"to": "x", "title": "bad", "body": "bad"}, {"Origin": "http://evil.invalid"}),
            ("/api/mail/snapshot", None, {"Host": "evil.invalid"}),
            ("/api/mail/process", {"message_id": "x"}, {}),
        ]:
            with pytest.raises(HTTPError) as error:
                request(route, payload, headers)
            assert error.value.code in {400, 403, 404}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_web_memory_projection_is_readable_and_path_safe(kb):
    wiki = kb / "wiki" / "engineering" / "repro.md"
    wiki.parent.mkdir(parents=True)
    wiki.write_text(
        "---\n"
        "title: 可复现性检查清单\n"
        "area: engineering\n"
        "type: strategy\n"
        "status: active\n"
        "---\n\n"
        "# 可复现性检查清单\n\n"
        "先固定环境，再记录运行命令和证据。\n",
        encoding="utf-8",
    )
    draft = kb / "drafts" / "feedback.md"
    draft.parent.mkdir(parents=True)
    draft.write_text(
        "---\n"
        "title: 一次真实复用后的反馈\n"
        "summary: 需要补充运行前置条件\n"
        "---\n\n候选补充。\n",
        encoding="utf-8",
    )
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(route):
        return urlopen(Request(base + route), timeout=5)

    try:
        with request("/api/memory") as response:
            snapshot = json.load(response)
        item = next(row for row in snapshot["recent"] if row["path"] == "wiki/engineering/repro.md")
        assert item["title"] == "可复现性检查清单"
        assert item["kind"] == "wiki"
        assert item["kind_label"] == "Wiki · 审核记录未知"
        assert item["review"]["state"] == "unknown"
        assert item["area"] == "engineering"
        assert snapshot["facets"]["areas"]["engineering"] == 1
        assert "固定环境" in item["summary"]
        assert item["updated_at"]

        with request("/api/memory/item?path=wiki/engineering/repro.md") as response:
            detail = json.load(response)
        assert detail["path"] == "wiki/engineering/repro.md"
        assert detail["title"] == item["title"]
        assert "运行命令" in detail["body"]
        assert detail["metadata"]["type"] == "strategy"

        for unsafe in ("../mail/messages/secret.md", "mail/messages/secret.md", "wiki/../mail/x.md"):
            with pytest.raises(HTTPError) as error:
                request("/api/memory/item?path=" + unsafe)
            assert error.value.code in {400, 404}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_web_memory_projection_uses_durable_time_and_hides_inactive(kb):
    wiki = kb / "wiki"
    (wiki / "engineering").mkdir(parents=True)
    (wiki / "engineering" / "active.md").write_text(
        "---\n"
        "title: 活跃知识\n"
        "area: engineering\n"
        "type: practice\n"
        "status: active\n"
        "created: 2026-01-01\n"
        "updated_at: 2026-09-15T08:00:00+00:00\n"
        "---\n\n正文摘要。\n",
        encoding="utf-8",
    )
    (wiki / "engineering" / "dropped.md").write_text(
        "---\n"
        "title: 已丢弃知识\n"
        "area: engineering\n"
        "status: dropped\n"
        "updated_at: 2026-09-20T08:00:00+00:00\n"
        "---\n\n不应出现在可复用列表。\n",
        encoding="utf-8",
    )
    (wiki / "engineering" / "archived.md").write_text(
        "---\n"
        "title: 已归档知识\n"
        "area: engineering\n"
        "archived: true\n"
        "updated_at: 2026-09-19T08:00:00+00:00\n"
        "---\n\n不应出现在可复用列表。\n",
        encoding="utf-8",
    )
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/memory", timeout=5) as response:
            snapshot = json.load(response)
        assert [item["title"] for item in snapshot["recent"]] == ["活跃知识"]
        assert snapshot["recent"][0]["timestamp_source"] == "updated_at"
        assert snapshot["counts"]["wiki"] == 1
        assert snapshot["counts"]["wiki_total"] == 3
        assert snapshot["counts"]["excluded"] == 2
        assert snapshot["facets"]["areas"] == {"engineering": 1}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_web_empty_state_actions_use_presence_checks(kb):
    """面板不提供自己做不到的动作（原则②：移交而非代办）。

    旧版是在空状态里摆「发起协作 / 创建 / 刷新记忆 / 团队同步」按钮，靠 presence 检查决定显不显示。
    Phase 1 把这些入口整体移除（面板不再自己发起协作，也不安装、不发布），
    所以本用例守的仍是同一个意图，只是断言方向从「有没有这个按钮」变成「这些入口都不得再长回来」。
    """
    app = (asset_root() / "mail-web" / "app.js").read_text(encoding="utf-8")
    html = (asset_root() / "mail-web" / "index.html").read_text(encoding="utf-8")
    # 面板不出手：源码里不得再出现任何自发起入口
    for removed in ("data-create", "data-refresh-memory", "data-team-sync",
                    "MAIL_INTENTS", "data-create-intent", "data-memory-collab-path",
                    "threadSessions"):
        assert removed not in app, f"面板不得重新长出 {removed} 入口"
    for removed in ("newIntent", "agentChoices", "发起协作"):
        assert removed not in html, f"面板不得重新长出 {removed} 入口"
    # Guidance remains a read-only handoff to the host, even with an empty KB.
    server = create_server(kb, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/connection-guide", timeout=5) as response:
            guide = json.load(response)
        assert guide["guide"].strip()
        with urlopen(base + "/api/mail/capabilities", timeout=5) as response:
            capabilities = json.load(response)
        assert capabilities["read_only"] is True
        assert capabilities["wake_supported"] is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    # 零写入口
    assert "<form" not in html


def test_web_connection_status_and_mail_verification(kb):
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(route, payload=None):
        req = Request(
            base + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return urlopen(req, timeout=5)

    try:
        with request("/api/mail/status") as response:
            status = json.load(response)
        assert status["schema"] == "mail.connection-status.v1"
        assert status["current_machine_id"] == "portable-test-machine"
        assert status["sessions"] == []

        mail.register_session(kb, "reviewer-s1", "reviewer", machine_id="portable-test-machine")
        with request("/api/mail/status") as response:
            status = json.load(response)
        assert status["agents"] == []
        assert status["sessions"] == []

        message = mail.write_message(kb, sender="human", recipients="reviewer", body="verify Mail")
        with request("/api/mail/status") as response:
            status = json.load(response)
        # 第二档：被投递过，但对方还没确认 → 已观察到。
        assert status["agents"][0]["verification_status"] == "observed"

        visible = next(mail.iter_messages(kb, "reviewer"))
        mail.record_delivery(kb, "reviewer-s1", visible, agent_id="reviewer", machine_id="portable-test-machine")
        mail.acknowledge_delivery(kb, "reviewer-s1", message["message_id"], agent_id="reviewer", machine_id="portable-test-machine")
        with request("/api/mail/status") as response:
            status = json.load(response)
        # 第三档：拿到了回执证据 → 已验证。
        assert status["agents"][0]["verification_status"] == "verified"
        assert status["agents"][0]["verification_evidence"]["evidence"] == "acknowledged"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("visible_source", ["message", "receipt"])
def test_status_projects_visible_machine_after_private_session_update(kb, visible_source):
    if visible_source == "message":
        mail.write_message(kb, sender="writer", recipients="human", body="Visible",
                           origin_session_id="writer-session", origin_machine_id="public-machine")
    else:
        sent = mail.write_message(kb, sender="human", recipients="writer", body="Visible")
        row = next(mail.iter_messages(kb, "writer"))
        mail.record_delivery(kb, "writer-session", row, agent_id="writer", machine_id="public-machine")
        assert sent["message_id"] == row["meta"]["message_id"]
    from knowledge_studio.mail_web import connection_status
    before = connection_status(kb, "human")
    mail.register_session(kb, "writer-session", "writer", scope="PRIVATE-PROJECT-SECRET",
                          machine_id="private-machine")

    status = connection_status(kb, "human")
    serialized = json.dumps(status)
    assert status["machine_count"] == before["machine_count"]
    assert status["machines"] == before["machines"]
    assert "private-machine" not in serialized
    assert "PRIVATE-PROJECT-SECRET" not in serialized
    assert status["sessions"][0]["machine_id"] == "public-machine"
    assert status["sessions"][0]["scope"] == ""
    assert status["agents"][0]["machine_ids"] == ["public-machine"]


def test_mail_verification_counts_replies_and_agent_only_threads(kb):
    """Reply/ack evidence is KB-wide: it must survive full agent-to-agent threads."""
    from knowledge_studio.mail_web import _mail_verification

    first = mail.write_message(kb, body="handoff", sender="claude", recipients="codex")
    mail.write_message(
        kb,
        body="done, see notes",
        sender="codex",
        recipients="claude",
        thread_id=first["thread_id"],
        reply_to=first["message_id"],
    )
    verified = _mail_verification(kb)
    assert verified["@codex"]["evidence"] == "reply"
    assert verified["@codex"]["message_id"]
    # Sending alone is not lifecycle evidence for the sender.
    assert "@claude" not in verified

    mail.register_session(kb, "codex-s1", "codex")
    visible = next(message for message in mail.iter_messages(kb, "codex")
                   if str(message["meta"].get("message_id")) == first["message_id"])
    mail.record_delivery(kb, "codex-s1", visible, agent_id="codex")
    mail.acknowledge_delivery(kb, "codex-s1", first["message_id"], agent_id="codex")
    verified = _mail_verification(kb)
    assert verified["@codex"]["evidence"] == "acknowledged"


def test_web_archive_roundtrip_for_canonical_and_legacy(kb):
    inbox = kb / "mail" / "inbox"
    inbox.mkdir(parents=True)
    legacy_thread = "legacy-thread-roundtrip"
    for message_id, body, read_marker in [
        ("legacy-one", "旧消息一", "false"),
        ("legacy-two", "旧消息二", "false"),
        ("legacy-read", "旧消息已读", "true"),
    ]:
        (inbox / f"{message_id}.md").write_text(
            "---\n"
            f"message_id: {message_id}\n"
            f"thread_id: {legacy_thread}\n"
            "from: @legacy-agent\n"
            "to: @human\n"
            "timestamp: 2026-09-12T00:00:00+00:00\n"
            f"read: {read_marker}\n"
            "type: text\n"
            "---\n"
            f"# 旧对话\n\n{body}\n",
            encoding="utf-8",
        )
    canonical = mail.write_message(
        kb, sender="canonical-agent", recipients="human", title="新格式", body="新格式消息"
    )
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(route, payload=None):
        req = Request(
            base + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return urlopen(req, timeout=5)

    try:
        with request("/api/mail/snapshot") as response:
            before = json.load(response)
        assert next(t for t in before["threads"] if t["thread_id"] == legacy_thread)["state"] == "open"
        with request("/api/mail/archive", {"thread_id": legacy_thread}) as response:
            assert json.load(response)["status"] == "archived"
        with request("/api/mail/snapshot") as response:
            archived = next(t for t in json.load(response)["threads"] if t["thread_id"] == legacy_thread)
        assert archived["state"] == "archived"
        assert all(message["archived_at"] for message in archived["messages"])
        assert "archived_at:" not in (inbox / "legacy-one.md").read_text(encoding="utf-8")
        with request("/api/mail/unarchive", {"thread_id": legacy_thread}) as response:
            assert json.load(response)["status"] == "unarchived"
        with request("/api/mail/snapshot") as response:
            restored = next(t for t in json.load(response)["threads"] if t["thread_id"] == legacy_thread)
        assert restored["state"] == "open"
        restored_messages = {message["message_id"]: message for message in restored["messages"]}
        assert all(restored_messages[key]["archived_at"] is None for key in ["legacy-one", "legacy-two", "legacy-read"])
        assert restored_messages["legacy-one"]["read_at"] is None
        assert restored_messages["legacy-two"]["read_at"] is None
        assert restored_messages["legacy-read"]["read_at"] == "2026-09-12T00:00:00+00:00"
        other_agent = next(t for t in mail.snapshot_data(kb, "legacy-agent")["threads"] if t["thread_id"] == legacy_thread)
        assert other_agent["state"] == "open"

        with request("/api/mail/read", {"message_id": "legacy-one"}) as response:
            assert json.load(response)["state"]["read_at"]
        read_state = mail.load_state(kb, "human", "legacy-one")
        assert read_state["read_at"]
        with request("/api/mail/archive", {"thread_id": legacy_thread}) as response:
            assert json.load(response)["status"] == "archived"
        with request("/api/mail/unarchive", {"thread_id": legacy_thread}) as response:
            assert json.load(response)["status"] == "unarchived"
        with request("/api/mail/snapshot") as response:
            after_read_roundtrip = next(t for t in json.load(response)["threads"] if t["thread_id"] == legacy_thread)
        after_read_messages = {message["message_id"]: message for message in after_read_roundtrip["messages"]}
        assert after_read_messages["legacy-one"]["read_at"]

        with request("/api/mail/archive", {"thread_id": canonical["thread_id"]}) as response:
            assert json.load(response)["status"] == "archived"
        with request("/api/mail/unarchive", {"thread_id": canonical["thread_id"]}) as response:
            assert json.load(response)["status"] == "unarchived"
        with request("/api/mail/snapshot") as response:
            canonical_restored = next(t for t in json.load(response)["threads"] if t["thread_id"] == canonical["thread_id"])
        assert canonical_restored["state"] == "open"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_web_session_id_is_stable_for_bound_port(kb):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    first = create_server(kb, port, mode="collaboration")
    try:
        first_session = first.session_id
        session_path = mail.sessions_dir(kb) / f"{first_session}.json"
        first_record = json.loads(session_path.read_text(encoding="utf-8"))
    finally:
        first.server_close()
    second = create_server(kb, port, mode="collaboration")
    try:
        token = hashlib.sha256("portable-test-machine".encode("utf-8")).hexdigest()[:12]
        assert second.session_id == f"mail-ui-{port}-{token}"
        assert second.session_id == first_session
        second_record = json.loads(session_path.read_text(encoding="utf-8"))
        assert second_record["started_at"] == first_record["started_at"]
        assert len(list(mail.sessions_dir(kb).glob("mail-ui-*.json"))) == 1
    finally:
        second.server_close()


def test_web_session_id_separates_machines(kb, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    first = create_server(kb, port, mode="collaboration")
    first_id = first.session_id
    first.server_close()
    monkeypatch.setenv("OKS_MACHINE_ID", "another-portable-machine")
    second = create_server(kb, port, mode="collaboration")
    try:
        assert second.session_id != first_id
        assert len(list(mail.sessions_dir(kb).glob("mail-ui-*.json"))) == 2
    finally:
        second.server_close()


def test_cli_archive_legacy_is_recipient_scoped(kb, monkeypatch):
    inbox = kb / "mail" / "inbox"
    inbox.mkdir(parents=True)
    message_id = "legacy-cli-archive"
    thread_id = "legacy-cli-thread"
    path = inbox / f"{message_id}.md"
    path.write_text(
        "---\n"
        f"message_id: {message_id}\n"
        f"thread_id: {thread_id}\n"
        "from: @legacy-agent\n"
        "to: @human, @reviewer\n"
        "timestamp: 2026-09-12T00:00:00+00:00\n"
        "read: false\n"
        "type: text\n"
        "---\n\n# 旧格式\n\n内容\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OKS_AGENT_ID", "human")
    result = CliRunner().invoke(app, ["mail", "archive", thread_id, "--path", str(kb)])
    assert result.exit_code == 0, result.output
    state = mail.load_state(kb, "human", message_id)
    assert state["archived_at"]
    assert state["read_at"] is None
    assert "read: false" in path.read_text(encoding="utf-8")
    other = mail.snapshot_data(kb, "reviewer")["threads"][0]
    assert other["state"] == "open"
