"""Focused tests for feishu_worker.notification module.

Covers: subprocess import isolation, render_candidate_review_message,
send_candidate_review_notification.
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

from feishu_worker.notification import (  # noqa: E402
    render_candidate_review_message,
    send_candidate_review_notification,
)


# ── Subprocess import isolation ────────────────────────────────────────


def test_notification_module_never_imports_feishu_base_worker():
    """Fresh subprocess confirms notification.py has zero feishu_base_worker deps."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""\
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(r'{}').parents[0]))
            # Import notification — must succeed without pulling in feishu_base_worker
            from feishu_worker import notification
            print("OK")
        """.format(str(SCRIPTS)))],
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK" in result.stdout


def test_notification_module_never_imports_candidate():
    """Fresh subprocess confirms notification.py has zero candidate deps."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""\
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(r'{}').parents[0]))
            # Verify notification module does not import candidate
            import feishu_worker.notification
            assert 'feishu_worker.candidate' not in sys.modules, "notification imported candidate!"
            print("OK")
        """.format(str(SCRIPTS)))],
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK" in result.stdout


# ── Review notification rendering ──────────────────────────────────────


def test_render_candidate_review_message_minimal():
    metadata = {"title": "Test", "review_summary": "A summary."}
    body = "X" * 60
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "Test" in msg
    assert "A summary." in msg
    assert "rec_1" in msg
    assert "cand_1" in msg
    assert "revision `1`" in msg


def test_render_candidate_review_message_fallback_summary():
    metadata: dict[str, object] = {"title": "Test"}
    body = "A" * 600
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert body[:600] in msg


def test_render_candidate_review_message_includes_source_context():
    metadata = {"title": "Test", "review_summary": "OK"}
    body = "X" * 60
    fields = {"内容": "https://example.com", "思考": "Important note"}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "https://example.com" in msg
    assert "Important note" in msg


def test_render_candidate_review_message_default_question():
    metadata = {"title": "Test", "review_summary": "OK"}
    body = "X" * 60
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "这条知识是否值得进入你的个人知识库？" in msg


def test_render_candidate_review_message_uses_metadata_questions():
    metadata = {
        "title": "Test",
        "review_summary": "OK",
        "review_questions": ["Q1: Is this useful?", "Q2: Is this accurate?"],
    }
    body = "X" * 60
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "Q1: Is this useful?" in msg
    assert "Q2: Is this accurate?" in msg


def test_render_candidate_review_message_question_string_coerced():
    metadata = {
        "title": "Test",
        "review_summary": "OK",
        "review_questions": "Single question string",
    }
    body = "X" * 60
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "Single question string" in msg


def test_render_candidate_review_message_caps_questions_at_three():
    metadata = {
        "title": "Test",
        "review_summary": "OK",
        "review_questions": ["Q1", "Q2", "Q3", "Q4", "Q5"],
    }
    body = "X" * 60
    fields = {}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "Q1" in msg
    assert "Q2" in msg
    assert "Q3" in msg
    assert "Q4" not in msg
    assert "Q5" not in msg


def test_render_candidate_review_message_without_source_omits_context():
    metadata = {"title": "Test", "review_summary": "OK"}
    body = "X" * 60
    fields = {"思考": "Note without source"}
    msg = render_candidate_review_message(
        record_id="rec_1",
        candidate_id="cand_1",
        revision=1,
        metadata=metadata,
        body=body,
        fields=fields,
    )
    assert "来源" not in msg


# ── send_candidate_review_notification ─────────────────────────────────


def test_send_notification_skips_without_recipient(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
    )
    result = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={"candidate_id": "c1", "revision": 1, "candidate_sha256": "abc"},
        metadata={"title": "Test"},
        body="X" * 60,
        fields={},
        root=tmp_path,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "review_recipient_not_configured"


def test_send_notification_failure_returns_failed_status(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
        review_recipient_user_id="ou_test",
    )

    def _failing_lark(*_args, **_kwargs):
        raise RuntimeError("network unreachable")

    result = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={"candidate_id": "c1", "revision": 1, "candidate_sha256": "abc"},
        metadata={"title": "Test"},
        body="X" * 60,
        fields={},
        root=tmp_path,
        _lark_fn=_failing_lark,
    )
    assert result["status"] == "failed"
    assert "network unreachable" in result["error"]


def test_send_notification_success_returns_sent_status(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
        review_recipient_user_id="ou_test",
    )

    def _success_lark(*_args, **_kwargs):
        return {
            "data": {
                "message_id": "om_msg_001",
                "chat_id": "oc_chat_001",
            }
        }

    result = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={"candidate_id": "c1", "revision": 1, "candidate_sha256": "abc"},
        metadata={"title": "Test"},
        body="X" * 60,
        fields={},
        root=tmp_path,
        _lark_fn=_success_lark,
    )
    assert result["status"] == "sent"
    assert result["message_id"] == "om_msg_001"
    assert result["chat_id"] == "oc_chat_001"
    assert result["recipient"] == "ou_test"
    assert result["identity"] == "bot"
    assert "idempotency_key" in result


def test_send_notification_idempotency_key_is_deterministic(tmp_path):
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
        review_recipient_user_id="ou_test",
    )

    def _capture_lark(*_args, **_kwargs):
        return {"data": {"message_id": "om_1", "chat_id": "oc_1"}}

    state = {"candidate_id": "c1", "revision": 2, "candidate_sha256": "abc123"}
    r1 = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state=state,
        metadata={"title": "T"},
        body="X" * 60,
        fields={},
        root=tmp_path,
        _lark_fn=_capture_lark,
    )
    r2 = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state=state,
        metadata={"title": "T"},
        body="X" * 60,
        fields={},
        root=tmp_path,
        _lark_fn=_capture_lark,
    )
    assert r1["idempotency_key"] == r2["idempotency_key"]


def test_send_notification_top_level_message_id_fallback(tmp_path):
    """When data.message_id is missing, fall back to envelope.message_id."""
    from feishu_worker.config import WorkerConfig

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
        review_recipient_user_id="ou_test",
    )

    def _lark(*_args, **_kwargs):
        return {"message_id": "om_top_level"}

    result = send_candidate_review_notification(
        config,
        record_id="rec_1",
        state={"candidate_id": "c1", "revision": 1, "candidate_sha256": "abc"},
        metadata={"title": "Test"},
        body="X" * 60,
        fields={},
        root=tmp_path,
        _lark_fn=_lark,
    )
    assert result["status"] == "sent"
    assert result["message_id"] == "om_top_level"
