"""Focused tests for feishu_worker.review_events module.

Covers: subprocess import isolation, parse_review_reply, event_reviewed_at,
decoded_raw_message_content, find_candidate_state_for_reply,
record_review_event, read_review_record_after_write, review_candidate
state machine (reject idempotent, accept promotion), process_next_review,
apply_review_reply_event, reconcile_historical_review_reply,
apply_review_event_with_fallback, consume_review_events.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from feishu_worker.review_events import (  # noqa: E402
    REVIEW_ACTIONS,
    REVIEW_ACTION_RE,
    apply_review_event_with_fallback,
    apply_review_reply_event,
    consume_review_events,
    decoded_raw_message_content,
    event_reviewed_at,
    find_candidate_state_for_reply,
    parse_review_reply,
    pending_review_states_in_chat,
    process_next_review,
    promote_candidate_document,
    raw_message,
    read_review_record_after_write,
    reconcile_historical_review_reply,
    record_review_event,
    review_candidate,
    review_states_for_prompt,
)
from feishu_worker.io_utils import atomic_write_json


# ── Subprocess import isolation ────────────────────────────────────────


def test_review_events_module_never_imports_feishu_base_worker():
    """Fresh subprocess confirms review_events.py has zero feishu_base_worker deps."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""\
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(r'{}').parents[0]))
            # Import review_events — must succeed without pulling in feishu_base_worker
            from feishu_worker import review_events
            print("OK")
        """.format(str(SCRIPTS)))],
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK" in result.stdout


# ── Constants ──────────────────────────────────────────────────────────


def test_review_actions_set():
    assert REVIEW_ACTIONS == {"accept", "edit", "reject", "defer"}


def test_review_action_re_matches():
    assert REVIEW_ACTION_RE.search("accept 文章有价值")
    assert REVIEW_ACTION_RE.search("文章有价值，accept")
    assert REVIEW_ACTION_RE.search("`defer`")
    assert not REVIEW_ACTION_RE.search("acceptance")


# ── parse_review_reply ─────────────────────────────────────────────────


def test_parse_review_reply_accepts_action_before_or_after_comment():
    assert parse_review_reply("accept 文章有价值") == ("accept", "文章有价值")
    assert parse_review_reply("文章有价值，accept") == ("accept", "文章有价值")
    assert parse_review_reply("接受") == ("accept", "")
    assert parse_review_reply("拒绝，方向不匹配") == ("reject", "方向不匹配")
    assert parse_review_reply("`defer`") == ("defer", "")


def test_parse_review_reply_rejects_missing_or_conflicting_action():
    for content in ("文章有价值", "accept but reject"):
        with pytest.raises(ValueError):
            parse_review_reply(content)


def test_parse_review_reply_strips_punctuation_from_comment():
    action, comment = parse_review_reply("accept 很好！。")
    assert action == "accept"
    assert comment == "很好"


# ── event_reviewed_at ──────────────────────────────────────────────────


def test_event_reviewed_at_parses_milliseconds():
    result = event_reviewed_at("1784730000000")
    assert "2026" in result


def test_event_reviewed_at_falls_back_on_invalid():
    result = event_reviewed_at(None)
    assert ":" in result  # time string


# ── decoded_raw_message_content ────────────────────────────────────────


def test_decoded_raw_message_content_text():
    msg = {"body": {"content": json.dumps({"text": "hello"})}}
    assert decoded_raw_message_content(msg) == "hello"


def test_decoded_raw_message_content_fallback():
    msg = {"body": {"content": json.dumps({"content": "world"})}}
    assert decoded_raw_message_content(msg) == "world"


def test_decoded_raw_message_content_plain():
    msg = {"body": {"content": "plain text"}}
    assert decoded_raw_message_content(msg) == "plain text"


def test_decoded_raw_message_content_empty():
    assert decoded_raw_message_content({}) == ""


# ── find_candidate_state_for_reply ─────────────────────────────────────


def test_find_candidate_state_for_reply_matches_by_message_id(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    state = {
        "record_id": "rec_1",
        "review_notification": {
            "status": "sent",
            "message_id": "om_prompt",
            "chat_id": "oc_chat",
        },
    }
    state_path = state_dir / "rec_1.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    event = {"reply_to": "om_prompt", "chat_id": "oc_chat"}
    result = find_candidate_state_for_reply(event, root=tmp_path)
    assert result is not None
    assert result[0] == state_path


def test_find_candidate_state_for_reply_requires_sender_match(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    state = {
        "record_id": "rec_1",
        "review_notification": {
            "status": "sent",
            "message_id": "om_prompt",
            "recipient": "ou_alice",
        },
    }
    (state_dir / "rec_1.json").write_text(json.dumps(state), encoding="utf-8")

    event = {"reply_to": "om_prompt", "sender_id": "ou_bob"}
    result = find_candidate_state_for_reply(event, root=tmp_path)
    assert result is None


def test_find_candidate_state_for_reply_requires_chat_match(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    state = {
        "record_id": "rec_1",
        "review_notification": {
            "status": "sent",
            "message_id": "om_prompt",
            "chat_id": "oc_chat_a",
        },
    }
    (state_dir / "rec_1.json").write_text(json.dumps(state), encoding="utf-8")

    event = {"reply_to": "om_prompt", "chat_id": "oc_chat_b"}
    result = find_candidate_state_for_reply(event, root=tmp_path)
    assert result is None


def test_find_candidate_state_for_reply_skips_unsent(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    state = {
        "record_id": "rec_1",
        "review_notification": {
            "status": "skipped",
            "message_id": "om_prompt",
        },
    }
    (state_dir / "rec_1.json").write_text(json.dumps(state), encoding="utf-8")

    event = {"reply_to": "om_prompt"}
    result = find_candidate_state_for_reply(event, root=tmp_path)
    assert result is None


# ── record_review_event ────────────────────────────────────────────────


def test_record_review_event_appends_and_persists(tmp_path):
    state_path = tmp_path / "state.json"
    state: dict = {"record_id": "rec_1"}
    atomic_write_json(state_path, state)

    event = {
        "message_id": "om_reply",
        "event_id": "evt_1",
        "sender_id": "ou_user",
        "reply_to": "om_prompt",
        "root_id": "om_prompt",
        "create_time": "1784730000000",
        "correlation_method": "reply_context",
    }
    record_review_event(state_path, state, event, action="accept", comment="good")

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(saved["review_reply_events"]) == 1
    receipt = saved["review_reply_events"][0]
    assert receipt["message_id"] == "om_reply"
    assert receipt["action"] == "accept"
    assert receipt["comment"] == "good"
    assert receipt["correlation_method"] == "reply_context"


def test_record_review_event_initializes_empty_receipts(tmp_path):
    state_path = tmp_path / "state.json"
    state: dict = {"record_id": "rec_1"}
    atomic_write_json(state_path, state)

    event = {"message_id": "om_1", "create_time": "1784730000000"}
    record_review_event(state_path, state, event, action="reject", comment="bad")

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(saved["review_reply_events"]) == 1


# ── read_review_record_after_write ─────────────────────────────────────


def test_read_review_record_after_write_retries_stale_snapshot(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )
    records = iter([
        {"record_id": "rec_1", "fields": {"审核动作": None}},
        {"record_id": "rec_1", "fields": {"审核动作": ["accept"]}},
    ])

    def _fake_get(_config, _record_id):
        return next(records)

    result = read_review_record_after_write(
        config, "rec_1", "accept", root=tmp_path, _get_fn=_fake_get,
    )
    from feishu_worker.io_utils import scalar_cell
    assert scalar_cell(result["fields"]["审核动作"]) == "accept"


# ── review_candidate (reject idempotent) ───────────────────────────────


CANDIDATE_DOC = textwrap.dedent("""\
    ---
    title: "Base review Candidate"
    draft_type: strategy
    draft_area: computing
    source_pages: []
    drafted_at: "2026-07-22"
    status: draft
    tags: "feishu, learning-loop"
    ---

    # 我对它的理解

    飞书多维表格是本轮 POC 的入口、状态机与人工审核控制面。Worker 负责确定性状态转换，Agent 负责需要判断的 Teach-back，审核通过后才允许晋升 Wiki。
""")


def test_reject_review_is_idempotent(tmp_path):
    from feishu_worker.config import WorkerConfig

    candidate = tmp_path / "drafts" / "base-review-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    atomic_write_json(
        tmp_path / ".oks" / "candidates" / "rec_1.json",
        {
            "candidate_id": "base-review-candidate",
            "candidate_path": "drafts/base-review-candidate.md",
            "review_history": [],
            "last_review_fingerprint": None,
        },
    )
    fields = {
        "候选ID": "base-review-candidate",
        "候选内容": "这是用户看到并拒绝的候选内容，因为它偏离了飞书 Base 主循环的真正验收目标。" * 3,
        "审核动作": "reject",
        "审核意见": "方向偏离，不晋升 Wiki。",
        "修改类型": ["方向偏离"],
        "审核时间": "2026-07-22 00:10:00",
    }
    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
    )
    updates = []
    _update = lambda _c, _r, patch: updates.append(patch) or {}

    first = review_candidate(
        config, {"record_id": "rec_1", "fields": fields},
        root=tmp_path, _update_fn=_update,
    )
    second = review_candidate(
        config, {"record_id": "rec_1", "fields": fields},
        root=tmp_path, _update_fn=_update,
    )

    assert first["processed"] is True
    assert first["action"] == "reject"
    assert updates == [{
        "运行状态": "已拒绝", "Wiki状态": "rejected", "Wiki路径": None,
        "审核时间": "2026-07-22 00:10:00",
    }]
    # Verify candidate document status changed
    from feishu_worker.candidate import parse_candidate_document
    metadata, _body = parse_candidate_document(candidate.read_text(encoding="utf-8"))
    assert metadata["status"] == "rejected"
    assert metadata["review"]["lesson"] == "方向偏离，不晋升 Wiki。"
    assert second == {"processed": False, "reason": "review_already_processed", "record_id": "rec_1"}


# ── review_candidate (defer) ───────────────────────────────────────────


def test_defer_review_resets_to_pending(tmp_path):
    from feishu_worker.config import WorkerConfig

    candidate = tmp_path / "drafts" / "defer-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    atomic_write_json(
        tmp_path / ".oks" / "candidates" / "rec_defer.json",
        {
            "candidate_id": "defer-candidate",
            "candidate_path": "drafts/defer-candidate.md",
            "review_history": [],
            "last_review_fingerprint": None,
        },
    )
    fields = {
        "候选ID": "defer-candidate",
        "候选内容": "这是用户选择暂缓的 Teach-back 内容。" * 5,
        "审核动作": "defer",
        "审核意见": "",
        "审核时间": "2026-07-22 00:30:00",
    }
    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
    )
    updates = []
    _update = lambda _c, _r, patch: updates.append(patch) or {}

    result = review_candidate(
        config, {"record_id": "rec_defer", "fields": fields},
        root=tmp_path, _update_fn=_update,
    )

    assert result["processed"] is True
    assert result["action"] == "defer"
    assert updates[-1]["运行状态"] == "候选待审"
    assert updates[-1]["Wiki状态"] == "review_pending"


# ── review_candidate (edit) ────────────────────────────────────────────


def test_edit_review_sets_needs_human_status(tmp_path):
    from feishu_worker.config import WorkerConfig

    candidate = tmp_path / "drafts" / "edit-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    atomic_write_json(
        tmp_path / ".oks" / "candidates" / "rec_edit.json",
        {
            "candidate_id": "edit-candidate",
            "candidate_path": "drafts/edit-candidate.md",
            "review_history": [],
            "last_review_fingerprint": None,
        },
    )
    fields = {
        "候选ID": "edit-candidate",
        "候选内容": "这是用户需要修改的 Teach-back 内容，需要补充更多细节。" * 3,
        "审核动作": "edit",
        "审核意见": "需要补充示例代码",
        "审核时间": "2026-07-22 00:40:00",
    }
    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
    )
    updates = []
    _update = lambda _c, _r, patch: updates.append(patch) or {}

    result = review_candidate(
        config, {"record_id": "rec_edit", "fields": fields},
        root=tmp_path, _update_fn=_update,
    )

    assert result["processed"] is True
    assert result["action"] == "edit"
    assert updates[-1]["运行状态"] == "需人工"
    assert updates[-1]["Wiki状态"] == "candidate"


# ── process_next_review ────────────────────────────────────────────────


def test_process_next_review_finds_first_pending(tmp_path):
    from feishu_worker.config import WorkerConfig

    candidate = tmp_path / "drafts" / "pr-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    atomic_write_json(
        tmp_path / ".oks" / "candidates" / "rec_pr.json",
        {
            "candidate_id": "pr-candidate",
            "candidate_path": "drafts/pr-candidate.md",
            "review_history": [],
            "last_review_fingerprint": None,
        },
    )

    def _fake_list(_config, _limit):
        return [
            {"record_id": "rec_pr", "fields": {"审核动作": "defer", "运行状态": "候选待审",
             "候选ID": "pr-candidate", "候选内容": "这是用户选择暂缓的 Teach-back 内容。" * 5,
             "审核时间": "2026-07-22 00:30:00", "审核意见": ""}},
        ]

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
    )
    _update = lambda _c, _r, _patch: {}

    result = process_next_review(
        config, root=tmp_path, _list_fn=_fake_list, _update_fn=_update,
    )
    assert result["processed"] is True
    assert result["action"] == "defer"


def test_process_next_review_skips_promoted(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )

    def _fake_list(_config, _limit):
        return [
            {"record_id": "rec_done", "fields": {"审核动作": "accept", "运行状态": "已晋升"}},
        ]

    result = process_next_review(config, root=tmp_path, _list_fn=_fake_list)
    assert result["processed"] is False
    assert result["reason"] == "no_pending_reviews"


# ── apply_review_reply_event ───────────────────────────────────────────


def test_apply_review_reply_event_processes_and_is_idempotent(tmp_path):
    from feishu_worker.config import WorkerConfig

    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    candidate = tmp_path / "drafts" / "reply-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    state_path = state_dir / "rec_reply.json"
    atomic_write_json(
        state_path,
        {
            "record_id": "rec_reply",
            "candidate_id": "reply-candidate",
            "candidate_path": "drafts/reply-candidate.md",
            "revision": 3,
            "review_history": [],
            "last_review_fingerprint": None,
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
        review_recipient_user_id="ou_reviewer",
    )
    updates = []
    _update = lambda _c, _r, patch: updates.append((_r, patch)) or {}
    _get = lambda _c, _r: {"record_id": _r, "fields": {
        "审核动作": "defer", "候选ID": "reply-candidate", "候选内容": "这是用户选择暂缓的 Teach-back 内容。" * 5,
        "审核意见": "", "审核时间": "2026-07-22 00:30:00",
    }}

    event = {
        "event_id": "evt_1",
        "message_id": "om_reply",
        "reply_to": "om_prompt",
        "root_id": "om_prompt",
        "chat_id": "oc_personal",
        "chat_type": "p2p",
        "sender_id": "ou_reviewer",
        "sender_type": "user",
        "message_type": "text",
        "content": "defer 暂缓处理",
        "create_time": "1784730000000",
    }

    first = apply_review_reply_event(
        config, event, root=tmp_path, _update_fn=_update, _get_fn=_get,
    )
    second = apply_review_reply_event(
        config, event, root=tmp_path, _update_fn=_update, _get_fn=_get,
    )

    assert first["processed"] is True
    assert first["record_id"] == "rec_reply"
    assert first["action"] == "defer"
    assert updates[0][1]["审核动作"] == "defer"
    assert "暂缓处理" in updates[0][1]["审核意见"]
    assert second["reason"] == "review_message_already_processed"


def test_apply_review_reply_rejects_non_p2p(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )
    event = {"message_id": "om_1", "chat_type": "group", "sender_type": "user"}
    result = apply_review_reply_event(config, event, root=tmp_path)
    assert result["reason"] == "not_personal_user_message"


def test_apply_review_reply_requires_comment_for_reject(tmp_path):
    from feishu_worker.config import WorkerConfig

    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    candidate = tmp_path / "drafts" / "rc-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE_DOC, encoding="utf-8")
    atomic_write_json(
        state_dir / "rec_rc.json",
        {
            "record_id": "rec_rc",
            "candidate_id": "rc-candidate",
            "candidate_path": "drafts/rc-candidate.md",
            "revision": 1,
            "review_history": [],
            "last_review_fingerprint": None,
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )
    event = {
        "message_id": "om_reply",
        "reply_to": "om_prompt",
        "chat_id": "oc_personal",
        "chat_type": "p2p",
        "sender_id": "ou_reviewer",
        "sender_type": "user",
        "message_type": "text",
        "content": "reject",
    }
    result = apply_review_reply_event(config, event, root=tmp_path)
    assert result["reason"] == "review_comment_required"


# ── pending_review_states_in_chat ──────────────────────────────────────


def test_pending_review_states_in_chat_filters_promoted(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    atomic_write_json(state_dir / "active.json", {
        "review_notification": {"status": "sent", "chat_id": "oc_chat"},
    })
    atomic_write_json(state_dir / "promoted.json", {
        "last_review_action": "accept",
        "review_notification": {"status": "sent", "chat_id": "oc_chat"},
    })

    states = pending_review_states_in_chat("oc_chat", root=tmp_path)
    assert len(states) == 1
    assert states[0][0].name == "active.json"


# ── review_states_for_prompt ───────────────────────────────────────────


def test_review_states_for_prompt_matches_exact_message_id(tmp_path):
    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    atomic_write_json(state_dir / "match.json", {
        "review_notification": {"status": "sent", "chat_id": "oc_chat", "message_id": "om_A"},
    })
    atomic_write_json(state_dir / "nomatch.json", {
        "review_notification": {"status": "sent", "chat_id": "oc_chat", "message_id": "om_B"},
    })

    states = review_states_for_prompt("oc_chat", "om_A", root=tmp_path)
    assert len(states) == 1
    assert states[0][0].name == "match.json"


# ── reconcile_historical_review_reply ──────────────────────────────────


def test_reconcile_historical_review_uses_p2p_sequence_fallback(tmp_path):
    from feishu_worker.config import WorkerConfig

    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    atomic_write_json(
        state_dir / "rec_reply.json",
        {
            "record_id": "rec_reply",
            "candidate_id": "candidate-1",
            "revision": 1,
            "review_history": [],
            "last_review_fingerprint": None,
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )

    messages = {
        "om_prompt": {
            "message_id": "om_prompt",
            "chat_id": "oc_personal",
            "message_position": "2",
            "create_time": "1784730000000",
        },
        "om_reply": {
            "message_id": "om_reply",
            "chat_id": "oc_personal",
            "message_position": "3",
            "create_time": "1784730001000",
            "msg_type": "text",
            "sender": {"id": "ou_reviewer", "sender_type": "user"},
            "body": {"content": json.dumps({"text": "accept, useful"})},
        },
    }
    _lark = lambda _c, *_a: messages.get(
        next((str(a) for a in _a if str(a).startswith("om_")), ""), {}
    )

    events = []
    def _fake_apply_reply(_config, event):
        events.append(event)
        return {"processed": True}
    def _fake_raw_msg(_config, message_id):
        return messages.get(message_id, {})

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, knowledge_root=tmp_path,
    )

    result = reconcile_historical_review_reply(
        config,
        prompt_message_id="om_prompt",
        reply_message_id="om_reply",
        root=tmp_path,
        _raw_message_fn=_fake_raw_msg,
        _apply_reply_fn=_fake_apply_reply,
    )

    assert result["processed"] is True
    assert result["correlation_method"] == "p2p_sequence_fallback"
    assert events[0]["reply_to"] == "om_prompt"
    assert events[0]["content"] == "accept, useful"


def test_reconcile_historical_review_rejects_nonadjacent(tmp_path):
    from feishu_worker.config import WorkerConfig

    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    atomic_write_json(
        state_dir / "rec_reply.json",
        {
            "record_id": "rec_reply",
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )

    messages = {
        "om_prompt": {
            "message_id": "om_prompt",
            "chat_id": "oc_personal",
            "message_position": "2",
            "create_time": "1784730000000",
        },
        "om_reply": {
            "message_id": "om_reply",
            "chat_id": "oc_personal",
            "message_position": "4",
            "create_time": "1784730001000",
            "msg_type": "text",
            "sender": {"id": "ou_reviewer", "sender_type": "user"},
            "body": {"content": json.dumps({"text": "accept"})},
        },
    }

    def _fake_raw_msg(_config, message_id):
        return messages.get(message_id, {})

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="immediately follow"):
        reconcile_historical_review_reply(
            config,
            prompt_message_id="om_prompt",
            reply_message_id="om_reply",
            root=tmp_path,
            _raw_message_fn=_fake_raw_msg,
        )


def test_reconcile_historical_review_is_idempotent(tmp_path):
    from feishu_worker.config import WorkerConfig

    state_dir = tmp_path / ".oks" / "candidates"
    state_dir.mkdir(parents=True)
    atomic_write_json(
        state_dir / "rec_reply.json",
        {
            "record_id": "rec_reply",
            "last_review_action": "accept",
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
            "review_reply_events": [
                {"message_id": "om_reply", "correlation_method": "p2p_sequence_fallback"}
            ],
        },
    )

    messages = {
        "om_prompt": {"message_id": "om_prompt", "chat_id": "oc_personal"},
        "om_reply": {"message_id": "om_reply", "chat_id": "oc_personal"},
    }

    def _fake_raw_msg(_config, message_id):
        return messages.get(message_id, {})

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )

    result = reconcile_historical_review_reply(
        config,
        prompt_message_id="om_prompt",
        reply_message_id="om_reply",
        root=tmp_path,
        _raw_message_fn=_fake_raw_msg,
    )

    assert result["processed"] is False
    assert result["reason"] == "review_message_already_processed"
    assert result["correlation_method"] == "p2p_sequence_fallback"


# ── apply_review_event_with_fallback ───────────────────────────────────


def test_apply_review_event_with_fallback_triggers_reconcile(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )

    reconciled = []
    _apply_reply = lambda _c, _e: {
        "processed": False, "reason": "unknown_review_notification",
        "message_id": "om_reply",
    }
    _pending = lambda _chat_id: [(
        tmp_path / "state.json",
        {"review_notification": {"status": "sent", "message_id": "om_prompt", "chat_id": "oc_personal"}},
    )]
    _reconcile = lambda _c, **kw: reconciled.append(kw) or {
        "processed": True, "correlation_method": "p2p_sequence_fallback",
    }

    result = apply_review_event_with_fallback(
        config,
        {"message_id": "om_reply", "chat_id": "oc_personal"},
        root=tmp_path,
        _apply_reply_fn=_apply_reply,
        _pending_fn=_pending,
        _reconcile_fn=_reconcile,
    )

    assert result["processed"] is True
    assert reconciled == [{"prompt_message_id": "om_prompt", "reply_message_id": "om_reply"}]


def test_apply_review_event_with_fallback_no_guess_between_candidates(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )

    _apply_reply = lambda _c, _e: {
        "processed": False, "reason": "unknown_review_notification",
        "message_id": "om_reply",
    }
    # Two pending candidates — fallback must not guess
    _pending = lambda _chat_id: [
        (tmp_path / "a.json", {"review_notification": {"status": "sent", "message_id": "om_A", "chat_id": "oc_personal"}}),
        (tmp_path / "b.json", {"review_notification": {"status": "sent", "message_id": "om_B", "chat_id": "oc_personal"}}),
    ]

    result = apply_review_event_with_fallback(
        config,
        {"message_id": "om_reply", "chat_id": "oc_personal"},
        root=tmp_path,
        _apply_reply_fn=_apply_reply,
        _pending_fn=_pending,
    )

    assert result["processed"] is False
    assert result["reason"] == "unknown_review_notification"


# ── consume_review_events ──────────────────────────────────────────────


def test_consume_review_events_uses_filtered_consumer(tmp_path, monkeypatch):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path, review_recipient_user_id="ou_reviewer",
    )
    event = {"message_id": "om_reply", "chat_type": "p2p", "sender_type": "user"}
    commands = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or subprocess.CompletedProcess(command, 0, json.dumps(event) + "\n", "[event] ready\n"),
    )

    processed_events = []
    _apply_event = lambda _c, e: processed_events.append(e) or {"processed": True, "message_id": e["message_id"]}

    result = consume_review_events(
        config, max_events=1, timeout="30s", root=tmp_path,
        _apply_event_fn=_apply_event,
    )

    assert result["events_received"] == 1
    assert result["outcomes"][0]["processed"] is True
    assert commands[0][1:4] == ["event", "consume", "im.message.receive_v1"]
    assert commands[0][commands[0].index("--as") + 1] == "bot"
    assert commands[0][commands[0].index("--max-events") + 1] == "1"
    assert "ou_reviewer" in commands[0][commands[0].index("--jq") + 1]


def test_consume_review_events_rejects_zero_max_events(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t", table_id="tbl", lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )
    with pytest.raises(ValueError, match="max_events must be at least 1"):
        consume_review_events(config, max_events=0, timeout="30s", root=tmp_path)
