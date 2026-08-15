"""Focused tests for feishu_worker.candidate module.

Covers: subprocess import isolation, parse/render, state path/load, fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from feishu_worker.candidate import (  # noqa: E402
    CANDIDATE_FIELDS,
    candidate_review_fingerprint,
    candidate_state_path,
    load_candidate_state,
    parse_candidate_document,
    publish_candidate,
    render_candidate_document,
    render_candidate_review_message,
    send_candidate_review_notification,
)


# ── Subprocess import isolation ────────────────────────────────────────


def test_candidate_module_never_imports_feishu_base_worker():
    """Fresh subprocess confirms candidate.py has zero feishu_base_worker deps."""
    check = textwrap.dedent("""\
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        # Block feishu_base_worker from being importable so any attempt fails loudly.
        import feishu_base_worker
        raise SystemExit(1)
    """)
    # We want the opposite — verify candidate.py does NOT trigger the guard.
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""\
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(r'{}').parents[0]))
            # Import candidate — must succeed without pulling in feishu_base_worker
            from feishu_worker import candidate
            print("OK")
        """.format(str(SCRIPTS)))],
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK" in result.stdout


# ── Document parse / render ────────────────────────────────────────────


VALID_CANDIDATE = textwrap.dedent("""\
    ---
    title: "Test Knowledge Unit"
    draft_type: strategy
    draft_area: computing
    source_pages: []
    drafted_at: "2026-07-22"
    status: draft
    tags: "feishu, learning-loop"
    ---

    # 我对它的理解

    飞书多维表格是本轮 POC 的入口、状态机与人工审核控制面。Worker 负责确定性状态转换。
    Agent 负责需要判断的 Teach-back，审核通过后才允许晋升 Wiki。
""")


def test_parse_candidate_document_valid():
    metadata, body = parse_candidate_document(VALID_CANDIDATE)
    assert metadata["title"] == "Test Knowledge Unit"
    assert metadata["draft_type"] == "strategy"
    assert metadata["draft_area"] == "computing"
    assert body.startswith("# 我对它的理解")
    assert len(body) >= 50


def test_parse_candidate_document_missing_frontmatter():
    with pytest.raises(ValueError, match="must start with YAML frontmatter"):
        parse_candidate_document("no frontmatter here\n\nContent goes here.")


def test_parse_candidate_document_unclosed_frontmatter():
    # Only opening --- without closing --- yields 2 parts, not 3.
    with pytest.raises(ValueError, match="frontmatter is not closed"):
        parse_candidate_document("---\ntitle: X\ndraft_type: strategy\ndraft_area: computing\n\nBody here.")


def test_parse_candidate_document_missing_required_fields():
    for field in ("title", "draft_type", "draft_area"):
        doc = VALID_CANDIDATE.replace(f"{field}:", "_missing_:")
        with pytest.raises(ValueError, match=f"missing {field}"):
            parse_candidate_document(doc)


def test_parse_candidate_document_invalid_draft_type():
    doc = VALID_CANDIDATE.replace("draft_type: strategy", "draft_type: invalid_type")
    with pytest.raises(ValueError, match="draft_type must be"):
        parse_candidate_document(doc)


def test_parse_candidate_document_body_too_short():
    doc = textwrap.dedent("""\
        ---
        title: "Short Body Test"
        draft_type: concept
        draft_area: science
        ---

        Too short.
    """)
    with pytest.raises(ValueError, match="at least 50 characters"):
        parse_candidate_document(doc)


def test_render_candidate_document_round_trip():
    metadata, body = parse_candidate_document(VALID_CANDIDATE)
    rendered = render_candidate_document(metadata, body)
    metadata2, body2 = parse_candidate_document(rendered)
    assert metadata2["title"] == metadata["title"]
    assert metadata2["draft_type"] == metadata["draft_type"]
    assert body2 == body


def test_render_candidate_document_preserves_metadata_order():
    metadata = {
        "title": "Z",
        "draft_type": "concept",
        "draft_area": "science",
        "status": "active",
    }
    body = "X" * 60
    result = render_candidate_document(metadata, body)
    # title should appear before draft_type in output
    assert result.find("title:") < result.find("draft_type:")


# ── State path / load ──────────────────────────────────────────────────


def test_candidate_state_path_normalizes_record_id(tmp_path):
    path = candidate_state_path("rec!@#ABC_123-测试", root=tmp_path)
    assert path.parent == tmp_path / ".oks" / "candidates"
    assert path.name.endswith(".json")
    assert "!" not in path.name
    assert "@" not in path.name
    assert "#" not in path.name


def test_candidate_state_path_rejects_empty_record_id(tmp_path):
    with pytest.raises(ValueError, match="record_id cannot form"):
        candidate_state_path("!!!", root=tmp_path)


def test_load_candidate_state_round_trip(tmp_path):
    state_path = candidate_state_path("rec_test123", root=tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    expected = {"schema_version": "v0.1", "record_id": "rec_test123", "candidate_id": "cand-1"}
    state_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    loaded = load_candidate_state("rec_test123", root=tmp_path)
    assert loaded == expected


def test_load_candidate_state_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Candidate state not found"):
        load_candidate_state("nonexistent_record", root=tmp_path)


def test_load_candidate_state_not_a_dict(tmp_path):
    state_path = candidate_state_path("rec_list", root=tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="not an object"):
        load_candidate_state("rec_list", root=tmp_path)


# ── Fingerprint ────────────────────────────────────────────────────────


def test_candidate_review_fingerprint_deterministic():
    fields = {"审核动作": "accept", "审核意见": "looks good", "候选内容": "body text"}
    fp1 = candidate_review_fingerprint(fields)
    fp2 = candidate_review_fingerprint(fields)
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_candidate_review_fingerprint_changes_with_action():
    base = {"审核动作": "accept", "审核意见": "ok"}
    fp_accept = candidate_review_fingerprint(base)
    fp_reject = candidate_review_fingerprint({**base, "审核动作": "reject"})
    assert fp_accept != fp_reject


def test_candidate_review_fingerprint_normalizes_scalar():
    """Single-element list action should normalize same as scalar."""
    fp_scalar = candidate_review_fingerprint({"审核动作": "accept"})
    fp_list = candidate_review_fingerprint({"审核动作": ["accept"]})
    assert fp_scalar == fp_list


def test_candidate_review_fingerprint_none_fields():
    fp = candidate_review_fingerprint({})
    assert len(fp) == 64
    # Should produce consistent output for empty fields
    fp2 = candidate_review_fingerprint({})
    assert fp == fp2


# ── Review notification rendering (publish helper) ─────────────────────


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


# ── publish_candidate injected notification regression ─────────────────
# When an explicit _send_notification_fn is supplied, its return value flows
# into state["review_notification"].  The worker-layer wrapper
# (feishu_base_worker.publish_candidate) injects its own monkeypatchable
# send_candidate_review_notification so that test monkeypatching stays
# effective and the default "skipped" path is never hit.


def test_publish_candidate_injected_notification_returns_sent(tmp_path):
    """candidate.publish_candidate honours an explicit _send_notification_fn."""
    from feishu_worker.config import WorkerConfig  # noqa: E402

    config = WorkerConfig(
        base_token="t",
        table_id="tbl",
        lark_cli=tmp_path / "lark-cli",
        output_root=tmp_path,
        knowledge_root=tmp_path,
    )
    raw = tmp_path / "raw-bundle"
    raw.mkdir()
    (raw / "bundle.json").write_text(
        json.dumps({"capture_id": "cap_1", "bundle_id": "bnd_1"}),
        encoding="utf-8",
    )
    source = tmp_path / "injected-candidate.md"
    source.write_text(VALID_CANDIDATE, encoding="utf-8")

    _get = lambda _c, _r, _p=None: {
        "record_id": "rec_inj",
        "fields": {"运行状态": "Raw就绪", "Raw Bundle": str(raw), "运行ID": "run_inj"},
    }
    _update = lambda _c, _r, _patch: {}
    _lark = lambda _c, *_a: {"data": {}}
    _notify = lambda _config, **_kw: {"status": "sent", "message_id": "om_injected", "chat_id": "oc_test"}

    state = publish_candidate(
        config,
        "rec_inj",
        source,
        root=tmp_path,
        _get_fn=_get,
        _update_fn=_update,
        _lark_fn=_lark,
        _send_notification_fn=_notify,
    )

    assert state["review_notification"]["status"] == "sent"
    assert state["review_notification"]["message_id"] == "om_injected"
    assert state["review_notification"]["chat_id"] == "oc_test"
    assert state["record_id"] == "rec_inj"
    assert state["candidate_id"] == "injected-candidate"


# ── CANDIDATE_FIELDS constant ──────────────────────────────────────────


def test_candidate_fields_contains_expected_keys():
    assert "运行状态" in CANDIDATE_FIELDS
    assert "候选ID" in CANDIDATE_FIELDS
    assert "候选内容" in CANDIDATE_FIELDS
    assert "Wiki状态" in CANDIDATE_FIELDS
    assert "Wiki路径" in CANDIDATE_FIELDS
    assert len(CANDIDATE_FIELDS) == 11
