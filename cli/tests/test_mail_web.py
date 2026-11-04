"""HTTP contract tests for the real local Mail workspace."""
import json
import re
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from knowledge_studio import mail
from knowledge_studio.mail_web import create_server


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "shared-kb"
    (root / "mail").mkdir(parents=True)
    (root / "wiki").mkdir()
    monkeypatch.setenv("OKS_MACHINE_ID", "web-test-machine")
    return root


def test_web_reads_real_threads_and_rejects_unsafe_requests(kb):
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(route, payload=None, headers=None):
        req = Request(
            base + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return urlopen(req, timeout=5)

    try:
        with request("/") as response:
            # Studio has exactly three primary views; writes remain separately
            # gated by the same local capability checks below.
            body = response.read()
            assert re.findall(rb'data-tab="([^"]+)"', body) == [b'discuss', b'goals', b'learning']
            assert b'/studio.js' in body
        with request("/api/mail/send", {"to": "custom-agent,reviewer", "title": "Hi", "body": "hello"}) as response:
            result = json.load(response)
        assert len(mail.snapshot_data(kb, "custom-agent")["threads"]) == 1

        long_body = "全文" * 3000
        mail.write_message(kb, sender="custom-agent", recipients="human", body=long_body, thread_id=result["thread_id"])
        with request("/api/mail/thread?id=" + result["thread_id"]) as response:
            full = json.load(response)
        assert full["messages"][-1]["body"] == long_body

        mail.write_message(kb, sender="custom-agent", recipients="human", body="reply", thread_id=result["thread_id"])
        with request("/api/mail/reply", {"thread_id": result["thread_id"], "body": "continue"}) as response:
            assert response.status == 201

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


# ── 独立 Wiki 页：面向普通读者的显示契约（R6）────────────────────────────
#
# 这一页是「有人点进来才看到」的深页面，最容易漏出维护者字段。
# 三条硬要求：分类值显示人话、维护信息降级进展开说明、不出现内部字段名。

def test_wiki_page_shows_human_labels_and_hides_maintenance_details():
    from knowledge_studio.mail_web import render_wiki_page

    item = {
        "path": "wiki/decision-card-on-blocker.md",
        "kind": "wiki",
        "kind_label": "已审核 Wiki",
        "title": "受阻时就地长出决策卡",
        "summary": "执行流受阻时就地展开候选方案。",
        "body": "## Summary\n\n正文一段。\n",
        "tags": ["collaboration", "checkpoint", "ui"],
        "tag_labels": ["团队与协作", "人类检查点", "界面与交互"],
        "area": "collaboration",
        "area_label": "团队与协作",
        "type": "strategy",
        "type_label": "策略",
        "is_skill": True,
        "status": "active",
        "status_label": "可复用",
        "updated_at": "2026-09-19T00:00:00+00:00",
        "timestamp_source": "updated_at",
    }
    page = render_wiki_page(item)

    # 分类值必须是人话
    assert "团队与协作、人类检查点、界面与交互" in page
    assert "治理类型" in page and "策略" in page
    # 原始字段值 / 字段名一个都不许露
    for leaked in ("collaboration", "updated_at", "file_mtime", "frontmatter"):
        assert leaked not in page, leaked
    # 维护信息保留但降级：默认收在展开说明里，且人话化
    assert "文件：wiki/decision-card-on-blocker.md" in page
    assert "时间来源：条目里记录的更新时间" in page
    assert '<details class="why">' in page
    # 点进来的人要有回头路
    assert "← 返回面板" in page


def test_wiki_page_never_invents_tag_labels_for_unknown_english_keys():
    """翻不出来的英文机器键不硬塞给读者；中文标签原样保留。"""
    from knowledge_studio.mail_knowledge import tag_label

    assert tag_label("collaboration") == "团队与协作"
    assert tag_label("checkpoint") == "人类检查点"
    assert tag_label("some_internal_key") == ""
    assert tag_label("自定义主题") == "自定义主题"
    assert tag_label(None) == ""


# ── 只读边界：面板不许有写路径（2026-09-22）─────────────────────────────
#
# 背景：面板原先有一个治理开关（裸 checkbox + change 即 POST /api/mail/knowledge/toggle），
# 写的是 wiki/drafts 条目的 enabled 位。移除它有两个理由，都记在案：
#   ① 那个位当时没有任何消费方（recall / store / skill / hook 都不读它），
#      而界面据此声称「停用后不再被 Skill 层启用」—— 许诺了一个没实现的下游效果；
#   ② 一个只读观察面不该是唯一能改写知识库文件的入口。
# 这两条断言把这个边界钉住，防止它被悄悄加回来。

def _served(base, route):
    with urlopen(base + route, timeout=5) as response:
        return response.read().decode("utf-8")


def test_panel_serves_no_post_capable_control(kb):
    """面板不能有任何会发 POST 的控件。

    口径说明：判「是否只读」要数**发 POST 的请求**，不是数表单元素。
    左栏的 showCounts / showSource 是视图开关，kmSearch 是筛选框 —— 数 form/input
    会把它们误判成写控件；反过来，数表单元素也会漏掉一个裸 checkbox。
    2026-09-22 那次「零写操作」结论就是这么假绿的：口径是「form 数为 0」，
    而真正的写路径是一个 `input.type='checkbox'` + change 即 POST。
    """
    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        script = _served(f"http://127.0.0.1:{server.server_port}", "/app.js")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert not re.search(r"method\s*:\s*['\"]POST['\"]", script, re.IGNORECASE), (
        "面板是只读观察面，不应该发 POST"
    )
    assert "<form" not in script


def test_removed_knowledge_toggle_route_fails_closed(kb):
    """被移除的写端点必须 404，且目标文件一个字节都不许变。"""
    target = kb / "wiki" / "a.md"
    target.write_text("---\ntitle: A\n---\n\nbody\n", encoding="utf-8")
    before = target.read_bytes()

    server = create_server(kb, 0, mode="collaboration")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        req = Request(
            base + "/api/mail/knowledge/toggle",
            data=json.dumps({"path": "wiki/a.md", "enabled": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(req, timeout=5)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert target.read_bytes() == before, "写端点已移除，文件不应该被改动"


# ── 主视图画的是关系网（2026-09-22）───────────────────────────────────
#
# 图例列的是**关系类型**，主视图原来画的是**目录从属**（中心 → 域 → 簇 → 点），
# 两者对不上：读者会以为那些线是知识关系。更具体的一处是「簇 → 点」那条层级线
# 借用了该点第一条关系的颜色键，于是图例里关掉某一类关系，层级线也跟着消失 ——
# 一条只表示从属的线，不该参与关系的筛选。
# 现在：知识点直接挂在知识域下（簇降为副标签），线只有两种 ——
# 分组联线（__group）与知识关系（后端边表，按类型着色）。

def test_frontend_serves_modular_graph_assets(kb):
    server = create_server(kb, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for name in ("force-layout.js", "tag-graph.js", "mail-view-model.js",
                     "knowledge-browser.js", "knowledge-navigation.js", "workspace-shell.js", "knowledge-heatmap.js"):
            with urlopen(base + "/" + name, timeout=5) as response:
                assert response.status == 200
                assert "javascript" in response.headers["Content-Type"]
                assert response.read()
        for name in ("tag-graph.css", "knowledge-browser.css", "knowledge-reading.css", "knowledge-workspace.css", "workspace-shell.css"):
            with urlopen(base + "/" + name, timeout=5) as response:
                assert response.status == 200
                assert "text/css" in response.headers["Content-Type"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_reader_omits_a_repeated_title_without_changing_the_document(kb):
    from knowledge_studio.mail_web import _memory_item, render_wiki_page

    document = "---\ntitle: Reader title\n---\n\n# Reader title\n\nOriginal body.\n"
    path = kb / "wiki" / "reader.md"
    path.write_text(document, encoding="utf-8")
    item = _memory_item(kb, "wiki/reader.md", full=True)
    assert item["markdown"] == document
    assert "<h2>Reader title</h2>" not in render_wiki_page(item)
    assert path.read_text(encoding="utf-8") == document
