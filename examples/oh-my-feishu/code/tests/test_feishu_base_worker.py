import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import feishu_base_worker as worker


def candidate_document(title="Base review Candidate"):
    return f'''---
title: "{title}"
draft_type: strategy
draft_area: computing
source_pages: []
drafted_at: "2026-07-22"
status: draft
tags: "feishu, learning-loop"
---

# 我对它的理解

飞书多维表格是本轮 POC 的入口、状态机与人工审核控制面。Worker 负责确定性状态转换，Agent 负责需要判断的 Teach-back，审核通过后才允许晋升 Wiki。
'''


def test_extract_url_from_labeled_capture():
    assert worker.extract_url("[test] https://example.com/a?b=1。") == "https://example.com/a?b=1"
    assert worker.extract_url("plain note") is None


def test_candidate_requires_pending_or_explicit_retry():
    assert worker.is_candidate({"fields": {"运行状态": "待处理", "重试": False}})
    assert worker.is_candidate({"fields": {"运行状态": ["待处理"], "重试": False}})
    assert worker.is_candidate({"fields": {"运行状态": "最终失败", "重试": True}})
    assert not worker.is_candidate({"fields": {"运行状态": "Raw就绪", "重试": False}})


def test_expired_lease_can_be_reclaimed_but_active_lease_cannot():
    now = worker.datetime(2026, 7, 19, 12, 0, 0, tzinfo=worker.timezone.utc)
    expired = {"fields": {"运行状态": "已领取", "重试": False, "租约到期": "2026-07-19 11:59:59"}}
    active = {"fields": {"运行状态": "已领取", "重试": False, "租约到期": "2026-07-19 12:00:01"}}
    assert worker.is_candidate(expired, now=now)
    assert not worker.is_candidate(active, now=now)


def test_claim_next_record_writes_visible_lease(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, lease_seconds=60
    )
    record = {"record_id": "rec_lease", "fields": {"运行状态": "待处理", "重试": False}}
    updates = []
    monkeypatch.setattr(worker, "list_records", lambda *_: [record])
    monkeypatch.setattr(worker, "update_record", lambda _c, record_id, patch: updates.append((record_id, patch)) or {})
    monkeypatch.setattr(worker, "local_claim_lock", lambda _config: worker.contextmanager(lambda: (yield))())

    claimed = worker.claim_next_record(config)

    assert claimed is not None
    assert claimed[0] == record
    assert claimed[1].startswith("run-")
    assert updates[0][0] == "rec_lease"
    assert updates[0][1]["运行状态"] == "已领取"
    assert updates[0][1]["租约所有者"]
    assert updates[0][1]["租约到期"]


def test_claim_record_only_reads_and_claims_the_explicit_record(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        lease_seconds=60,
    )
    requested = []
    updates = []
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda _config, record_id, projection: requested.append((record_id, projection))
        or {"record_id": record_id, "fields": {"运行状态": "待处理", "重试": False}},
    )
    monkeypatch.setattr(
        worker,
        "update_record",
        lambda _config, record_id, patch: updates.append((record_id, patch)) or {},
    )
    monkeypatch.setattr(
        worker,
        "local_claim_lock",
        lambda _config: worker.contextmanager(lambda: (yield))(),
    )

    claimed = worker.claim_record(config, "rec_selected")

    assert claimed is not None
    assert requested[0][0] == "rec_selected"
    # CAPTURE_FIELDS may vary; verify key fields are requested
    assert "内容" in requested[0][1]
    assert "运行状态" in requested[0][1]
    assert updates[0][0] == "rec_selected"
    assert updates[0][1]["运行状态"] == "已领取"


def test_attachment_change_changes_capture_hash():
    original = {"内容": "https://example.com", "思考": "note", "附件": []}
    changed = {
        **original,
        "附件": [{"file_token": "file_1", "name": "diagram.png", "size": 12}],
    }
    assert worker.capture_content_hash(original) != worker.capture_content_hash(changed)


def test_question_is_preserved_in_user_note_and_capture_hash():
    original = {
        "内容": "https://example.com",
        "思考": "值得学习",
        "希望解决的问题": "先学什么？",
    }
    changed = {**original, "希望解决的问题": "学完能做什么？"}

    assert worker.capture_user_note(original) == "值得学习\n\n重点问题：先学什么？"
    assert worker.capture_content_hash(original) != worker.capture_content_hash(changed)

    current = {"思考": "值得学习", "重点问题（可选）": "现在先做什么？"}
    assert worker.capture_user_note(current) == "值得学习\n\n重点问题：现在先做什么？"


def test_downloaded_attachment_sha_changes_final_envelope_hash(tmp_path):
    fields = {
        "内容": "attachment only",
        "思考": "note",
        "附件": [{"file_token": "file_1", "name": "sample.txt", "size": 3}],
    }
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    capture = worker.capture_envelope(config, "rec_1", fields)
    before = capture["content_hash"]
    capture["attachments"][0]["sha256"] = "a" * 64
    assert worker.envelope_content_hash(capture) != before


def test_attachment_capability_routes_existing_adapters():
    assert worker.attachment_capability(Path("paper.pdf")) == ("pdf.mineru", "text")
    assert worker.attachment_capability(Path("scan.png")) == ("image.rapidocr", "ocr")
    assert worker.attachment_capability(Path("notes.txt")) == ("office.markitdown", "text")


def test_content_type_extension_supports_direct_pdf_without_url_suffix():
    assert worker.content_type_extension("application/pdf") == ".pdf"
    assert worker.content_type_extension("application/pdf; charset=binary") == ".pdf"
    assert worker.content_type_extension("application/x-unknown") == ""


def test_source_snapshot_changes_final_envelope_hash(tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    capture = worker.capture_envelope(config, "rec_1", {"内容": "https://example.com/paper.pdf", "思考": "note"})
    before = capture["content_hash"]
    capture["source_snapshot"] = {
        "final_url": "https://example.com/paper.pdf",
        "content_type": "application/pdf",
        "size": 123,
        "sha256": "a" * 64,
    }
    assert worker.envelope_content_hash(capture) != before


def test_attachment_download_passes_repository_relative_output(monkeypatch, tmp_path):
    output = worker.ROOT / ".oks" / "runs" / "test-relative-output"
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    commands = []
    monkeypatch.setattr(worker, "lark_json", lambda _config, *args: commands.append(args) or {})
    worker.download_attachments(config, "rec_1", output)
    output_arg = commands[0][commands[0].index("--output") + 1]
    assert output_arg == "./.oks/runs/test-relative-output"


def test_list_records_maps_projected_rows(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    monkeypatch.setattr(
        worker,
        "lark_json",
        lambda *_args: {
            "data": {
                "fields": ["内容", "运行状态", "重试"],
                "data": [["https://example.com", "待处理", False]],
                "record_id_list": ["rec_1"],
            }
        },
    )
    assert worker.list_records(config) == [
        {
            "record_id": "rec_1",
            "fields": {"内容": "https://example.com", "运行状态": "待处理", "重试": False},
        }
    ]


def test_publish_candidate_requires_raw_and_writes_visible_review_state(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    raw = tmp_path / "raw-bundle"
    raw.mkdir()
    (raw / "bundle.json").write_text(
        json.dumps(
            {
                "schema_version": "raw-multimodal/v0.2",
                "capture_id": "capture_1",
                "bundle_id": "bundle:capture_1:run_1",
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "base-review-candidate.md"
    source.write_text(candidate_document(), encoding="utf-8")
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    updates = []
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {
            "record_id": "rec_1",
            "fields": {"运行状态": "Raw就绪", "Raw Bundle": str(raw), "运行ID": "run_1"},
        },
    )
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    notifications = []
    monkeypatch.setattr(
        worker,
        "send_candidate_review_notification",
        lambda *_args, **kwargs: notifications.append(kwargs)
        or {"status": "sent", "message_id": "om_1"},
    )

    state = worker.publish_candidate(config, "rec_1", source)

    assert state["candidate_id"] == "base-review-candidate"
    assert state["revision"] == 1
    assert (tmp_path / state["candidate_path"]).is_file()
    assert updates[-1]["候选ID"] == "base-review-candidate"
    assert updates[-1]["Wiki状态"] == "review_pending"
    assert updates[-1]["运行状态"] == "候选待审"
    assert "飞书多维表格" in updates[-1]["候选内容"]
    assert state["review_notification"]["status"] == "sent"
    assert notifications[0]["record_id"] == "rec_1"
    metadata, _body = worker.parse_candidate_document(
        (tmp_path / state["candidate_path"]).read_text(encoding="utf-8")
    )
    execution_trace = metadata["traces"][0]
    assert execution_trace == {
        "kind": "execution",
        "id": "run_1",
        "capture_id": "capture_1",
        "bundle_id": "bundle:capture_1:run_1",
        "path": "raw-bundle",
    }


def test_publish_candidate_writes_draft_to_configured_personal_root(monkeypatch, tmp_path):
    studio_root = tmp_path / "studio"
    personal_root = tmp_path / "personal"
    raw = personal_root / "raw" / "bundle"
    raw.mkdir(parents=True)
    (raw / "bundle.json").write_text(
        json.dumps({"capture_id": "capture_1", "bundle_id": "bundle_1"}),
        encoding="utf-8",
    )
    source = tmp_path / "personal-candidate.md"
    source.write_text(candidate_document(), encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", studio_root)
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        raw.parent,
        knowledge_root=personal_root,
    )
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {
            "record_id": "rec_personal",
            "fields": {"运行状态": "Raw就绪", "Raw Bundle": str(raw), "运行ID": "run_1"},
        },
    )
    monkeypatch.setattr(worker, "update_record", lambda *_: {})
    monkeypatch.setattr(
        worker,
        "send_candidate_review_notification",
        lambda *_args, **_kwargs: {"status": "disabled"},
    )

    state = worker.publish_candidate(config, "rec_personal", source)

    candidate = personal_root / "drafts" / "personal-candidate.md"
    assert candidate.is_file()
    assert state["candidate_path"] == str(candidate)
    assert Path(state["candidate_path"]).is_absolute()


def test_promote_candidate_document_uses_configured_personal_root(monkeypatch, tmp_path):
    studio_root = tmp_path / "studio"
    personal_root = tmp_path / "personal"
    candidate = personal_root / "drafts" / "personal-candidate.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(candidate_document(), encoding="utf-8")
    # Ensure knowledge_studio can be imported even when ROOT is monkeypatched
    sys.path.insert(0, str(Path(worker.__file__).resolve().parents[1] / "cli"))
    monkeypatch.setattr(worker, "ROOT", studio_root)
    monkeypatch.setenv("OKS_ROOT", str(studio_root))

    wiki_path = worker.promote_candidate_document(
        candidate,
        worker.parse_candidate_document(candidate.read_text(encoding="utf-8"))[1],
        {
            "outcome": "success",
            "decision_correct": True,
            "lesson": "验收通过",
            "reviewed_at": "2026-07-24 12:00:00",
        },
        knowledge_root=personal_root,
    )

    assert wiki_path.is_relative_to(personal_root / "wiki")
    assert wiki_path.is_file()
    assert not (studio_root / "wiki").exists()
    assert worker.os.environ["OKS_ROOT"] == str(studio_root)


def test_render_candidate_review_message_uses_agent_summary_and_questions():
    message = worker.render_candidate_review_message(
        record_id="rec_1",
        candidate_id="candidate-1",
        revision=2,
        metadata={
            "title": "控制面设计",
            "review_summary": "Base 保存审计事实，Agent 负责解释与提问。",
            "review_questions": ["这条知识是否值得保留？", "是否需要补充反例？"],
        },
        body="完整 Candidate 正文。" * 20,
        fields={"内容": "https://example.com", "思考": "如何降低审核摩擦？"},
    )

    assert "控制面设计" in message
    assert "Base 保存审计事实" in message
    assert "这条知识是否值得保留" in message
    assert "如何降低审核摩擦" in message
    assert "candidate-1" in message
    assert "revision `2`" in message


def test_review_notification_skips_without_configured_recipient(tmp_path):
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        tmp_path,
    )

    result = worker.send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={
            "candidate_id": "candidate-1",
            "revision": 1,
            "candidate_sha256": "a" * 64,
        },
        metadata={"title": "Candidate"},
        body="正文" * 50,
        fields={},
    )

    assert result == {"status": "skipped", "reason": "review_recipient_not_configured"}


def test_review_notification_sends_idempotent_personal_message(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        tmp_path,
        review_recipient_user_id="ou_user",
        review_message_identity="bot",
    )
    commands = []
    monkeypatch.setattr(
        worker,
        "lark_json",
        lambda _config, *args: commands.append(args)
        or {"data": {"message_id": "om_1"}},
    )

    result = worker.send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={
            "candidate_id": "candidate-1",
            "revision": 1,
            "candidate_sha256": "a" * 64,
        },
        metadata={"title": "Candidate", "review_summary": "摘要"},
        body="正文" * 50,
        fields={},
    )

    assert result["status"] == "sent"
    assert result["message_id"] == "om_1"
    assert commands[0][:2] == ("im", "+messages-send")
    assert commands[0][commands[0].index("--user-id") + 1] == "ou_user"
    assert commands[0][commands[0].index("--as") + 1] == "bot"
    assert len(commands[0][commands[0].index("--idempotency-key") + 1]) == 50


def test_parse_review_reply_accepts_action_before_or_after_comment():
    assert worker.parse_review_reply("accept 文章有价值") == ("accept", "文章有价值")
    assert worker.parse_review_reply("文章有价值，accept") == ("accept", "文章有价值")
    assert worker.parse_review_reply("`defer`") == ("defer", "")


def test_parse_review_reply_rejects_missing_or_conflicting_action():
    for content in ("文章有价值", "accept but reject"):
        try:
            worker.parse_review_reply(content)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid review reply accepted: {content}")


def test_personal_reply_updates_exact_linked_candidate_and_records_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    state_path = worker.candidate_state_path("rec_reply")
    worker.atomic_write_json(
        state_path,
        {
            "record_id": "rec_reply",
            "candidate_id": "candidate-1",
            "revision": 3,
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        tmp_path,
        review_recipient_user_id="ou_reviewer",
    )
    updates = []
    monkeypatch.setattr(
        worker,
        "update_record",
        lambda _config, record_id, patch: updates.append((record_id, patch)) or {},
    )
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda _config, record_id: {
            "record_id": record_id,
            "fields": {"审核动作": "accept"},
        },
    )
    monkeypatch.setattr(
        worker,
        "review_candidate",
        lambda _config, record: {
            "processed": True,
            "record_id": record["record_id"],
            "action": "accept",
        },
    )
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
        "content": "文章有价值，accept",
        "create_time": "1784730000000",
    }

    first = worker.apply_review_reply_event(config, event)
    second = worker.apply_review_reply_event(config, event)

    assert first["processed"] is True
    assert first["record_id"] == "rec_reply"
    assert first["revision"] == 3
    assert updates[0][0] == "rec_reply"
    assert updates[0][1]["审核动作"] == "accept"
    assert updates[0][1]["审核意见"] == "文章有价值"
    assert updates[0][1]["修改类型"] == "无修改"
    assert second["reason"] == "review_message_already_processed"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["review_reply_events"][0]["message_id"] == "om_reply"


def test_review_reply_requires_exact_parent_and_comment_for_reject(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    worker.atomic_write_json(
        worker.candidate_state_path("rec_reply"),
        {
            "record_id": "rec_reply",
            "candidate_id": "candidate-1",
            "revision": 1,
            "review_notification": {
                "status": "sent",
                "message_id": "om_prompt",
                "chat_id": "oc_personal",
                "recipient": "ou_reviewer",
            },
        },
    )
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        tmp_path,
    )
    base_event = {
        "message_id": "om_reply",
        "reply_to": "om_prompt",
        "chat_id": "oc_personal",
        "chat_type": "p2p",
        "sender_id": "ou_reviewer",
        "sender_type": "user",
        "message_type": "text",
        "content": "reject",
    }
    assert worker.apply_review_reply_event(config, base_event)["reason"] == "review_comment_required"
    assert worker.apply_review_reply_event(
        config,
        {**base_event, "reply_to": "om_other", "content": "reject 方向偏离"},
    )["reason"] == "unknown_review_notification"


def test_reconcile_historical_review_uses_strict_p2p_sequence_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    worker.atomic_write_json(
        worker.candidate_state_path("rec_reply"),
        {
            "record_id": "rec_reply",
            "candidate_id": "candidate-1",
            "revision": 1,
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
    monkeypatch.setattr(worker, "raw_message", lambda _config, message_id: messages[message_id])
    events = []
    monkeypatch.setattr(
        worker,
        "apply_review_reply_event",
        lambda _config, event: events.append(event) or {"processed": True},
    )
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )

    result = worker.reconcile_historical_review_reply(
        config,
        prompt_message_id="om_prompt",
        reply_message_id="om_reply",
    )

    assert result["processed"] is True
    assert result["correlation_method"] == "p2p_sequence_fallback"
    assert events[0]["reply_to"] == "om_prompt"
    assert events[0]["content"] == "accept, useful"


def test_unknown_standalone_review_automatically_uses_strict_sequence_fallback(
    monkeypatch, tmp_path
):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )
    state = {
        "review_notification": {
            "status": "sent",
            "message_id": "om_prompt",
            "chat_id": "oc_personal",
        }
    }
    monkeypatch.setattr(
        worker,
        "apply_review_reply_event",
        lambda *_args: {
            "processed": False,
            "reason": "unknown_review_notification",
            "message_id": "om_reply",
        },
    )
    monkeypatch.setattr(
        worker,
        "pending_review_states_in_chat",
        lambda chat_id: [(tmp_path / "state.json", state)]
        if chat_id == "oc_personal"
        else [],
    )
    reconciled = []
    monkeypatch.setattr(
        worker,
        "reconcile_historical_review_reply",
        lambda _config, **kwargs: reconciled.append(kwargs)
        or {"processed": True, "correlation_method": "p2p_sequence_fallback"},
    )

    result = worker.apply_review_event_with_fallback(
        config,
        {
            "message_id": "om_reply",
            "chat_id": "oc_personal",
        },
    )

    assert result["processed"] is True
    assert reconciled == [
        {
            "prompt_message_id": "om_prompt",
            "reply_message_id": "om_reply",
        }
    ]


def test_standalone_review_fallback_does_not_guess_between_candidates(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )
    monkeypatch.setattr(
        worker,
        "apply_review_reply_event",
        lambda *_args: {
            "processed": False,
            "reason": "unknown_review_notification",
            "message_id": "om_reply",
        },
    )
    monkeypatch.setattr(
        worker,
        "pending_review_states_in_chat",
        lambda _chat_id: [
            (tmp_path / "one.json", {}),
            (tmp_path / "two.json", {}),
        ],
    )

    result = worker.apply_review_event_with_fallback(
        config,
        {"message_id": "om_reply", "chat_id": "oc_personal"},
    )

    assert result["reason"] == "unknown_review_notification"


def test_review_write_read_retries_a_stale_base_snapshot(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )
    records = iter(
        [
            {"record_id": "rec_reply", "fields": {"审核动作": None}},
            {"record_id": "rec_reply", "fields": {"审核动作": ["accept"]}},
        ]
    )
    delays = []
    monkeypatch.setattr(worker, "get_record", lambda *_args: next(records))
    monkeypatch.setattr(worker.time, "sleep", lambda delay: delays.append(delay))

    record = worker.read_review_record_after_write(config, "rec_reply", "accept")

    assert worker.scalar_cell(record["fields"]["审核动作"]) == "accept"
    assert delays == [0.25]


def test_reconcile_historical_review_rejects_nonadjacent_message(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    worker.atomic_write_json(
        worker.candidate_state_path("rec_reply"),
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
    monkeypatch.setattr(worker, "raw_message", lambda _config, message_id: messages[message_id])
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )

    try:
        worker.reconcile_historical_review_reply(
            config,
            prompt_message_id="om_prompt",
            reply_message_id="om_reply",
        )
    except RuntimeError as error:
        assert "immediately follow" in str(error)
    else:
        raise AssertionError("A nonadjacent message must not be correlated as a review")


def test_reconcile_historical_review_is_idempotent_after_promotion(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    worker.atomic_write_json(
        worker.candidate_state_path("rec_reply"),
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
                {
                    "message_id": "om_reply",
                    "correlation_method": "p2p_sequence_fallback",
                }
            ],
        },
    )
    messages = {
        "om_prompt": {"message_id": "om_prompt", "chat_id": "oc_personal"},
        "om_reply": {"message_id": "om_reply", "chat_id": "oc_personal"},
    }
    monkeypatch.setattr(worker, "raw_message", lambda _config, message_id: messages[message_id])
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )

    result = worker.reconcile_historical_review_reply(
        config,
        prompt_message_id="om_prompt",
        reply_message_id="om_reply",
    )

    assert result["processed"] is False
    assert result["reason"] == "review_message_already_processed"
    assert result["correlation_method"] == "p2p_sequence_fallback"


def test_reconcile_historical_review_calls_monkeypatched_raw_message(monkeypatch, tmp_path):
    """Regression: worker monkeypatched raw_message is used transitively during reconcile."""
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    worker.atomic_write_json(
        worker.candidate_state_path("rec_reply"),
        {
            "record_id": "rec_reply",
            "candidate_id": "candidate-1",
            "revision": 1,
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
    raw_calls = []
    monkeypatch.setattr(
        worker,
        "raw_message",
        lambda _config, message_id: raw_calls.append(message_id) or messages[message_id],
    )
    monkeypatch.setattr(
        worker,
        "apply_review_reply_event",
        lambda _config, event: {"processed": True},
    )
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path
    )

    result = worker.reconcile_historical_review_reply(
        config,
        prompt_message_id="om_prompt",
        reply_message_id="om_reply",
    )

    assert result["processed"] is True
    assert result["correlation_method"] == "p2p_sequence_fallback"
    assert raw_calls == ["om_prompt", "om_reply"], (
        f"monkeypatched raw_message must be called for prompt then reply, got {raw_calls}"
    )


def test_review_listener_uses_bounded_filtered_bot_event_consumer(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base",
        "table",
        tmp_path / "lark.exe",
        tmp_path,
        tmp_path / "python.exe",
        tmp_path,
        review_recipient_user_id="ou_reviewer",
    )
    event = {"message_id": "om_reply", "chat_type": "p2p", "sender_type": "user"}
    commands = []
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or worker.subprocess.CompletedProcess(command, 0, json.dumps(event) + "\n", "[event] ready\n"),
    )
    monkeypatch.setattr(
        worker,
        "apply_review_reply_event",
        lambda _config, value: {"processed": True, "message_id": value["message_id"]},
    )

    result = worker.consume_review_events(config, max_events=1, timeout="30s")

    assert result["events_received"] == 1
    assert result["outcomes"][0]["processed"] is True
    assert commands[0][1:4] == ["event", "consume", "im.message.receive_v1"]
    assert commands[0][commands[0].index("--as") + 1] == "bot"
    assert commands[0][commands[0].index("--max-events") + 1] == "1"
    assert "ou_reviewer" in commands[0][commands[0].index("--jq") + 1]


def test_publish_candidate_refuses_record_without_raw(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    source = tmp_path / "candidate.md"
    source.write_text(candidate_document(), encoding="utf-8")
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {"record_id": "rec_1", "fields": {"运行状态": "Raw就绪", "Raw Bundle": None}},
    )

    try:
        worker.publish_candidate(config, "rec_1", source)
    except RuntimeError as error:
        assert "no Raw Bundle" in str(error)
    else:
        raise AssertionError("Candidate publication must require a Raw Bundle")


def test_reject_review_is_persistent_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    candidate = tmp_path / "drafts" / "base-review-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(candidate_document(), encoding="utf-8")
    worker.atomic_write_json(
        worker.candidate_state_path("rec_1"),
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
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})

    first = worker.review_candidate(config, {"record_id": "rec_1", "fields": fields})
    second = worker.review_candidate(config, {"record_id": "rec_1", "fields": fields})

    assert first["processed"] is True
    assert first["action"] == "reject"
    assert updates == [{
        "运行状态": "已拒绝",
        "Wiki状态": "rejected",
        "Wiki路径": None,
        "审核时间": "2026-07-22 00:10:00",
    }]
    metadata, _body = worker.parse_candidate_document(candidate.read_text(encoding="utf-8"))
    assert metadata["status"] == "rejected"
    assert metadata["review"]["lesson"] == "方向偏离，不晋升 Wiki。"
    assert second == {"processed": False, "reason": "review_already_processed", "record_id": "rec_1"}


def test_accept_review_promotes_exact_base_content(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    candidate = tmp_path / "drafts" / "base-review-candidate.md"
    candidate.parent.mkdir()
    candidate.write_text(candidate_document(), encoding="utf-8")
    worker.atomic_write_json(
        worker.candidate_state_path("rec_2"),
        {
            "candidate_id": "base-review-candidate",
            "candidate_path": "drafts/base-review-candidate.md",
            "review_history": [],
            "last_review_fingerprint": None,
        },
    )
    accepted_body = "这是用户在飞书 Base 中最终确认的 Teach-back 内容。" * 5
    fields = {
        "候选ID": "base-review-candidate",
        "候选内容": accepted_body,
        "审核动作": "accept",
        "审核意见": "验收通过。",
        "修改类型": ["无修改"],
        "审核时间": "2026-07-22 00:20:00",
    }
    wiki = tmp_path / "wiki" / "computing" / "strategies" / "accepted.md"
    wiki.parent.mkdir(parents=True)
    wiki.write_text("accepted", encoding="utf-8")
    promoted = []
    monkeypatch.setattr(
        worker,
        "promote_candidate_document",
        lambda path, body, review, **_kwargs: promoted.append((path, body, review)) or wiki,
    )
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path)

    result = worker.review_candidate(config, {"record_id": "rec_2", "fields": fields})

    assert result["action"] == "accept"
    assert promoted[0][1] == accepted_body
    assert promoted[0][2]["lesson"] == "验收通过。"
    assert updates[-1]["运行状态"] == "已晋升"
    assert updates[-1]["Wiki状态"] == "promoted"
    assert updates[-1]["Wiki路径"] == "wiki/computing/strategies/accepted.md"
    assert updates[-1]["审核时间"] == "2026-07-22 00:20:00"


def test_needs_user_action_never_claims_raw_ready(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "needs_user_action",
            "error": {"code": "CHALLENGE_REQUIRED", "message": "captcha required"},
        },
    )
    result = worker.process_record(
        config,
        {"record_id": "rec_1", "fields": {"内容": "https://example.com", "思考": "test"}},
    )
    assert result["status"] == "failed"
    assert result["failure_disposition"] == "needs_user_auth"
    assert updates[-1]["运行状态"] == "需授权"
    assert updates[-1]["Raw Bundle"] is None
    assert all(update.get("运行状态") != "Raw就绪" for update in updates)


def test_javascript_page_waits_for_browser_snapshot(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "ok",
            "content_type": "text/html",
            "next_action": "browser_public",
            "error": {"code": "JS_RENDER_REQUIRED", "message": "render required"},
        },
    )
    monkeypatch.setattr(worker, "package_public_web", lambda *_: (_ for _ in ()).throw(AssertionError("must not package pre-render HTML")))

    result = worker.process_record(
        config,
        {"record_id": "rec_js", "fields": {"内容": "https://example.com/app", "思考": "test"}},
    )

    assert result["status"] == "failed"
    assert result["failure_disposition"] == "needs_user_action"
    assert updates[-1]["运行状态"] == "需人工"
    assert updates[-1]["采集模式"] == "公开浏览器"
    assert updates[-1]["Raw Bundle"] is None


def test_platform_route_uses_watch_and_reference_snapshot(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "ok", "content_type": "text/html", "final_url": "https://www.bilibili.com/video/BV1/",
            "next_action": "platform_extractor", "route_plan": {"platform": "bilibili", "source_type": "video"},
        },
    )
    def fake_package(_config, _source, output):
        output.mkdir(parents=True)
        (output / "metadata.json").write_text('{"processing_status":"partial"}', encoding="utf-8")
        (output / "quality-report.json").write_text('{"processing_status":"partial","frame_count":1,"transcript_segment_count":0,"ocr_block_count":2,"warnings":[]}', encoding="utf-8")
        return {"processing_status": "partial"}
    finalized = []
    monkeypatch.setattr(worker, "package_routed_source", fake_package)
    monkeypatch.setattr(worker, "finalize_raw_v2", lambda *_args: finalized.append(_args) or {"valid": True})

    result = worker.process_record(config, {"record_id": "rec_video", "fields": {"内容": "https://www.bilibili.com/video/BV1", "思考": "test"}})

    assert result["status"] == "partial"
    assert result["job"]["capability"] == "video.watch"
    assert result["modalities"]["video"]["evidence_count"] == 1
    assert result["modalities"]["ocr"]["evidence_count"] == 2
    assert updates[-1]["运行状态"] == "Raw就绪"
    assert updates[-1]["采集模式"] == "平台提取器"
    reference = finalized[0][-1]
    assert json.loads(reference.read_text(encoding="utf-8"))["original_media_retained"] is False


def test_platform_failure_is_attributed_to_video_modality(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "ok", "content_type": "text/html", "final_url": "https://www.bilibili.com/video/BV1/",
            "next_action": "platform_extractor", "route_plan": {"platform": "bilibili", "source_type": "video"},
        },
    )
    monkeypatch.setattr(worker, "package_routed_source", lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 412")))

    result = worker.process_record(config, {"record_id": "rec_video_fail", "fields": {"内容": "https://www.bilibili.com/video/BV1", "思考": "test"}})

    assert result["status"] == "failed"
    assert result["modalities"]["video"]["status"] == "failed"
    assert result["modalities"]["video"]["error_code"] == "PLATFORM_EXTRACTOR_FAILED"
    assert result["modalities"]["text"]["status"] == "skipped"
    assert result["errors"][0]["modality"] == "video"
    assert updates[-1]["运行状态"] == "可重试失败"


def test_monkeypatched_worker_update_record_is_invoked_not_subprocess(monkeypatch, tmp_path):
    """A monkeypatched worker.update_record must be invoked by process_record.

    The pipeline module uses its own module-level bindings for I/O helpers.
    Without explicit callback injection from the worker wrapper, tests that
    monkeypatch worker attributes (update_record, probe_source,
    package_routed_source, etc.) would be silently bypassed and the real
    subprocess-based implementations would execute instead.

    This is a targeted regression test: it monkeypatches the workerʼs
    update_record and then calls process_record with a public-web URL.
    The test fails the pipeline before probe_source so the update_record
    calls for the initial status write are the only ones that matter.
    """
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "needs_user_action",
            "error": {"code": "CHALLENGE_REQUIRED", "message": "captcha required"},
        },
    )
    result = worker.process_record(
        config,
        {"record_id": "rec_monkey", "fields": {"内容": "https://example.com", "思考": "regression"}},
    )
    # If the pipeline bypassed the monkeypatched update_record and called
    # its own module-level function, this would have tried to spawn a
    # subprocess (lark.exe) and either hung or raised a different error.
    assert result["status"] == "failed"
    assert len(updates) >= 2, f"Expected at least 2 update_record calls, got {len(updates)}"
    # First call: 运行状态="已领取" (initial claim state write)
    assert updates[0]["运行状态"] == "已领取"
    # Last call: 运行状态="需授权" (probe failure disposition)
    assert updates[-1]["运行状态"] == "需授权"


# ── Pipeline dedup helper contract ──────────────────────────────────


def test_dedup_helpers_invoked_by_two_branch_paths(monkeypatch, tmp_path):
    """_complete_bundle and _fail_bundle are invoked by at least two branch paths."""
    from feishu_worker import pipeline as pipeline_mod

    complete_calls = []
    fail_calls = []

    def fake_complete(**kwargs):
        complete_calls.append(kwargs)

    def fake_fail(**kwargs):
        fail_calls.append(kwargs)

    monkeypatch.setattr(pipeline_mod, "_complete_bundle", fake_complete)
    monkeypatch.setattr(pipeline_mod, "_fail_bundle", fake_fail)
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: None)

    config = worker.WorkerConfig(
        "base", "table",
        tmp_path / "lark.exe", tmp_path,
        tmp_path / "python.exe", tmp_path / "out",
    )

    # --- Branch 1: public-web success ---
    monkeypatch.setattr(worker, "probe_source", lambda *_: {
        "status": "ok", "content_type": "text/html",
    })
    monkeypatch.setattr(worker, "package_public_web", lambda _c, _u, out, _h: (
        out.mkdir(parents=True, exist_ok=True),
        (out / "metadata.json").write_text('{"processing_status":"complete"}', encoding="utf-8"),
    ) and {"processing_status": "complete"})
    monkeypatch.setattr(worker, "finalize_raw_v2", lambda *_: {"valid": True, "schema_version": "raw-multimodal/v0.2"})

    worker.process_record(config, {
        "record_id": "rec_web_ok",
        "fields": {"内容": "https://example.com/page", "思考": "test"},
    })

    assert len(complete_calls) == 1, f"Expected 1 _complete_bundle call, got {len(complete_calls)}"
    assert complete_calls[0]["modality_key"] == "text"
    assert complete_calls[0]["record_id"] == "rec_web_ok"

    # --- Branch 2: public-web failure ---
    monkeypatch.setattr(
        worker, "package_public_web",
        lambda *_: (_ for _ in ()).throw(RuntimeError("extraction failed")),
    )

    worker.process_record(config, {
        "record_id": "rec_web_fail",
        "fields": {"内容": "https://example.com/page2", "思考": "test"},
    })

    assert len(fail_calls) == 1, f"Expected 1 _fail_bundle call, got {len(fail_calls)}"
    assert fail_calls[0]["failure_code"] == "EXTRACTION_FAILED"
    assert fail_calls[0]["record_id"] == "rec_web_fail"
    assert fail_calls[0]["clear_outputs"] is False


# ── Fix 1: .oks/ gitignore regression tests ────────────────────────

def test_candidate_state_path_is_under_dot_oks():
    path = worker.candidate_state_path("rec-test-123")
    assert ".oks" in path.parts
    assert "candidates" in path.parts
    assert path.name == "rec-test-123.json"


def test_run_dir_is_under_dot_oks_runs():
    run_id = "run-20260727T120000-abc12345"
    run_dir = worker.ROOT / ".oks" / "runs" / run_id
    assert ".oks" in run_dir.parts
    assert "runs" in run_dir.parts
    assert run_dir.name == run_id


def test_lock_dir_is_under_dot_oks_locks():
    lock_dir = worker.ROOT / ".oks" / "locks"
    assert ".oks" in lock_dir.parts
    assert "locks" in lock_dir.parts


def _git_check_ignore(path: Path) -> bool:
    """Return True if *path* is ignored by git."""
    import subprocess
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=worker.ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def test_dot_oks_is_in_gitignore():
    gitignore = Path(__file__).resolve().parents[4] / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert ".oks/" in lines


def test_git_check_ignore_candidates():
    candidate_path = worker.ROOT / ".oks" / "candidates" / "rec-test-ignore.json"
    assert _git_check_ignore(candidate_path), (
        f"git check-ignore must match {candidate_path}; .gitignore rule may be stale"
    )


def test_git_check_ignore_runs():
    run_path = worker.ROOT / ".oks" / "runs" / "run-20260727T000000-ffffffff"
    assert _git_check_ignore(run_path), (
        f"git check-ignore must match {run_path}; .gitignore rule may be stale"
    )


def test_git_check_ignore_locks():
    lock_path = worker.ROOT / ".oks" / "locks" / "feishu-base-0000000000000000.lock"
    assert _git_check_ignore(lock_path), (
        f"git check-ignore must match {lock_path}; .gitignore rule may be stale"
    )


def test_candidate_path_rejects_invalid_record_id():
    try:
        worker.candidate_state_path("")
    except ValueError as error:
        assert "record_id" in str(error)
    else:
        raise AssertionError("Empty record_id must be rejected")


# ── Fix 2: Lazy Lark CLI resolver tests ─────────────────────────────

def test_shared_resolver_prefers_lark_cli_exe(monkeypatch, tmp_path):
    lark = tmp_path / "custom-lark.cmd"
    lark.write_text("")
    monkeypatch.setenv("LARK_CLI_EXE", str(lark))
    from _lark_cli import resolve_lark_cli

    assert resolve_lark_cli() == lark.resolve()


def test_shared_resolver_raises_when_cli_missing(monkeypatch):
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    monkeypatch.setattr("_lark_cli.shutil.which", lambda _name: None)
    from _lark_cli import resolve_lark_cli

    try:
        resolve_lark_cli(_platform="posix")
    except RuntimeError as error:
        assert "LARK_CLI_EXE" in str(error)
    else:
        raise AssertionError("Missing CLI must raise RuntimeError")


def test_importing_feishu_module_does_not_require_cli_installation(monkeypatch):
    """Importing feishu_setup or feishu_base_worker must not resolve the CLI."""
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    import importlib
    import feishu_setup

    assert feishu_setup._LARK_CLI is None
    importlib.reload(feishu_setup)
    assert feishu_setup._LARK_CLI is None


def test_shared_resolver_supports_windows_cmd_and_exe(monkeypatch, tmp_path):
    """Simulate Windows nt: lark-cli.cmd is found before lark-cli.exe."""
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    lark_cmd = tmp_path / "lark-cli.cmd"
    lark_cmd.write_text("")
    monkeypatch.setattr("_lark_cli.shutil.which", lambda name: str(lark_cmd) if name == "lark-cli.cmd" else None)
    from _lark_cli import resolve_lark_cli

    assert resolve_lark_cli(_platform="nt").name == "lark-cli.cmd"


def test_resolver_windows_falls_back_to_exe(monkeypatch, tmp_path):
    """Simulate Windows nt: lark-cli.exe resolves when .cmd is absent."""
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    exe = tmp_path / "lark-cli.exe"
    exe.write_text("")

    def _which(name):
        return str(exe) if name == "lark-cli.exe" else None

    monkeypatch.setattr("_lark_cli.shutil.which", _which)
    from _lark_cli import resolve_lark_cli as win_resolve

    resolved = win_resolve(_platform="nt")
    assert resolved.name == "lark-cli.exe"


def test_resolver_posix_uses_plain_lark_cli(monkeypatch, tmp_path):
    """Simulate POSIX (Linux/macOS): searches for lark-cli without extension.

    Verifies the resolution branch, not the full Path.resolve() call, so the
    test runs deterministically on any host OS.
    """
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    calls = []

    def _capture_which(name):
        calls.append(name)
        return None

    monkeypatch.setattr("_lark_cli.shutil.which", _capture_which)
    try:
        from _lark_cli import resolve_lark_cli as posix_resolve
        posix_resolve(_platform="posix")
    except RuntimeError:
        pass  # expected — CLI not found on this machine
    assert "lark-cli" in calls, (
        f"POSIX resolver must search for lark-cli, got calls: {calls}"
    )
    assert "lark-cli.cmd" not in calls
    assert "lark-cli.exe" not in calls


def test_shared_resolver_uses_path_lookup_when_no_env_var(monkeypatch, tmp_path):
    monkeypatch.delenv("LARK_CLI_EXE", raising=False)
    lark = tmp_path / "lark-cli"
    lark.write_text("")
    # On actual Windows, the resolver checks .cmd/.exe; on POSIX, "lark-cli".
    # Test the actual OS path without patching os.name.
    from _lark_cli import resolve_lark_cli
    try:
        resolved = resolve_lark_cli()
    except RuntimeError:
        # CLI not installed — skip assertion, path lookup was attempted
        return
    assert resolved.name.startswith("lark-cli")


# ── Fix 3: Token redaction in Feishu setup ──────────────────────────

def test_redact_token_shows_partial_token():
    from feishu_setup import _redact_token

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    redacted = _redact_token(token)
    assert "***" in redacted
    assert token not in redacted
    assert redacted.startswith(token[:6])
    assert redacted.endswith(token[-4:])


def test_redact_token_handles_short_token():
    from feishu_setup import _redact_token

    token = "abc123def456"
    redacted = _redact_token(token)
    assert "***" in redacted
    assert token not in redacted


def test_lark_redacts_token_in_error_output(monkeypatch):
    """_lark() must redact base_token from subprocess stderr before raising."""
    import feishu_setup
    from feishu_setup import _lark, _redact_token
    import subprocess as sp

    # Hermetic: never resolve the real lark-cli, and leave the module-level
    # cache untouched for other tests.
    monkeypatch.setattr(feishu_setup, "_LARK_CLI", None)
    monkeypatch.setattr(feishu_setup, "_get_lark_cli", lambda: "/fake/lark-cli")

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    monkeypatch.setattr(
        sp,
        "run",
        lambda *_args, **_kwargs: sp.CompletedProcess(
            ["lark-cli"], returncode=1, stdout="", stderr=f"error: {token} not found"
        ),
    )
    try:
        _lark(["base", "+base-get"], redact_token=token)
    except RuntimeError as error:
        assert token not in str(error)
        assert _redact_token(token) in str(error)
    else:
        raise AssertionError("_lark must raise on non-zero returncode")


def test_setup_select_options_cover_every_worker_written_value():
    """A Base created by setup must accept every status the worker writes.

    Bitable rejects unknown select options with INVALID_ARGUMENT, which this
    pipeline treats as fatal (no retry) — so a mismatch bricks the first upsert.
    """
    import re

    from feishu_setup import WORKER_FIELDS
    from feishu_worker.states import (
        CAPTURE_MODE_OPTIONS,
        QUALITY_STATUS_OPTIONS,
        RUN_STATUS_OPTIONS,
        WIKI_STATUS_OPTIONS,
    )

    declared = {
        field["name"]: {option["name"] for option in field["options"]}
        for field in WORKER_FIELDS
        if field["type"] == "select"
    }
    assert declared["运行状态"] == set(RUN_STATUS_OPTIONS)
    assert declared["采集模式"] == set(CAPTURE_MODE_OPTIONS)
    assert declared["质量状态"] == set(QUALITY_STATUS_OPTIONS)
    assert declared["Wiki状态"] == set(WIKI_STATUS_OPTIONS)

    # Scan the pipeline sources for literal writes and prove they are declared.
    root = Path(__file__).resolve().parent.parent
    sources = [root / "feishu_base_worker.py", *sorted((root / "feishu_worker").glob("*.py"))]
    for field_name, allowed in (
        ("运行状态", declared["运行状态"]),
        ("采集模式", declared["采集模式"]),
        ("质量状态", declared["质量状态"]),
        ("Wiki状态", declared["Wiki状态"]),
    ):
        pattern = re.compile(rf'"{field_name}":\s*"([^"]+)"')
        for source in sources:
            if source.name.startswith("test_"):
                continue
            for written in pattern.findall(source.read_text(encoding="utf-8")):
                assert written in allowed, (
                    f"{source.name} writes {field_name}={written!r} but setup does not declare it"
                )


def test_claim_filter_covers_retry_and_lease_recovery():
    """list_records must fetch every status is_candidate() can accept."""
    from feishu_worker.states import (
        CLAIMABLE_STATUSES,
        RUN_STATUS_CLAIMED,
        RUN_STATUS_PENDING,
        RUN_STATUS_RETRYABLE,
    )

    # Retry-flagged and expired-lease records are not 待处理; filtering to
    # 待处理 alone made both paths unreachable in run-once.
    assert RUN_STATUS_PENDING in CLAIMABLE_STATUSES
    assert RUN_STATUS_RETRYABLE in CLAIMABLE_STATUSES
    assert RUN_STATUS_CLAIMED in CLAIMABLE_STATUSES

    for source in (
        Path(__file__).resolve().parent.parent / "feishu_base_worker.py",
        Path(__file__).resolve().parent.parent / "feishu_worker" / "base_client.py",
    ):
        text = source.read_text(encoding="utf-8")
        assert 'intersects",["待处理"]' not in text, f"{source.name} still hardcodes 待处理-only filter"
        assert "CLAIMABLE_STATUSES" in text


def test_redact_error_message_replaces_token():
    from feishu_setup import _redact_text, _redact_token

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    message = f"Error querying Base {token}: permission denied"
    redacted = _redact_text(message, token)
    assert token not in redacted
    assert _redact_token(token) in redacted


def test_setup_accepts_show_credentials_flag():
    from feishu_setup import build_parser

    parser = build_parser()
    args = parser.parse_args(["--show-credentials"])
    assert args.show_credentials is True


def test_setup_default_hides_credentials():
    from feishu_setup import build_parser

    parser = build_parser()
    args = parser.parse_args([])
    assert args.show_credentials is False


def test_worker_notification_wrapper_forwards_candidate_adapter_kwargs(monkeypatch, tmp_path):
    captured = {}
    config = worker.WorkerConfig("base", "table", tmp_path / "lark", tmp_path)

    def fake_send(*args, **kwargs):
        captured.update(kwargs)
        return {"status": "skipped"}

    monkeypatch.setattr(worker, "_candidate_send_candidate_review_notification", fake_send)

    result = worker.send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={"candidate_id": "candidate", "revision": 1, "candidate_sha256": "hash"},
        metadata={"title": "Candidate"},
        body="Candidate body",
        fields={},
        root=tmp_path,
        _lark_fn=lambda *_args, **_kwargs: {},
    )

    assert result == {"status": "skipped"}
    assert captured["root"] == tmp_path
    assert callable(captured["_lark_fn"])


def test_setup_accepts_current_base_create_response_envelope(monkeypatch):
    """Current lark-cli nests the created Base under data.base."""
    import io

    from feishu_setup import USER_FIELDS, build_parser, setup

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    table_id = "tblABC123"

    monkeypatch.setattr("feishu_setup._get_lark_cli", lambda: "/fake/lark-cli")

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        sub = args[1] if len(args) > 1 else ""
        if sub == "+base-create":
            return {"ok": True, "data": {"base": {"base_token": token}}}
        if sub == "+table-list":
            return [{"name": "每日知识采集", "id": table_id}]
        if sub == "+field-list":
            return [{"name": field["name"]} for field in USER_FIELDS]
        if sub == "+form-list":
            return {"data": {"forms": [{"id": "frmXYZ", "name": "OKS Daily Knowledge Intake"}]}}
        if sub == "+form-create":
            return {"data": {"form_id": "frmXYZ"}}
        if sub == "+form-questions-list":
            return {"data": {"items": [
                {"id": f"q_{index}", "title": title, "required": index == 0}
                for index, title in enumerate((
                    "内容", "附件", "思考", "重点问题（可选）", "评级", "知识域",
                ))
            ]}}
        return {}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    assert setup(build_parser().parse_args([])) == 0
    assert token not in stdout.getvalue()


def test_setup_redacts_fixture_base_token_by_default(monkeypatch):
    """End-to-end: setup() with --base-token must redact the token in stdout by default."""
    import io

    from feishu_setup import _redact_token, build_parser, setup

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    table_id = "tblABC123"

    monkeypatch.setattr("feishu_setup._get_lark_cli", lambda: "/fake/lark-cli")

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        sub = args[1] if len(args) > 1 else ""
        if sub == "+base-get":
            return {"name": "OKS Base"}
        if sub == "+table-list":
            return [{"name": "每日知识采集", "id": table_id}]
        if sub == "+field-list":
            return [
                {"name": "内容", "type": "text"},
                {"name": "附件", "type": "attachment"},
                {"name": "思考", "type": "text"},
                {"name": "希望解决的问题", "type": "text"},
                {"name": "评级", "type": "select"},
                {"name": "知识域", "type": "select", "multiple": True},
            ]
        if sub == "+form-list":
            return {"data": {"forms": [{"id": "frmXYZ", "name": "OKS Daily Knowledge Intake"}]}}
        if sub == "+form-create":
            return {"data": {"form_id": "frmXYZ"}, "form_id": "frmXYZ"}
        if sub == "+form-questions-list":
            return {"data": {"items": [
                {"id": f"q_{index}", "title": title, "required": index == 0}
                for index, title in enumerate((
                    "内容", "附件", "思考", "重点问题（可选）", "评级", "知识域",
                ))
            ]}}
        if sub == "+field-create":
            return {"field_id": "fld_new"}
        return {}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)

    parser = build_parser()
    args = parser.parse_args(["--base-token", token])

    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    exit_code = setup(args)

    output = stdout.getvalue()
    assert exit_code == 0
    assert token not in output, (
        f"Full Base token must not appear in default setup output:\n{output}"
    )
    assert _redact_token(token) in output, (
        f"Redacted token {_redact_token(token)!r} must appear in setup output:\n{output}"
    )
    assert "--show-credentials" in output, (
        "Default output must hint about --show-credentials"
    )


def test_setup_shows_fixture_token_only_with_show_credentials(monkeypatch):
    """End-to-end: --show-credentials must display the full Base token in the final block."""
    import io

    from feishu_setup import build_parser, setup

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"
    table_id = "tblABC123"

    monkeypatch.setattr("feishu_setup._get_lark_cli", lambda: "/fake/lark-cli")

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        sub = args[1] if len(args) > 1 else ""
        if sub == "+base-get":
            return {"name": "OKS Base"}
        if sub == "+table-list":
            return [{"name": "每日知识采集", "id": table_id}]
        if sub == "+field-list":
            return [
                {"name": "内容", "type": "text"},
                {"name": "附件", "type": "attachment"},
                {"name": "思考", "type": "text"},
                {"name": "希望解决的问题", "type": "text"},
                {"name": "评级", "type": "select"},
                {"name": "知识域", "type": "select", "multiple": True},
            ]
        if sub == "+form-list":
            return {"data": {"forms": [{"id": "frmXYZ", "name": "OKS Daily Knowledge Intake"}]}}
        if sub == "+form-create":
            return {"data": {"form_id": "frmXYZ"}, "form_id": "frmXYZ"}
        if sub == "+form-questions-list":
            return {"data": {"items": [
                {"id": f"q_{index}", "title": title, "required": index == 0}
                for index, title in enumerate((
                    "内容", "附件", "思考", "重点问题（可选）", "评级", "知识域",
                ))
            ]}}
        if sub == "+field-create":
            return {"field_id": "fld_new"}
        return {}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)

    parser = build_parser()
    args = parser.parse_args(["--base-token", token, "--show-credentials"])

    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    exit_code = setup(args)

    output = stdout.getvalue()
    assert exit_code == 0
    assert token in output, (
        f"Full Base token must appear with --show-credentials:\n{output}"
    )
    assert "--show-credentials" not in output, (
        "Output must not hint about --show-credentials when already shown"
    )


def test_reference_form_schema_is_exactly_six_user_questions():
    from feishu_setup import FORM_QUESTIONS, USER_FIELDS, WORKER_FIELDS
    from feishu_worker.states import KNOWLEDGE_DOMAIN_OPTIONS, RATING_OPTIONS

    assert [question["title"] for question in FORM_QUESTIONS] == [
        "内容", "附件", "思考", "重点问题（可选）", "评级", "知识域",
    ]
    assert [field["name"] for field in USER_FIELDS] == [
        "内容", "附件", "思考", "重点问题（可选）", "评级", "知识域",
    ]
    assert FORM_QUESTIONS[0]["required"] is True
    assert all(not question["required"] for question in FORM_QUESTIONS[1:])
    assert [option["name"] for option in USER_FIELDS[4]["options"]] == list(RATING_OPTIONS)
    assert USER_FIELDS[5]["multiple"] is True
    assert [option["name"] for option in USER_FIELDS[5]["options"]] == list(KNOWLEDGE_DOMAIN_OPTIONS)
    assert not ({field["name"] for field in USER_FIELDS} & {field["name"] for field in WORKER_FIELDS})


def test_setup_creates_form_before_worker_fields(monkeypatch):
    from feishu_setup import FORM_QUESTIONS, USER_FIELDS, WORKER_FIELDS, build_parser, setup

    calls = []
    questions = [{"id": "q_0", "title": "内容"}]

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        sub = args[1]
        calls.append(sub)
        if sub == "+base-get":
            return {"name": "OKS Base"}
        if sub == "+table-list":
            return []
        if sub == "+table-create":
            return {"data": {"table": {"id": "tblNew"}}}
        if sub == "+form-list":
            return {"data": {"forms": []}}
        if sub == "+form-create":
            return {"data": {"form_id": "frmNew"}}
        if sub == "+form-questions-create":
            questions[:] = [
                {"id": f"q_{index}", "title": item["title"], "required": item["required"]}
                for index, item in enumerate(FORM_QUESTIONS)
            ]
            return {"ok": True}
        if sub == "+form-questions-list":
            return {"data": {"items": list(questions)}}
        return {"ok": True}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    assert setup(build_parser().parse_args(["--base-token", "base-token"])) == 0
    assert calls.index("+form-create") < calls.index("+field-create")
    assert calls.count("+field-create") == len(WORKER_FIELDS)
    assert "+form-questions-delete" not in calls


def test_legacy_question_title_is_accepted_and_renamed(monkeypatch):
    from feishu_setup import FORM_QUESTIONS, _complete_user_form, _verify_user_form

    questions = [
        {"id": f"q_{index}", "title": item["title"], "required": item["required"]}
        for index, item in enumerate(FORM_QUESTIONS)
    ]
    questions[3]["title"] = "希望解决的问题"

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        if args[1] == "+form-questions-list":
            return {"data": {"items": list(questions)}}
        if args[1] == "+form-questions-update":
            updates = json.loads(args[args.index("--questions") + 1])
            for question, update in zip(questions, updates):
                question.update(update)
        return {"ok": True}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    _complete_user_form("base", "table", "form")
    _verify_user_form("base", "table", "form")
    assert questions[3]["title"] == "重点问题（可选）"


def test_empty_new_form_fails_before_creating_questions(monkeypatch):
    from feishu_setup import _complete_user_form

    calls = []

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        calls.append(args[1])
        return {"data": {"items": []}}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    monkeypatch.setattr("feishu_setup.time.sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="未返回引导问题"):
        _complete_user_form("base", "table", "form")
    assert "+form-questions-create" not in calls


def test_question_creation_waits_for_feishu_read_propagation(monkeypatch):
    from feishu_setup import FORM_QUESTIONS, _complete_user_form

    complete = [
        {"id": f"q_{index}", "title": item["title"], "required": item["required"]}
        for index, item in enumerate(FORM_QUESTIONS)
    ]
    reads = iter([
        [{"id": "q_0", "title": "内容"}],
        [{"id": "q_0", "title": "内容"}],
        complete,
    ])

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        if args[1] == "+form-questions-list":
            return {"data": {"items": next(reads)}}
        return {"ok": True}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    monkeypatch.setattr("feishu_setup.time.sleep", lambda _seconds: None)
    _complete_user_form("base", "table", "form")


def test_worker_fields_are_followed_by_a_second_form_verification(monkeypatch):
    from feishu_setup import FORM_QUESTIONS, USER_FIELDS, build_parser, setup

    question_reads = 0
    worker_created = False

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        nonlocal question_reads, worker_created
        sub = args[1]
        if sub == "+base-get":
            return {"name": "OKS Base"}
        if sub == "+table-list":
            return [{"name": "每日知识采集", "id": "table"}]
        if sub == "+field-list":
            return [{"name": field["name"]} for field in USER_FIELDS]
        if sub == "+form-list":
            return {"data": {"forms": [{"id": "form", "name": "OKS Daily Knowledge Intake"}]}}
        if sub == "+form-questions-list":
            question_reads += 1
            return {"data": {"items": [
                {"id": f"q_{index}", "title": item["title"], "required": item["required"]}
                for index, item in enumerate(FORM_QUESTIONS)
            ]}}
        if sub == "+field-create":
            worker_created = True
        return {"ok": True}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    assert setup(build_parser().parse_args(["--base-token", "base"])) == 0
    assert worker_created
    assert question_reads >= 5


def test_setup_fails_closed_on_polluted_form(monkeypatch):
    from feishu_setup import FORM_QUESTIONS, USER_FIELDS, WORKER_FIELDS, build_parser, setup

    calls = []

    def _mock_lark(args, *, timeout=60.0, redact_token=None):
        sub = args[1]
        calls.append(sub)
        if sub == "+base-get":
            return {"name": "OKS Base"}
        if sub == "+table-list":
            return [{"name": "每日知识采集", "id": "tblExisting"}]
        if sub == "+field-list":
            return [{"name": field["name"]} for field in USER_FIELDS + WORKER_FIELDS]
        if sub == "+form-list":
            return {"data": {"forms": [{"id": "frmExisting", "name": "OKS Daily Knowledge Intake"}]}}
        if sub == "+form-questions-list":
            return {"data": {"items": [
                *[
                    {"id": f"q_{index}", "title": item["title"], "required": item["required"]}
                    for index, item in enumerate(FORM_QUESTIONS)
                ],
                {"id": "q_worker", "title": "运行状态"},
            ]}}
        return {"ok": True}

    monkeypatch.setattr("feishu_setup._lark", _mock_lark)
    with pytest.raises(RuntimeError, match="额外字段|字段校验失败"):
        setup(build_parser().parse_args(["--base-token", "base-token"]))
    assert "+form-questions-delete" not in calls
    assert "+field-delete" not in calls


def test_verify_form_rejects_missing_readback(monkeypatch):
    from feishu_setup import _verify_user_form

    monkeypatch.setattr("feishu_setup._lark", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("feishu_setup.time.sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="无法读取表单问题列表"):
        _verify_user_form("base", "table", "form")


def test_legacy_rating_aliases_are_normalized():
    from feishu_worker.states import normalize_rating

    assert normalize_rating("紧急核心") == "A"
    assert normalize_rating("重要") == "B"
    assert normalize_rating("普通参考") == "C"
    assert normalize_rating("暂不处理") == "C"
    assert normalize_rating("A") == "A"


def test_existing_incompatible_user_field_fails_closed():
    from feishu_setup import _validate_existing_user_fields

    with pytest.raises(RuntimeError, match="知识域 类型应为 select"):
        _validate_existing_user_fields([
            {"name": "知识域", "type": "text"},
        ])


def test_setup_redacts_token_in_mocked_lark_failure(monkeypatch):
    """A lark-cli failure during setup() must not expose the Base token."""
    import io
    import subprocess as sp

    from feishu_setup import _redact_token, build_parser, setup

    token = "B4s3T0k3nV4lu3Fr0mF3ishu"

    monkeypatch.setattr("feishu_setup._get_lark_cli", lambda: "/fake/lark-cli")

    monkeypatch.setattr(
        sp, "run",
        lambda *_args, **_kwargs: sp.CompletedProcess(
            ["lark-cli"], returncode=1, stdout="",
            stderr=f"error: Base {token} not found, permission denied for {token}",
        ),
    )

    parser = build_parser()
    args = parser.parse_args(["--base-token", token])

    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    try:
        setup(args)
    except RuntimeError as error:
        assert token not in str(error), (
            f"Error message must not expose full token: {error}"
        )
        assert _redact_token(token) in str(error), (
            f"Error message must contain redacted token: {error}"
        )
    else:
        raise AssertionError("setup() must raise RuntimeError when lark-cli fails")


# ── Fix 4: Error text redaction in worker ───────────────────────────

def test_redact_error_text_strips_bearer_tokens():
    message = "failed: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNq1PStH5hHOqg0"
    redacted = worker._redact_error_text(message)
    assert "Bearer eyJ" not in redacted
    assert "Bearer ***" in redacted


def test_redact_error_text_replaces_home_directory():
    home = str(worker.HOME)
    if len(home) > 4:
        message = f"config file not found: {home}/.oks/config.json"
        redacted = worker._redact_error_text(message)
        assert home not in redacted
        assert "~" in redacted


def test_redact_error_text_handles_empty_and_none():
    assert worker._redact_error_text("") == ""
    assert worker._redact_error_text("plain error") == "plain error"


def test_redact_error_text_strips_access_token_assignments():
    message = "error: access_token=abc123def456ghi789jkl at https://api.example.com"
    redacted = worker._redact_error_text(message)
    assert "abc123def456ghi789jkl" not in redacted
    assert "=***" in redacted


def test_redact_error_text_strips_token_and_key_assignments():
    message = "failed: token=supersecret123 token:moreSecret456 key=base64stuff"
    redacted = worker._redact_error_text(message)
    assert "supersecret123" not in redacted
    assert "moreSecret456" not in redacted
    assert "base64stuff" not in redacted
    assert redacted.count("=***") >= 3


def test_redact_error_text_strips_api_key_and_secret_assignments():
    message = "api_key=sk-proj-1234567890abcdef app_secret=mysecretvalue123 secret_key=dontleak"
    redacted = worker._redact_error_text(message)
    for secret in ("sk-proj-1234567890abcdef", "mysecretvalue123", "dontleak"):
        assert secret not in redacted
    assert redacted.count("=***") >= 3


def test_redact_error_text_preserves_short_values():
    message = "key=abc value=12 status=ok"
    redacted = worker._redact_error_text(message)
    # Short values (< 8 chars) are not redacted; they're not credential-like
    assert "key=abc" in redacted
    assert "value=12" in redacted


def test_failed_record_error_text_is_redacted_before_truncation(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path, tmp_path / "python.exe", tmp_path / "out")
    updates = []
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {})
    monkeypatch.setattr(
        worker,
        "probe_source",
        lambda *_: {
            "status": "needs_user_action",
            "error": {"code": "AUTH_REQUIRED", "message": f"auth failed with Bearer secret123abc and path {worker.HOME}/token"},
        },
    )
    result = worker.process_record(
        config,
        {"record_id": "rec_1", "fields": {"内容": "https://example.com", "思考": "test"}},
    )
    assert result["status"] == "failed"
    error_text = updates[-1]["错误说明"]
    assert "Bearer secret123abc" not in error_text
    assert "Bearer ***" in error_text
    home_str = str(worker.HOME)
    if len(home_str) > 4:
        assert home_str not in error_text


# ── Round 2 / Part A: lark_json bounded exponential retry ─────────────


def _fake_completed_process(stdout="", stderr="", returncode=0):
    return worker.subprocess.CompletedProcess(
        ["lark-cli"], returncode, stdout, stderr,
    )


def _make_lark_error_response(code, message="error"):
    return json.dumps({"ok": False, "error": {"code": code, "message": message}})


def test_lark_json_retries_on_rate_limited(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            return _fake_completed_process(
                stdout=_make_lark_error_response("RATE_LIMITED"),
                returncode=1,
            )
        return _fake_completed_process(stdout='{"ok": true}')

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    result = worker.lark_json(
        worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
        "base", "+record-list",
    )

    assert result == {"ok": True}
    assert len(calls) == 3
    assert len(sleeps) == 2
    # Exponential: 1.0, 2.0
    assert sleeps[0] == pytest.approx(1.0)
    assert sleeps[1] == pytest.approx(2.0)


def test_lark_json_retries_on_subprocess_timeout(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise worker.subprocess.TimeoutExpired(["lark-cli"], 30)
        return _fake_completed_process(stdout='{"ok": true}')

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    result = worker.lark_json(
        worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
        "base", "+record-list",
    )

    assert result == {"ok": True}
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_lark_json_retries_on_oserror(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionRefusedError("Connection refused")
        return _fake_completed_process(stdout='{"ok": true}')

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    result = worker.lark_json(
        worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
        "base", "+record-list",
    )

    assert result == {"ok": True}
    assert len(calls) == 3


def test_lark_json_never_retries_auth_failed(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return _fake_completed_process(
            stdout=_make_lark_error_response("AUTH_FAILED"),
            returncode=1,
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-list",
        )
    except RuntimeError as exc:
        assert "AUTH_FAILED" in str(exc)
    else:
        raise AssertionError("auth failures must not be retried")

    assert len(calls) == 1
    assert len(sleeps) == 0


def test_lark_json_reports_redacted_stderr_for_empty_failed_output(monkeypatch):
    token = "base_token_secret_123456"

    def fake_run(*args, **kwargs):
        return _fake_completed_process(
            stdout="",
            stderr=f"validation failed: token={token}",
            returncode=1,
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as error:
        worker.lark_json(
            worker.WorkerConfig(token, "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-upsert",
        )

    assert "lark-cli exited 1" in str(error.value)
    assert token not in str(error.value)
    assert "token=***" in str(error.value)


def test_lark_json_never_retries_permission_denied(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return _fake_completed_process(
            stdout=_make_lark_error_response("PERMISSION_DENIED"),
            returncode=1,
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-list",
        )
    except RuntimeError as exc:
        assert "PERMISSION_DENIED" in str(exc)
    else:
        raise AssertionError("permission failures must not be retried")

    assert len(calls) == 1
    assert len(sleeps) == 0


def test_lark_json_exhausts_retries_with_command_context(monkeypatch):
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return _fake_completed_process(
            stdout=_make_lark_error_response("UPSTREAM_UNAVAILABLE"),
            returncode=1,
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-upsert", "--record-id", "rec_1",
        )
    except RuntimeError as exc:
        error_text = str(exc)
        assert "4 attempts" in error_text or str(1 + worker._LARK_MAX_RETRIES) in error_text
        assert "base" in error_text
    else:
        raise AssertionError("exhausted retries must raise RuntimeError")

    assert len(calls) == 1 + worker._LARK_MAX_RETRIES
    assert len(sleeps) == worker._LARK_MAX_RETRIES


def test_extract_lark_error_code_from_error_dict():
    assert worker._extract_lark_error_code({"error": {"code": "RATE_LIMITED"}}) == "RATE_LIMITED"
    assert worker._extract_lark_error_code({"code": "TIMEOUT"}) == "TIMEOUT"
    assert worker._extract_lark_error_code({"ok": False}) == ""


def test_is_retryable_lark_error_detects_transient_codes():
    assert worker._is_retryable_lark_error({"error": {"code": "RATE_LIMITED"}})
    assert worker._is_retryable_lark_error({"error": {"code": "UPSTREAM_UNAVAILABLE"}})
    assert worker._is_retryable_lark_error({"error": {"code": "NETWORK_ERROR"}})
    assert worker._is_retryable_lark_error({"error": {"code": "TIMEOUT"}})
    assert not worker._is_retryable_lark_error({"error": {"code": "AUTH_FAILED"}})
    assert not worker._is_retryable_lark_error({})


def test_is_fatal_lark_error_blocks_retry():
    assert worker._is_fatal_lark_error({"error": {"code": "AUTH_FAILED"}})
    assert worker._is_fatal_lark_error({"error": {"code": "PERMISSION_DENIED"}})
    assert worker._is_fatal_lark_error({"error": {"code": "ACCESS_DENIED"}})
    assert worker._is_fatal_lark_error({"error": {"code": "VALIDATION_ERROR"}})
    assert not worker._is_fatal_lark_error({"error": {"code": "RATE_LIMITED"}})
    assert not worker._is_fatal_lark_error({})


# ── Round 2 / Part B: aware-UTC lease / run-id time paths ────────────


def test_parse_base_datetime_offset_timestamp():
    result = worker.parse_base_datetime("2026-07-27 12:00:00+00:00")
    assert result is not None
    assert result.tzinfo is not None
    assert result == worker.datetime(2026, 7, 27, 12, 0, 0, tzinfo=worker.timezone.utc)


def test_parse_base_datetime_iso_format_with_z():
    result = worker.parse_base_datetime("2026-07-27T12:00:00Z")
    assert result is not None
    assert result.tzinfo is not None
    assert result == worker.datetime(2026, 7, 27, 12, 0, 0, tzinfo=worker.timezone.utc)


def test_parse_base_datetime_rejects_naive_by_default():
    result = worker.parse_base_datetime("2026-07-27 12:00:00")
    assert result is None


def test_parse_base_datetime_migrates_naive_with_assume_utc():
    result = worker.parse_base_datetime(
        "2026-07-27 12:00:00", naive_migration="assume_utc"
    )
    assert result is not None
    assert result.tzinfo is not None
    assert result == worker.datetime(2026, 7, 27, 12, 0, 0, tzinfo=worker.timezone.utc)


def test_parse_base_datetime_offset_with_non_utc():
    result = worker.parse_base_datetime("2026-07-27 20:00:00+08:00")
    assert result is not None
    assert result.tzinfo is not None
    assert result == worker.datetime(2026, 7, 27, 12, 0, 0, tzinfo=worker.timezone.utc)


def test_parse_base_datetime_returns_none_for_empty():
    assert worker.parse_base_datetime(None) is None
    assert worker.parse_base_datetime("") is None
    assert worker.parse_base_datetime("   ") is None


def test_lease_format_roundtrips_through_parse():
    import uuid as _uuid
    now = worker.datetime.now(worker.timezone.utc)
    expires = now + worker.timedelta(seconds=3600)
    formatted = expires.strftime("%Y-%m-%d %H:%M:%S+00:00")
    parsed = worker.parse_base_datetime(formatted)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert abs((parsed - expires).total_seconds()) < 1.0


def test_claim_record_writes_aware_utc_lease(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, lease_seconds=60
    )
    updates = []
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {"record_id": "rec_utc", "fields": {"运行状态": "待处理", "重试": False}},
    )
    monkeypatch.setattr(
        worker,
        "update_record",
        lambda _c, _r, patch: updates.append((_r, patch)) or {},
    )
    monkeypatch.setattr(worker, "local_claim_lock", lambda _config: worker.contextmanager(lambda: (yield))())

    claimed = worker.claim_record(config, "rec_utc")

    assert claimed is not None
    lease_str = updates[0][1]["租约到期"]
    assert "+00:00" in lease_str
    parsed = worker.parse_base_datetime(lease_str)
    assert parsed is not None
    assert parsed.tzinfo is not None
    # Lease must be in the future
    assert parsed > worker.datetime.now(worker.timezone.utc)


def test_claim_record_run_id_contains_utc_timestamp(monkeypatch, tmp_path):
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, lease_seconds=60,
    )
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {"record_id": "rec_runid", "fields": {"运行状态": "待处理", "重试": False}},
    )
    monkeypatch.setattr(worker, "update_record", lambda _c, _r, _p: {})
    monkeypatch.setattr(worker, "local_claim_lock", lambda _config: worker.contextmanager(lambda: (yield))())

    claimed = worker.claim_record(config, "rec_runid")

    assert claimed is not None
    run_id = claimed[1]
    assert run_id.startswith("run-")
    # Run ID timestamp segment: run-YYYYMMDDTHHMMSS-xxxxxxxx
    ts_part = run_id[4:19]
    assert len(ts_part) == 15
    assert ts_part[8] == "T"


# -- Round 3 Phase 3A: DST / offset lease tests --


def test_lease_dst_spring_forward_is_still_utc_aware(monkeypatch, tmp_path):
    """A lease written near a DST spring-forward MUST be aware UTC and must
    not jump by an hour when the local wall clock changes."""
    config = worker.WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, lease_seconds=60,
    )
    monkeypatch.setattr(
        worker,
        "get_record",
        lambda *_: {"record_id": "rec_dst", "fields": {"运行状态": "待处理", "重试": False}},
    )
    updates: list = []
    monkeypatch.setattr(
        worker, "update_record", lambda _c, _r, patch: updates.append(patch) or {}
    )
    monkeypatch.setattr(
        worker, "local_claim_lock",
        lambda _config: worker.contextmanager(lambda: (yield))(),
    )

    claimed = worker.claim_record(config, "rec_dst")
    assert claimed is not None

    lease_str = updates[0]["租约到期"]
    # Must carry an explicit offset
    assert "+00:00" in lease_str or lease_str.endswith("Z") or "-" in lease_str.split(" ")[-1], (
        f"Lease must be offset-aware, got: {lease_str!r}"
    )
    parsed = worker.parse_base_datetime(lease_str)
    assert parsed is not None
    assert parsed.tzinfo is not None
    # The parsed UTC datetime must be close to now (within lease_seconds)
    now_utc = worker.datetime.now(worker.timezone.utc)
    assert abs((parsed - now_utc).total_seconds()) < 120, (
        f"Lease expiry {parsed} too far from now {now_utc}"
    )


def test_lease_positive_utc_offset_converts_to_utc():
    """A lease written with an explicit +08:00 offset must be parseable and
    convert to the equivalent UTC instant."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    # +08:00 → should become 04:00 UTC
    result = claim_parse("2026-08-15 12:00:00+08:00")
    assert result is not None
    assert result.tzinfo is not None
    expected = worker.datetime(2026, 8, 15, 4, 0, 0, tzinfo=worker.timezone.utc)
    assert result == expected, f"Expected {expected}, got {result}"


def test_lease_negative_utc_offset_converts_to_utc():
    """A lease written with an explicit -05:00 offset must be parseable and
    convert to the equivalent UTC instant."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    # -05:00 → should become 17:00 UTC
    result = claim_parse("2026-08-15 12:00:00-05:00")
    assert result is not None
    assert result.tzinfo is not None
    expected = worker.datetime(2026, 8, 15, 17, 0, 0, tzinfo=worker.timezone.utc)
    assert result == expected, f"Expected {expected}, got {result}"


def test_lease_with_z_suffix_is_utc():
    """Lease with Z suffix is parsed as UTC."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    result = claim_parse("2026-12-25T00:00:00Z")
    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset() == worker.timedelta(0)


def test_lease_offset_with_colon_format():
    """Lease with +05:30 offset (colon format) converts correctly."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    result = claim_parse("2026-08-15 12:00:00+05:30")
    assert result is not None
    assert result.tzinfo is not None
    expected = worker.datetime(2026, 8, 15, 6, 30, 0, tzinfo=worker.timezone.utc)
    assert result == expected, f"Expected {expected}, got {result}"


def test_lease_naive_still_rejected_by_default():
    """Naive lease strings are still rejected (return None) by default."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    assert claim_parse("2026-08-15 12:00:00") is None
    assert claim_parse("2026-08-15T12:00:00") is None


def test_lease_naive_accepted_with_migration_flag():
    """Naive lease strings are accepted when naive_migration='assume_utc'."""
    from feishu_worker.claim import parse_base_datetime as claim_parse

    result = claim_parse("2026-08-15 12:00:00", naive_migration="assume_utc")
    assert result is not None
    assert result.tzinfo is not None
    assert result == worker.datetime(2026, 8, 15, 12, 0, 0, tzinfo=worker.timezone.utc)


def test_lease_roundtrip_through_strftime_and_parse():
    """Lease written by claim_record roundtrips through strftime/parse correctly."""
    now = worker.datetime(2026, 7, 27, 14, 30, 45, tzinfo=worker.timezone.utc)
    formatted = now.strftime("%Y-%m-%d %H:%M:%S+00:00")
    parsed = worker.parse_base_datetime(formatted)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed == now


def test_candidate_rejects_future_lease():
    """A record whose lease is in the future is NOT a candidate for reclaim."""
    now = worker.datetime(2026, 7, 28, 12, 0, 0, tzinfo=worker.timezone.utc)
    future_lease = {
        "fields": {
            "运行状态": "已领取",
            "重试": False,
            "租约到期": "2026-07-28 12:00:01",
        }
    }
    assert not worker.is_candidate(future_lease, now=now)


def test_candidate_accepts_past_lease():
    """A record whose lease has expired IS a candidate for reclaim."""
    now = worker.datetime(2026, 7, 28, 12, 0, 0, tzinfo=worker.timezone.utc)
    past_lease = {
        "fields": {
            "运行状态": "已领取",
            "重试": False,
            "租约到期": "2026-07-28 11:59:59",
        }
    }
    assert worker.is_candidate(past_lease, now=now)


def test_claim_module_has_subprocess_import():
    """claim.py carries a fresh subprocess import for future phases."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        claim = importlib.import_module("feishu_worker.claim")
        assert hasattr(claim, "subprocess"), (
            "feishu_worker.claim must import subprocess"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import _lark_cli  # noqa: F811


# -- Round 2 / Part A regression: malformed JSON and narrow OSError retry --


def test_lark_json_no_retry_on_malformed_json(monkeypatch):
    """Malformed/non-JSON output must raise immediately — zero retries."""
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return worker.subprocess.CompletedProcess(
            ["lark-cli"], 0, stdout="not json at all <html>error</html>", stderr="",
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-list",
        )
    except RuntimeError as exc:
        assert "non-JSON" in str(exc)
    else:
        raise AssertionError("malformed JSON must raise RuntimeError")

    assert len(calls) == 1, f"malformed JSON must receive exactly 1 attempt, got {len(calls)}"
    assert len(sleeps) == 0


def test_lark_json_no_retry_on_non_object_json(monkeypatch):
    """Non-object (e.g. list) JSON value must raise immediately — zero retries."""
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return worker.subprocess.CompletedProcess(
            ["lark-cli"], 0, stdout='["array", "not", "object"]', stderr="",
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-list",
        )
    except RuntimeError as exc:
        assert "non-object" in str(exc)
    else:
        raise AssertionError("non-object JSON must raise RuntimeError")

    assert len(calls) == 1, f"non-object JSON must receive exactly 1 attempt, got {len(calls)}"
    assert len(sleeps) == 0


def test_lark_json_no_retry_on_non_transient_oserror(monkeypatch):
    """Non-transient OSError (e.g. FileNotFoundError) must raise immediately."""
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        raise FileNotFoundError("lark-cli binary not found")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-list",
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("FileNotFoundError must propagate immediately")

    assert len(calls) == 1, f"non-transient OSError must receive exactly 1 attempt, got {len(calls)}"
    assert len(sleeps) == 0


def test_lark_json_exhausted_oserror_includes_attempt_count_and_command(monkeypatch):
    """Exhausted transient OSError retries must report attempt count and command context."""
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        raise ConnectionRefusedError("Connection refused")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    try:
        worker.lark_json(
            worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
            "base", "+record-upsert", "--record-id", "rec_target",
        )
    except RuntimeError as exc:
        error_text = str(exc)
        assert "4 attempts" in error_text or str(1 + worker._LARK_MAX_RETRIES) in error_text
        assert "base" in error_text
        assert "Connection refused" in error_text
    else:
        raise AssertionError("exhausted transient OSError retries must raise RuntimeError")

    assert len(calls) == 1 + worker._LARK_MAX_RETRIES


def test_lark_json_transient_oserror_retries_connection_reset(monkeypatch):
    """ConnectionResetError (transient) must be retried."""
    calls = []
    sleeps = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionResetError("Connection reset by peer")
        return worker.subprocess.CompletedProcess(
            ["lark-cli"], 0, stdout='{"ok": true}', stderr="",
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    result = worker.lark_json(
        worker.WorkerConfig("base", "table", worker.Path("/fake/lark"), worker.Path("/tmp")),
        "base", "+record-list",
    )

    assert result == {"ok": True}
    assert len(calls) == 3


# -- Round 2 / Part B1: production web extractor has no experiment dependency --


def test_production_web_extractor_has_no_experiment_import():
    """The production web extractor module must not import from experiments."""
    import ast
    import sys as _sys

    web_path = SCRIPTS / "extractors" / "web.py"
    if not web_path.is_file():
        # Module does not exist yet; accept for now (will be created in B1)
        return
    source = web_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            if "experiments" in module:
                raise AssertionError(
                    f"production extractor must not import from experiments: {ast.dump(node)}"
                )


def test_package_public_web_uses_production_extractor_not_experiment(monkeypatch, tmp_path):
    """package_public_web must call production extractor, not experiments/web_raw_probe.py."""
    import inspect

    source = inspect.getsource(worker.package_public_web)
    assert "experiments" not in source, (
        f"package_public_web must not reference experiments/:\n{source}"
    )


# ── Round 3 Phase 1A: config module extraction compatibility ──────────


def test_config_module_re_exports_all_moved_names():
    """Every name is still a feishu_base_worker attribute.

    Names that stayed in config must be the same object; names moved back to
    the base worker must still be present as module attributes.
    """
    from feishu_worker import config as config_module

    config_names = [
        "WorkerConfig",
        "resolve_lark_cli",
        "load_config",
        "configured_knowledge_root",
    ]
    for name in config_names:
        assert hasattr(worker, name), (
            f"feishu_base_worker must expose {name}"
        )
        assert hasattr(config_module, name), (
            f"feishu_worker.config must expose {name}"
        )

    native_names = [
        "RETRYABLE_CODES",
        "_FATAL_LARK_CODES",
        "_LARK_BASE_DELAY",
        "_LARK_MAX_RETRIES",
        "_LARK_SUBPROCESS_TIMEOUT",
        "lark_json",
        "_extract_lark_error_code",
        "_is_fatal_lark_error",
        "_is_retryable_lark_error",
    ]
    for name in native_names:
        assert hasattr(worker, name), (
            f"feishu_base_worker must expose {name}"
        )
        assert not hasattr(config_module, name), (
            f"feishu_worker.config must NOT expose {name} (moved back to base worker)"
        )


def test_config_module_importable_independently():
    """feishu_worker.config can be imported without importing feishu_base_worker."""
    import importlib
    import sys

    # Remove feishu_base_worker and all its transitive dependants from
    # sys.modules so the config import cannot accidentally find it.
    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        config = importlib.import_module("feishu_worker.config")
        assert hasattr(config, "WorkerConfig")
        assert hasattr(config, "load_config")
        assert hasattr(config, "configured_knowledge_root")
        assert hasattr(config, "resolve_lark_cli")
        # These must NOT be present -- they belong to the protocol layer.
        assert not hasattr(config, "lark_json")
        assert not hasattr(config, "RETRYABLE_CODES")
        assert not hasattr(config, "_LARK_MAX_RETRIES")
    finally:
        # Restore the original imports so later tests are unaffected.
        import feishu_base_worker  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import _lark_cli  # noqa: F811


# -- Round 3 Phase 1B: io_utils extraction independence tests --


def test_io_utils_module_importable_independently():
    """feishu_worker.io_utils can be imported without importing feishu_base_worker."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        io_utils = importlib.import_module("feishu_worker.io_utils")
        for name in (
            "utc_now",
            "sha256_file",
            "atomic_write_json",
            "atomic_write_text",
            "_redact_error_text",
            "scalar_cell",
            "content_type_extension",
            "attachment_capability",
            "HOME",
        ):
            assert hasattr(io_utils, name), (
                f"feishu_worker.io_utils must expose {name}"
            )
        # These must NOT be present -- they belong to config or protocol.
        for name in ("WorkerConfig", "lark_json", "load_config", "ROOT"):
            assert not hasattr(io_utils, name), (
                f"feishu_worker.io_utils must NOT expose {name}"
            )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import _lark_cli  # noqa: F811


def test_both_leaf_modules_importable_without_base_worker():
    """Both io_utils and config import in a fresh subprocess with no
    feishu_base_worker module loaded in sys.modules."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        io_utils = importlib.import_module("feishu_worker.io_utils")
        config = importlib.import_module("feishu_worker.config")
        # Neither module should have dragged in feishu_base_worker
        assert "feishu_base_worker" not in sys.modules, (
            "leaf module import must not load feishu_base_worker"
        )
        # Each module has its own distinct namespace
        assert hasattr(io_utils, "utc_now")
        assert hasattr(config, "WorkerConfig")
        assert not hasattr(io_utils, "WorkerConfig")
        assert not hasattr(config, "utc_now")
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import _lark_cli  # noqa: F811


def test_io_utils_re_exports_all_moved_names():
    """Every name extracted to io_utils must be importable from feishu_base_worker."""
    io_utils_names = [
        "utc_now",
        "sha256_file",
        "atomic_write_json",
        "atomic_write_text",
        "_redact_error_text",
        "scalar_cell",
        "content_type_extension",
        "attachment_capability",
        "HOME",
    ]
    for name in io_utils_names:
        assert hasattr(worker, name), (
            f"feishu_base_worker must re-export {name}"
        )


def test_io_utils_re_exports_are_functionally_equivalent():
    """Re-exported names must be callable and produce identical results.

    Object identity (``is``) is not required because earlier independence
    tests manipulate ``sys.modules``, which can cause re-imports that create
    fresh function objects.  What matters is that the worker attributes
    resolve and behave identically to the io_utils originals.
    """
    from feishu_worker import io_utils as io_utils_module

    # Every re-exported name must resolve and be callable/accessible.
    for name in (
        "utc_now",
        "sha256_file",
        "atomic_write_json",
        "atomic_write_text",
        "_redact_error_text",
        "scalar_cell",
        "content_type_extension",
        "attachment_capability",
    ):
        worker_attr = getattr(worker, name)
        assert callable(worker_attr), (
            f"worker.{name} must be callable"
        )

    # HOME must be a Path and match io_utils.HOME
    assert isinstance(worker.HOME, Path)
    assert worker.HOME == io_utils_module.HOME

    # A quick behavioral smoke test via the worker re-export
    assert worker.scalar_cell(["single"]) == "single"
    assert worker.utc_now().endswith("+00:00")
    assert len(worker.sha256_file(
        Path(worker.__file__).parent / "feishu_worker" / "io_utils.py"
    )) == 64


def test_worker_has_zero_naive_datetime_now():
    """feishu_base_worker.py must have no naive datetime.now() calls."""
    import ast
    import inspect

    source = inspect.getsource(worker)
    tree = ast.parse(source)

    naive_now_found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "now"
                and isinstance(func.value, ast.Name)
                and func.value.id == "datetime"
            ):
                # Only flag if no timezone argument (no keywords, no args)
                if not node.args and not node.keywords:
                    naive_now_found.append((node.lineno, ast.unparse(node)))

    assert len(naive_now_found) == 0, (
        f"Naive datetime.now() calls found in worker: {naive_now_found}"
    )


# -- Round 3 Phase 1B: io_utils function correctness tests --


def test_io_utils_scalar_cell_normalizes_and_passthrough():
    """scalar_cell normalizes single-element lists, passes through everything else."""
    assert worker.scalar_cell(["only"]) == "only"
    assert worker.scalar_cell(["a", "b"]) == ["a", "b"]
    assert worker.scalar_cell("plain") == "plain"
    assert worker.scalar_cell(None) is None
    assert worker.scalar_cell([]) == []
    assert worker.scalar_cell(42) == 42


def test_io_utils_content_type_extension_edge_cases():
    """content_type_extension handles edge cases and unknown types."""
    assert worker.content_type_extension(None) == ""
    assert worker.content_type_extension("") == ""
    assert worker.content_type_extension("application/pdf") == ".pdf"
    assert worker.content_type_extension("application/pdf; charset=binary") == ".pdf"
    assert worker.content_type_extension("image/png") == ".png"
    assert worker.content_type_extension("unknown/type") == ""


def test_io_utils_attachment_capability_all_routes():
    """attachment_capability routes all recognized extensions."""
    assert worker.attachment_capability(Path("doc.pdf")) == ("pdf.mineru", "text")
    assert worker.attachment_capability(Path("photo.png")) == ("image.rapidocr", "ocr")
    assert worker.attachment_capability(Path("photo.jpg")) == ("image.rapidocr", "ocr")
    assert worker.attachment_capability(Path("photo.jpeg")) == ("image.rapidocr", "ocr")
    assert worker.attachment_capability(Path("clip.mp4")) == ("video.watch", "asr")
    assert worker.attachment_capability(Path("clip.webm")) == ("video.watch", "asr")
    assert worker.attachment_capability(Path("audio.mp3")) == ("audio.faster-whisper", "asr")
    assert worker.attachment_capability(Path("audio.wav")) == ("audio.faster-whisper", "asr")
    assert worker.attachment_capability(Path("notes.txt")) == ("office.markitdown", "text")
    assert worker.attachment_capability(Path("sheet.csv")) == ("office.markitdown", "text")


def test_io_utils_atomic_json_roundtrip(tmp_path):
    """atomic_write_json writes valid JSON that roundtrips exactly."""
    dest = tmp_path / "sub" / "data.json"
    data = {"key": "value", "list": [1, 2, 3], "nested": {"a": True}}
    worker.atomic_write_json(dest, data)
    assert dest.is_file()
    import json as _json
    loaded = _json.loads(dest.read_text(encoding="utf-8"))
    assert loaded == data


def test_io_utils_atomic_text_roundtrip(tmp_path):
    """atomic_write_text writes text that roundtrips exactly."""
    dest = tmp_path / "sub" / "notes.txt"
    content = "line 1\nline 2\nline 3\n"
    worker.atomic_write_text(dest, content)
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == content


def test_io_utils_atomic_write_json_cleans_up_temp_on_failure(tmp_path):
    """atomic_write_json must remove temp file on serialization failure."""
    dest = tmp_path / "data.json"
    # A lambda cannot be JSON-serialized
    try:
        worker.atomic_write_json(dest, {"bad": lambda: None})
    except TypeError:
        pass
    # Only dest should remain (it may or may not exist); temp must be gone
    temps = list(dest.parent.glob(".*.data.json.*"))
    assert len(temps) == 0, f"Temp files leaked: {temps}"


def test_io_utils_utc_now_is_aware_iso():
    """utc_now returns an ISO string with timezone info."""
    result = worker.utc_now()
    assert isinstance(result, str)
    assert "T" in result
    assert "+" in result or result.endswith("Z")
    # Parse to verify it's a valid aware datetime
    parsed = worker.datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


def test_io_utils_sha256_deterministic(tmp_path):
    """sha256_file is deterministic and matches hashlib."""
    f = tmp_path / "content.bin"
    f.write_bytes(b"hello world")
    digest = worker.sha256_file(f)
    assert len(digest) == 64
    assert digest == worker.hashlib.sha256(b"hello world").hexdigest()
    # Second call yields same result
    assert worker.sha256_file(f) == digest


def test_io_utils_redaction_is_idempotent():
    """_redact_error_text is idempotent -- redacting twice equals redacting once."""
    original = "Bearer tokensecret123 at path /home/user and key=abcdefghij"
    once = worker._redact_error_text(original)
    twice = worker._redact_error_text(once)
    assert once == twice


# ── Round 3 Phase 2: base_client extraction compatibility ──────────────


def test_base_client_module_importable_independently():
    """feishu_worker.base_client imports in a fresh subprocess without
    feishu_base_worker loaded in sys.modules."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        base_client = importlib.import_module("feishu_worker.base_client")
        for name in (
            "lark_json",
            "parse_json_output",
            "base_args",
            "update_record",
            "create_record",
            "list_records",
            "get_record",
            "list_review_records",
            "RETRYABLE_CODES",
            "_FATAL_LARK_CODES",
            "_LARK_MAX_RETRIES",
            "_LARK_BASE_DELAY",
            "_LARK_SUBPROCESS_TIMEOUT",
            "_extract_lark_error_code",
            "_is_fatal_lark_error",
            "_is_retryable_lark_error",
            "_parse_record_rows",
        ):
            assert hasattr(base_client, name), (
                f"feishu_worker.base_client must expose {name}"
            )
        assert "feishu_base_worker" not in sys.modules, (
            "base_client import must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import _lark_cli  # noqa: F811


def test_base_client_re_exports_all_moved_names():
    """Every name extracted to base_client is importable from feishu_base_worker."""
    base_client_names = [
        "RETRYABLE_CODES",
        "_FATAL_LARK_CODES",
        "_LARK_BASE_DELAY",
        "_LARK_MAX_RETRIES",
        "_LARK_SUBPROCESS_TIMEOUT",
        "_extract_lark_error_code",
        "_is_fatal_lark_error",
        "_is_retryable_lark_error",
        "lark_json",
        "parse_json_output",
        "base_args",
        "update_record",
        "create_record",
        "list_records",
        "get_record",
        "list_review_records",
    ]
    for name in base_client_names:
        assert hasattr(worker, name), (
            f"feishu_base_worker must expose {name}"
        )


def test_base_client_names_not_on_config_or_io_utils():
    """base_client names must stay out of config and io_utils module namespaces."""
    from feishu_worker import config as config_module
    from feishu_worker import io_utils as io_utils_module

    protocol_names = {
        "lark_json", "parse_json_output", "base_args",
        "update_record", "create_record", "list_records",
        "get_record", "list_review_records",
        "RETRYABLE_CODES", "_FATAL_LARK_CODES",
        "_LARK_MAX_RETRIES", "_LARK_BASE_DELAY", "_LARK_SUBPROCESS_TIMEOUT",
        "_extract_lark_error_code", "_is_fatal_lark_error", "_is_retryable_lark_error",
        "_parse_record_rows",
    }
    for name in protocol_names:
        assert not hasattr(config_module, name), (
            f"feishu_worker.config must NOT expose {name}"
        )
        assert not hasattr(io_utils_module, name), (
            f"feishu_worker.io_utils must NOT expose {name}"
        )


def test_base_client_imports_only_leaf_dependencies():
    """base_client.py must not import from feishu_base_worker."""
    import ast
    from feishu_worker import base_client as bc

    source = __import__("inspect").getsource(bc)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            if "feishu_base_worker" in module:
                raise AssertionError(
                    f"base_client must not import feishu_base_worker: {ast.dump(node)}"
                )


# ── parse_json_output unit tests ───────────────────────────────────────


def test_parse_json_output_success():
    result = worker.subprocess.CompletedProcess(
        ["lark-cli"], 0, stdout='{"ok": true}', stderr="",
    )
    assert worker.parse_json_output(result) == {"ok": True}


def test_parse_json_output_allows_non_zero_with_matching_code():
    result = worker.subprocess.CompletedProcess(
        ["connector"], 2, stdout='{"status": "ok"}', stderr="",
    )
    assert worker.parse_json_output(result, allow_codes={0, 2}) == {"status": "ok"}


def test_parse_json_output_rejects_unexpected_return_code():
    result = worker.subprocess.CompletedProcess(
        ["lark-cli"], 1, stdout="{}", stderr="command failed",
    )
    try:
        worker.parse_json_output(result)
    except RuntimeError as exc:
        assert "1" in str(exc)
    else:
        raise AssertionError("unexpected return code must raise RuntimeError")


def test_parse_json_output_raises_on_non_json():
    result = worker.subprocess.CompletedProcess(
        ["lark-cli"], 0, stdout="not json", stderr="",
    )
    try:
        worker.parse_json_output(result)
    except RuntimeError as exc:
        assert "non-JSON" in str(exc)
    else:
        raise AssertionError("non-JSON output must raise RuntimeError")


def test_parse_json_output_raises_on_non_object():
    result = worker.subprocess.CompletedProcess(
        ["lark-cli"], 0, stdout='[1,2,3]', stderr="",
    )
    try:
        worker.parse_json_output(result)
    except RuntimeError as exc:
        assert "non-object" in str(exc)
    else:
        raise AssertionError("non-object JSON must raise RuntimeError")


# ── base_args unit test ────────────────────────────────────────────────


def test_base_args_format(tmp_path):
    config = worker.WorkerConfig(
        "tok123", "tbl456", tmp_path / "lark.exe", tmp_path,
    )
    args = worker.base_args(config)
    assert args == [
        "--base-token", "tok123",
        "--table-id", "tbl456",
        "--as", "user",
    ]


def test_base_args_respects_explicit_identity(tmp_path):
    config = worker.WorkerConfig(
        "tok", "tbl", tmp_path / "lark.exe", tmp_path,
        identity="bot",
    )
    assert worker.base_args(config)[-2:] == ["--as", "bot"]


# ── _parse_record_rows unit tests ──────────────────────────────────────


def test_parse_record_rows_from_list_format():
    from feishu_worker.base_client import _parse_record_rows

    rows = [["https://example.com", "待处理", False]]
    fields = ["内容", "运行状态", "重试"]
    record_ids = ["rec_1"]

    result = _parse_record_rows(rows, fields, record_ids)
    assert result == [
        {"record_id": "rec_1", "fields": {"内容": "https://example.com", "运行状态": "待处理", "重试": False}},
    ]


def test_parse_record_rows_from_dict_format():
    from feishu_worker.base_client import _parse_record_rows

    rows = [{"record_id": "rec_2", "fields": {"内容": "test", "运行状态": "已领取"}}]
    fields = ["内容", "运行状态"]
    record_ids = ["rec_2"]

    result = _parse_record_rows(rows, fields, record_ids)
    assert result == [
        {"record_id": "rec_2", "fields": {"内容": "test", "运行状态": "已领取"}},
    ]


def test_parse_record_rows_skips_empty_rows():
    from feishu_worker.base_client import _parse_record_rows

    result = _parse_record_rows(["not-dict-or-list"], ["f1"], ["rec_1"])
    assert result == []


def test_parse_record_rows_dict_without_record_id_falls_back_to_list():
    from feishu_worker.base_client import _parse_record_rows

    rows = [{"fields": {"内容": "test"}}]
    result = _parse_record_rows(rows, ["内容"], ["rec_backup"])
    assert result == [
        {"record_id": "rec_backup", "fields": {"内容": "test"}},
    ]


def test_parse_record_rows_handles_extra_ids():
    from feishu_worker.base_client import _parse_record_rows

    rows = [["a"], ["b"]]
    result = _parse_record_rows(rows, ["f1"], ["id1", "id2", "id3"])
    assert len(result) == 2
    assert result[0]["record_id"] == "id1"
    assert result[1]["record_id"] == "id2"


def test_parse_record_rows_uses_fewer_ids():
    from feishu_worker.base_client import _parse_record_rows

    rows = [["a"], ["b"]]
    result = _parse_record_rows(rows, ["f1"], ["only_one"])
    # First row gets the only id; second gets None and is excluded
    assert len(result) == 1
    assert result[0]["record_id"] == "only_one"


# ── lark_json / wrapper integration tests ──────────────────────────────


def test_worker_lark_json_wrapper_passes_root(monkeypatch, tmp_path):
    """The worker's lark_json wrapper must forward root=ROOT to base_client."""
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path)
    captured_root = []

    def capture_root(cfg, *args, root):
        captured_root.append(root)
        return {"ok": True}

    monkeypatch.setattr(
        worker,
        "_base_client_lark_json",
        capture_root,
    )

    worker.lark_json(config, "base", "+record-list")
    assert captured_root == [worker.ROOT]


def test_update_record_includes_json_payload_in_command(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path)
    commands = []
    monkeypatch.setattr(worker, "lark_json", lambda _c, *args: commands.append(args) or {})
    worker.update_record(config, "rec_1", {"运行状态": "Raw就绪"})
    # Positional args: "base", "+record-upsert", *base_args(...), "--record-id", "rec_1", "--json", "{...}"
    assert commands[0][0] == "base"
    assert commands[0][1] == "+record-upsert"
    assert "--record-id" in commands[0]
    assert commands[0][commands[0].index("--record-id") + 1] == "rec_1"
    assert "--json" in commands[0]


def test_created_record_id_accepts_current_lark_cli_response_shape():
    assert worker.created_record_id({
        "ok": True,
        "data": {"record": {"record_id_list": ["rec_current"]}},
    }) == "rec_current"


def test_promote_candidate_wrapper_forwards_explicit_root(monkeypatch, tmp_path):
    captured = {}

    def fake_promote(candidate_path, reviewed_body, review, *, root, knowledge_root):
        captured.update({"root": root, "knowledge_root": knowledge_root})
        return tmp_path / "wiki" / "accepted.md"

    monkeypatch.setattr(worker, "_review_promote_candidate_document", fake_promote)
    result = worker.promote_candidate_document(
        tmp_path / "draft.md", "body", {}, root=tmp_path, knowledge_root=tmp_path / "kb"
    )

    assert result == tmp_path / "wiki" / "accepted.md"
    assert captured == {"root": tmp_path, "knowledge_root": tmp_path / "kb"}


def test_create_record_passes_fields_as_compact_json(monkeypatch, tmp_path):
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path)
    commands = []
    monkeypatch.setattr(worker, "lark_json", lambda _c, *args: commands.append(args) or {})
    worker.create_record(config, {"内容": "https://example.com"})
    json_idx = commands[0].index("--json") + 1
    assert "https://example.com" in commands[0][json_idx]


def test_record_crud_errors_propagate_to_main_cli(monkeypatch, tmp_path):
    """RuntimeError from lark_json must propagate through the wrapper
    so the main() CLI can catch it."""
    config = worker.WorkerConfig("base", "table", tmp_path / "lark.exe", tmp_path)
    monkeypatch.setattr(
        worker,
        "_base_client_lark_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("AUTH_FAILED")
        ),
    )
    try:
        worker.update_record(config, "rec_1", {"status": "test"})
    except RuntimeError as exc:
        assert "AUTH_FAILED" in str(exc)
    else:
        raise AssertionError("lark_json errors must propagate to record CRUD callers")


# ── Round 3 Phase 3A: claim module isolation tests ─────────────────────────


def test_claim_module_importable_independently():
    """feishu_worker.claim imports in a fresh subprocess without
    feishu_base_worker loaded in sys.modules."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        claim = importlib.import_module("feishu_worker.claim")
        for name in (
            "parse_base_datetime",
            "is_candidate",
            "local_claim_lock",
            "claim_next_record",
            "claim_record",
            "release_lease",
        ):
            assert hasattr(claim, name), (
                f"feishu_worker.claim must expose {name}"
            )
        # These must NOT be present -- they belong to the orchestrator.
        for name in ("process_record", "parse_candidate_document", "main", "ROOT"):
            assert not hasattr(claim, name), (
                f"feishu_worker.claim must NOT expose {name}"
            )
        assert "feishu_base_worker" not in sys.modules, (
            "claim import must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import _lark_cli  # noqa: F811


def test_claim_re_exports_all_moved_names():
    """Every name extracted to claim is importable from feishu_base_worker."""
    claim_names = [
        "parse_base_datetime",
        "is_candidate",
        "local_claim_lock",
        "claim_next_record",
        "claim_record",
        "release_lease",
    ]
    missing = [n for n in claim_names if not hasattr(worker, n)]
    assert not missing, (
        f"feishu_base_worker must re-export: {', '.join(missing)}"
    )


def test_all_leaf_modules_importable_without_base_worker():
    """All four leaf modules (config, io_utils, base_client, claim) import
    cleanly without feishu_base_worker loaded."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        for mod_name in (
            "feishu_worker.config",
            "feishu_worker.io_utils",
            "feishu_worker.base_client",
            "feishu_worker.claim",
        ):
            mod = importlib.import_module(mod_name)
            assert mod is not None, f"Failed to import {mod_name}"
        assert "feishu_base_worker" not in sys.modules, (
            "Leaf module imports must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import _lark_cli  # noqa: F811


def test_claim_direct_usage_without_legacy_wrappers(monkeypatch, tmp_path):
    """claim.py functions work when called directly with injected callables
    (no dependency on feishu_base_worker wrappers)."""
    from feishu_worker.claim import (
        claim_next_record,
        claim_record,
        release_lease,
        is_candidate,
        parse_base_datetime,
        local_claim_lock,
    )
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        "base", "table", tmp_path / "lark.exe", tmp_path, lease_seconds=60,
    )

    # ---- claim_next_record ----
    records = [{"record_id": "rec_1", "fields": {"运行状态": "待处理", "重试": False}}]
    updates: list = []

    def fake_list(_config, _limit):
        return records

    def fake_update(_config, record_id, patch):
        updates.append((record_id, patch))
        return {}

    @worker.contextmanager
    def fake_lock(_config):
        yield

    result = claim_next_record(
        config,
        limit=10,
        _list_fn=fake_list,
        _update_fn=fake_update,
        _lock_fn=fake_lock,
    )
    assert result is not None
    assert result[0] == records[0]
    assert updates[0][0] == "rec_1"
    assert updates[0][1]["运行状态"] == "已领取"

    # ---- claim_record ----
    get_calls: list = []

    def fake_get(_config, record_id, projection):
        get_calls.append((record_id, projection))
        return {"record_id": record_id, "fields": {"运行状态": "待处理", "重试": False}}

    result2 = claim_record(
        config, "rec_explicit",
        _get_fn=fake_get,
        _update_fn=fake_update,
        _lock_fn=fake_lock,
    )
    assert result2 is not None
    assert get_calls[0][0] == "rec_explicit"

    # ---- release_lease ----
    release_updates: list = []

    def fake_release_update(_config, record_id, patch):
        release_updates.append((record_id, patch))
        return {}

    release_lease(config, "rec_release", _update_fn=fake_release_update)
    assert release_updates[0][0] == "rec_release"
    assert release_updates[0][1]["租约所有者"] is None
    assert release_updates[0][1]["租约到期"] is None


# ── Round 3 Phase 4: capture module isolation tests ──────────────────────────


def test_capture_module_importable_independently():
    """feishu_worker.capture imports in a fresh subprocess without
    feishu_base_worker loaded in sys.modules."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        capture = importlib.import_module("feishu_worker.capture")
        for name in (
            "URL_RE",
            "extract_url",
            "normalize_attachments",
            "capture_user_note",
            "capture_content_hash",
            "envelope_content_hash",
            "capture_envelope",
        ):
            assert hasattr(capture, name), (
                f"feishu_worker.capture must expose {name}"
            )
        # These must NOT be present -- they belong to the orchestrator.
        for name in ("process_record", "parse_candidate_document", "main", "ROOT", "lark_json"):
            assert not hasattr(capture, name), (
                f"feishu_worker.capture must NOT expose {name}"
            )
        assert "feishu_base_worker" not in sys.modules, (
            "capture import must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.capture  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import _lark_cli  # noqa: F811


def test_capture_module_has_subprocess_import():
    """capture.py carries a fresh subprocess import for future phases."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        capture = importlib.import_module("feishu_worker.capture")
        assert hasattr(capture, "subprocess"), (
            "feishu_worker.capture must import subprocess"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.capture  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import _lark_cli  # noqa: F811


def test_capture_re_exports_all_moved_names():
    """Every name extracted to capture is importable from feishu_base_worker."""
    capture_names = [
        "URL_RE",
        "extract_url",
        "normalize_attachments",
        "capture_user_note",
        "capture_content_hash",
        "envelope_content_hash",
        "capture_envelope",
    ]
    missing = [n for n in capture_names if not hasattr(worker, n)]
    assert not missing, (
        f"feishu_base_worker must re-export: {', '.join(missing)}"
    )


def test_capture_names_not_on_other_leaf_modules():
    """Capture names must stay out of config, io_utils, base_client, and claim namespaces."""
    from feishu_worker import config as config_module
    from feishu_worker import io_utils as io_utils_module
    from feishu_worker import base_client as base_client_module
    from feishu_worker import claim as claim_module

    capture_names = {
        "URL_RE",
        "extract_url",
        "normalize_attachments",
        "capture_user_note",
        "capture_content_hash",
        "envelope_content_hash",
        "capture_envelope",
    }
    for name in capture_names:
        assert not hasattr(config_module, name), (
            f"feishu_worker.config must NOT expose {name}"
        )
        assert not hasattr(io_utils_module, name), (
            f"feishu_worker.io_utils must NOT expose {name}"
        )
        assert not hasattr(base_client_module, name), (
            f"feishu_worker.base_client must NOT expose {name}"
        )
        assert not hasattr(claim_module, name), (
            f"feishu_worker.claim must NOT expose {name}"
        )


def test_capture_imports_only_leaf_dependencies():
    """capture.py must not import from feishu_base_worker."""
    import ast
    from feishu_worker import capture as cap

    source = __import__("inspect").getsource(cap)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            if "feishu_base_worker" in module:
                raise AssertionError(
                    f"capture must not import feishu_base_worker: {ast.dump(node)}"
                )


# ── Round 3 Phase 4: capture contract regression tests ──────────────────────
# These lock capture-envelope v0.2 field names and values byte-for-byte.


def test_capture_envelope_v02_schema_version():
    """capture_envelope must produce schema_version oks-capture-envelope/v0.2."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    assert envelope["schema_version"] == "oks-capture-envelope/v0.2"


def test_capture_envelope_v02_field_names():
    """capture_envelope must contain every v0.2 field name exactly."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    expected_fields = {
        "schema_version",
        "capture_id",
        "capture_revision",
        "source_type",
        "source_uri",
        "captured_at",
        "submitted_by",
        "user_note",
        "content",
        "content_hash",
        "hash_algorithm",
        "source_record",
        "attachments",
        "capture_adapter",
    }
    missing = expected_fields - set(envelope.keys())
    assert not missing, f"capture_envelope missing fields: {missing}"
    extra = set(envelope.keys()) - expected_fields
    assert not extra, f"capture_envelope has unexpected fields: {extra}"


def test_capture_envelope_v02_source_record_shape():
    """source_record must contain a token fingerprint, never the token itself."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    sr = envelope["source_record"]
    assert sr["base_token_hash"] == worker.hashlib.sha256(b"tok1").hexdigest()[:12]
    assert "base_token" not in sr
    assert sr["table_id"] == "tbl1"
    assert sr["record_id"] == "rec_test"
    assert sr["revision"] is None
    assert set(sr.keys()) == {"base_token_hash", "table_id", "record_id", "revision"}


def test_capture_envelope_never_serializes_base_token():
    """Capture metadata may correlate a Base but must never persist its token."""
    token = "base_token_that_must_not_reach_the_data_plane"
    config = worker.WorkerConfig(token, "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})

    assert envelope["source_uri"] == "feishu-base://tbl1/rec_test"
    assert token not in worker.json.dumps(envelope, ensure_ascii=False)


def test_capture_envelope_v02_capture_adapter_shape():
    """capture_adapter must name feishu.base at version 0.1.0."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    assert envelope["capture_adapter"] == {"name": "feishu.base", "version": "0.1.0"}


def test_capture_envelope_v02_content_hash_algorithm():
    """content_hash must be a 64-char hex sha256 via sha256-canonical-json-v1."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    assert envelope["hash_algorithm"] == "sha256-canonical-json-v1"
    assert len(envelope["content_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in envelope["content_hash"])


def test_capture_envelope_v02_capture_id_format():
    """capture_id must be feishu-{record_id}-{12-char content_hash_prefix}."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_abc123", {"内容": "hello"})
    prefix = f"feishu-rec_abc123-{envelope['content_hash'][:12]}"
    assert envelope["capture_id"] == prefix


def test_capture_envelope_v02_captured_at_is_aware_utc():
    """captured_at must be an aware UTC ISO timestamp."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    parsed = worker.datetime.fromisoformat(envelope["captured_at"])
    assert parsed.tzinfo is not None, "captured_at must be timezone-aware"


def test_capture_envelope_v02_attachment_normalization():
    """normalize_attachments must produce sorted, stable attachment descriptors."""
    from feishu_worker.capture import normalize_attachments

    raw = [
        {"file_token": "f2", "name": "b.txt", "size": 10, "mime_type": "text/plain"},
        {"file_token": "f1", "name": "a.png", "size": 20, "mime_type": "image/png"},
    ]
    result = normalize_attachments(raw)
    # Must be sorted by (source_token, name)
    assert result[0]["source_token"] == "f1"
    assert result[0]["name"] == "a.png"
    assert result[1]["source_token"] == "f2"
    assert result[1]["name"] == "b.txt"
    # All descriptor fields present
    for item in result:
        assert set(item.keys()) == {
            "source_token", "name", "size", "mime_type", "sha256", "source_uri",
        }


def test_capture_envelope_v02_attachment_token_fallback():
    """normalize_attachments must fall back through file_token→token→id for source_token."""
    from feishu_worker.capture import normalize_attachments

    assert normalize_attachments([{"id": "abc", "name": "x"}])[0]["source_token"] == "abc"
    assert normalize_attachments([{"token": "tok", "name": "x"}])[0]["source_token"] == "tok"
    # When no token-like field, falls back to name
    result = normalize_attachments([{"name": "report.pdf"}])
    assert result[0]["source_token"] == "report.pdf"


def test_capture_envelope_v02_url_extraction():
    """extract_url must find http/https URLs and strip trailing punctuation."""
    from feishu_worker.capture import extract_url

    assert extract_url("https://example.com/path") == "https://example.com/path"
    assert extract_url("[label] https://example.com/a?b=1。") == "https://example.com/a?b=1"
    assert extract_url("http://foo.bar/baz, and more") == "http://foo.bar/baz"
    assert extract_url("no url here") is None
    assert extract_url(None) is None
    assert extract_url(123) is None


def test_capture_envelope_v02_content_hash_deterministic():
    """capture_content_hash must be deterministic for identical inputs."""
    from feishu_worker.capture import capture_content_hash

    fields = {"内容": "same content", "思考": "same note"}
    h1 = capture_content_hash(fields)
    h2 = capture_content_hash(fields)
    assert h1 == h2


def test_capture_envelope_v02_revision_is_always_one():
    """capture_revision must always be 1 — envelope is immutable after creation."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    assert envelope["capture_revision"] == 1


def test_capture_envelope_v02_submitted_by_is_none():
    """submitted_by must be None — the worker captures, a human submits."""
    config = worker.WorkerConfig("tok1", "tbl1", worker.Path("/fake/lark"), worker.Path("/tmp"))
    envelope = worker.capture_envelope(config, "rec_test", {"内容": "hello"})
    assert envelope["submitted_by"] is None


# ── Updated: all five leaf modules importable without base worker ────────────


def test_all_leaf_modules_importable_without_base_worker_round3():
    """All five leaf modules (config, io_utils, base_client, claim, capture) import
    cleanly without feishu_base_worker loaded."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        for mod_name in (
            "feishu_worker.config",
            "feishu_worker.io_utils",
            "feishu_worker.base_client",
            "feishu_worker.claim",
            "feishu_worker.capture",
        ):
            mod = importlib.import_module(mod_name)
            assert mod is not None, f"Failed to import {mod_name}"
        assert "feishu_base_worker" not in sys.modules, (
            "Leaf module imports must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import feishu_worker.capture  # noqa: F811
        import _lark_cli  # noqa: F811


# ── Round 3: source_router module extraction ──────────────────────────────


def test_source_router_module_importable_independently():
    """feishu_worker.source_router imports without feishu_base_worker loaded."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        sr = importlib.import_module("feishu_worker.source_router")
        for name in (
            "_connector_binary",
            "_run_or_validate",
            "package_local_attachment",
            "package_routed_source",
            "package_public_web",
        ):
            assert hasattr(sr, name), (
                f"feishu_worker.source_router must expose {name}"
            )
        # Must NOT expose orchestrator-level names.
        for name in ("ROOT", "process_record", "main", "load_config"):
            assert not hasattr(sr, name), (
                f"feishu_worker.source_router must NOT expose {name}"
            )
        assert "feishu_base_worker" not in sys.modules, (
            "source_router import must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.source_router  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import _lark_cli  # noqa: F811


def test_all_six_leaf_modules_importable_without_base_worker():
    """All six leaf modules import cleanly without feishu_base_worker loaded."""
    import importlib
    import sys

    stale = {k for k in sys.modules if k.startswith("feishu_base_worker")}
    stale.update(k for k in sys.modules if k.startswith("feishu_worker"))
    stale.update(k for k in sys.modules if k.startswith("_lark_cli"))
    for key in stale:
        del sys.modules[key]

    try:
        for mod_name in (
            "feishu_worker.config",
            "feishu_worker.io_utils",
            "feishu_worker.base_client",
            "feishu_worker.claim",
            "feishu_worker.capture",
            "feishu_worker.source_router",
        ):
            mod = importlib.import_module(mod_name)
            assert mod is not None, f"Failed to import {mod_name}"
        assert "feishu_base_worker" not in sys.modules, (
            "Leaf module imports must not load feishu_base_worker"
        )
    finally:
        import feishu_base_worker  # noqa: F811
        import feishu_worker.source_router  # noqa: F811
        import feishu_worker.config  # noqa: F811
        import feishu_worker.io_utils  # noqa: F811
        import feishu_worker.base_client  # noqa: F811
        import feishu_worker.claim  # noqa: F811
        import feishu_worker.capture  # noqa: F811
        import _lark_cli  # noqa: F811


def test_package_local_attachment_uses_shared_run_or_validate():
    """package_local_attachment delegates to _run_or_validate."""
    import inspect
    from feishu_worker import source_router as sr

    source = inspect.getsource(sr.package_local_attachment)
    assert "_run_or_validate" in source, (
        f"package_local_attachment must call _run_or_validate:\n{source}"
    )


def test_package_routed_source_uses_shared_run_or_validate():
    """package_routed_source delegates to _run_or_validate."""
    import inspect
    from feishu_worker import source_router as sr

    source = inspect.getsource(sr.package_routed_source)
    assert "_run_or_validate" in source, (
        f"package_routed_source must call _run_or_validate:\n{source}"
    )


def test_source_router_package_public_web_uses_extractors_web():
    """source_router.package_public_web imports from extractors.web, not experiments/."""
    import inspect
    from feishu_worker import source_router as sr

    source = inspect.getsource(sr.package_public_web)
    assert "extractors.web" in source, (
        f"package_public_web must import from extractors.web:\n{source}"
    )
    assert "experiments" not in source, (
        f"package_public_web must not reference experiments/:\n{source}"
    )


def test_source_router_module_has_no_experiment_import():
    """source_router module has zero imports from experiments/."""
    import ast
    from feishu_worker import source_router as sr

    source = Path(sr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            if "experiments" in module:
                raise AssertionError(
                    f"source_router must not import from experiments: {ast.dump(node)}"
                )


def test_source_router_re_exports_in_base_worker():
    """All source_router public names are importable from feishu_base_worker."""
    names = [
        "package_local_attachment",
        "package_routed_source",
        "package_public_web",
    ]
    for name in names:
        assert hasattr(worker, name), (
            f"feishu_base_worker must expose {name}"
        )
        assert callable(getattr(worker, name)), (
            f"worker.{name} must be callable"
        )


def test_connector_binary_still_accessible_from_worker():
    """_connector_binary is still accessible as a feishu_base_worker attribute."""
    assert hasattr(worker, "_connector_binary")
    assert callable(worker._connector_binary)


def test_connector_binary_dev_fallback_runs_through_interpreter(tmp_path, monkeypatch):
    """A bare .py path as argv[0] fails on Windows (WinError 193)."""
    from feishu_worker.source_router import _connector_binary

    script = tmp_path / "scripts" / "raw_bundle_adapter.py"
    script.parent.mkdir(parents=True)
    script.write_text("# stub", encoding="utf-8")
    # Force the dev fallback: no entry point next to the interpreter.
    monkeypatch.setattr(Path, "is_file", lambda self: self == script)

    argv = _connector_binary(tmp_path)
    assert argv == [sys.executable, str(script)]
    assert not argv[0].endswith(".py")


def test_source_router_fresh_subprocess_import():
    """source_router imports in a fresh subprocess without the base worker."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'code'); "
            "from feishu_worker.source_router import "
            "_connector_binary, _run_or_validate, "
            "package_local_attachment, package_routed_source, package_public_web; "
            "print('source_router imported OK')",
        ],
        cwd=str(SCRIPTS.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"source_router subprocess import failed:\n{proc.stderr}"
    )
    assert "source_router imported OK" in proc.stdout
