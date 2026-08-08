from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_observation import (  # noqa: E402
    AgentIdentity,
    AgentObservation,
    Claim,
    EvidenceRef,
)
from observation_adapter import (  # noqa: E402
    CandidateDraft,
    _describe_locator,
    _format_claim,
    _format_dc_claim,
    _truncate_title,
    observation_to_candidate,
)


# ── fixture: minimal valid observation dataclass ───────────────────

@pytest.fixture
def valid_dc_obs():
    return AgentObservation(
        observation_id="obs-test-001",
        source_capture_id="cap-test-001",
        status="partial",
        agent=AgentIdentity(runtime="claude-code", model="claude-opus-5"),
        claims=(
            Claim(
                claim_id="c1-title",
                text="文档标题为'开放知识工作室轻量部署验收'",
                status="supported",
                confidence=0.95,
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="page-1",
                        locator={"kind": "page", "page": 1},
                    ),
                ),
            ),
            Claim(
                claim_id="c2-table",
                text="第 2 页包含来源能力与降级矩阵",
                status="supported",
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="page-2",
                        locator={"kind": "page", "page": 2, "region": "table"},
                    ),
                ),
            ),
            Claim(
                claim_id="c3-uncertain",
                text="嵌入示意图的完整语义未验证",
                status="uncertain",
                confidence=0.3,
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="page-3",
                        locator={"kind": "page", "page": 3, "region": "embedded-image"},
                    ),
                ),
            ),
            Claim(
                claim_id="c4-not-observed",
                text="OCR 字符级准确率未测量",
                status="not_observed",
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="page-3",
                        locator={"kind": "page", "page": 3},
                    ),
                ),
            ),
        ),
        warnings=(
            "这是 Agent 派生的解释，不是来源原文",
            "真实模型延迟和成本未测量",
        ),
        created_at="2026-08-06T00:00:00Z",
    )


@pytest.fixture
def valid_dict_obs(valid_dc_obs):
    return valid_dc_obs.to_dict()


# ── observation_to_candidate (dataclass input) ─────────────────────

def test_dc_observation_converts(valid_dc_obs):
    draft = observation_to_candidate(valid_dc_obs)
    assert isinstance(draft, CandidateDraft)
    assert draft.draft_type == "strategy"
    assert draft.source_capture_id == "cap-test-001"
    assert draft.source_observation_id == "obs-test-001"
    assert "已验证的观察" in draft.body
    assert "不确定的观察" in draft.body
    assert "未观察到的方面" in draft.body


# ── observation_to_candidate (dict input) ──────────────────────────

def test_dict_observation_converts(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    assert isinstance(draft, CandidateDraft)
    assert draft.source_capture_id == "cap-test-001"


def test_supported_claims_become_verified(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    assert "[verified]" in draft.body
    assert "c1-title" in draft.body
    assert "c2-table" in draft.body


def test_uncertain_claims_become_inferred(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    assert "[inferred]" in draft.body
    assert "c3-uncertain" in draft.body


def test_not_observed_claims_in_appendix(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    assert "未观察到的方面" in draft.body
    assert "c4-not-observed" in draft.body


def test_evidence_traceability_section(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    assert "证据可追溯性" in draft.body
    assert "page-1" in draft.body
    assert "page-2" in draft.body


def test_custom_title_and_slug(valid_dict_obs):
    draft = observation_to_candidate(
        valid_dict_obs, title="自定义标题", slug="custom-slug",
    )
    assert draft.title == "自定义标题"
    assert draft.slug == "custom-slug"


# ── artifact_id + locator guard ────────────────────────────────────

def test_missing_artifact_id_raises():
    bad = {
        "schema_version": "oks-agent-observation/v0.1",
        "observation_id": "obs-bad",
        "source_capture_id": "cap-x",
        "status": "partial",
        "agent": {"runtime": "test", "model": None},
        "claims": [{
            "claim_id": "c1",
            "text": "test",
            "status": "supported",
            "evidence_refs": [
                {"artifact_id": "", "locator": {"kind": "page", "page": 1}},
            ],
        }],
        "warnings": ["test"],
        "created_at": "2026-08-06T00:00:00Z",
    }
    with pytest.raises(ValueError, match="artifact_id"):
        observation_to_candidate(bad)


def test_missing_locator_raises():
    bad = {
        "schema_version": "oks-agent-observation/v0.1",
        "observation_id": "obs-bad",
        "source_capture_id": "cap-x",
        "status": "partial",
        "agent": {"runtime": "test", "model": None},
        "claims": [{
            "claim_id": "c1",
            "text": "test",
            "status": "supported",
            "evidence_refs": [
                {"artifact_id": "page-1", "locator": {}},
            ],
        }],
        "warnings": ["test"],
        "created_at": "2026-08-06T00:00:00Z",
    }
    with pytest.raises(ValueError, match="locator"):
        observation_to_candidate(bad)


def test_no_claims_raises():
    bad = {
        "schema_version": "oks-agent-observation/v0.1",
        "observation_id": "obs-empty",
        "source_capture_id": "cap-x",
        "status": "failed",
        "agent": {"runtime": "test", "model": None},
        "claims": [],
        "warnings": ["no data"],
        "created_at": "2026-08-06T00:00:00Z",
    }
    with pytest.raises(ValueError, match="at least one claim"):
        observation_to_candidate(bad)


def test_no_evidence_refs_raises():
    bad = {
        "schema_version": "oks-agent-observation/v0.1",
        "observation_id": "obs-bad",
        "source_capture_id": "cap-x",
        "status": "partial",
        "agent": {"runtime": "test", "model": None},
        "claims": [{
            "claim_id": "c1",
            "text": "test",
            "status": "supported",
            "evidence_refs": [],
        }],
        "warnings": ["test"],
        "created_at": "2026-08-06T00:00:00Z",
    }
    with pytest.raises(ValueError, match="at least one evidence_ref"):
        observation_to_candidate(bad)


# ── CandidateDraft ─────────────────────────────────────────────────

def test_draft_to_markdown(valid_dict_obs):
    draft = observation_to_candidate(valid_dict_obs)
    md = draft.to_markdown()
    assert md.startswith("---")
    assert "draft_type: strategy" in md
    assert "source_capture_id: cap-test-001" in md
    assert "review_status: pending" in md


def test_draft_empty_body_raises():
    with pytest.raises(ValueError, match="body must not be empty"):
        CandidateDraft(slug="test", title="Test", body="")


def test_draft_empty_slug_raises():
    with pytest.raises(ValueError, match="slug must not be empty"):
        CandidateDraft(slug="", title="Test", body="content")


# ── helpers ────────────────────────────────────────────────────────

def test_truncate_title():
    assert _truncate_title("short") == "short"
    long_text = "A" * 100
    assert len(_truncate_title(long_text)) <= 83


def test_format_dc_claim_supported():
    claim = Claim(
        claim_id="c1",
        text="test claim",
        status="supported",
        confidence=0.9,
        evidence_refs=(EvidenceRef(artifact_id="p1", locator={"kind": "page", "page": 1}),),
    )
    result = _format_dc_claim(claim, 1)
    assert "[verified]" in result
    assert "test claim" in result
    assert "90%" in result


def test_format_dc_claim_uncertain():
    claim = Claim(
        claim_id="c2",
        text="uncertain claim",
        status="uncertain",
    )
    result = _format_dc_claim(claim, 2)
    assert "[inferred]" in result


def test_describe_locator_page():
    assert "第 1 页" in _describe_locator({"kind": "page", "page": 1})


def test_describe_locator_page_with_region():
    desc = _describe_locator({"kind": "page", "page": 2, "region": "table"})
    assert "第 2 页" in desc
    assert "table" in desc


def test_describe_locator_bbox():
    assert "bbox" in _describe_locator({"kind": "bbox", "bbox": [10, 20, 100, 50]})


def test_describe_locator_timestamp():
    desc = _describe_locator({"kind": "timestamp", "start_ms": 1000, "end_ms": 5000})
    assert "1000" in desc and "5000" in desc


def test_describe_locator_document():
    desc = _describe_locator({"kind": "document", "document_section": "header"})
    assert "header" in desc


def test_describe_locator_custom():
    desc = _describe_locator({"kind": "custom", "custom_label": "s1"})
    assert "s1" in desc


def test_describe_locator_legacy():
    desc = _describe_locator({"page": 5, "paragraph": 3})
    assert "5" in desc
