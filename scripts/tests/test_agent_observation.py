from __future__ import annotations

import json
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
    OBSERVATION_VERSION,
    load_observation,
    validate_observation,
    write_observation,
    write_observation_sidecar,
)


FIXTURE = (
    SCRIPTS.parent / "experiments" / "2026-08-promotion-readiness"
    / "10-agent-native-capture" / "p2-agent-observation.json"
)


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
        ),
        warnings=("这是 Agent 派生的解释，不是来源原文",),
        created_at="2026-08-06T00:00:00Z",
    )


# ── dataclass construction ─────────────────────────────────────────

def test_construct_minimal():
    obs = AgentObservation(
        observation_id="obs-1",
        source_capture_id="cap-1",
        status="full",
        agent=AgentIdentity(runtime="test", model=None),
        created_at="2026-08-06T00:00:00Z",
    )
    assert obs.observation_id == "obs-1"
    assert obs.schema_version == OBSERVATION_VERSION
    assert obs.claims == ()
    assert obs.warnings == ()


def test_construct_with_claims():
    obs = AgentObservation(
        observation_id="obs-2",
        source_capture_id="cap-2",
        status="partial",
        agent=AgentIdentity(runtime="claude-code", model="claude-opus-5"),
        claims=(
            Claim(
                claim_id="c1",
                text="test claim",
                status="supported",
                confidence=0.8,
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="page-1",
                        locator={"kind": "page", "page": 1},
                    ),
                ),
            ),
        ),
        warnings=("test warning",),
        created_at="2026-08-06T00:00:00Z",
    )
    assert len(obs.claims) == 1
    assert obs.claims[0].claim_id == "c1"
    assert len(obs.claims[0].evidence_refs) == 1
    assert obs.claims[0].evidence_refs[0].artifact_id == "page-1"


def test_construct_partial_without_warnings_raises():
    with pytest.raises(ValueError, match="must have warnings"):
        AgentObservation(
            observation_id="obs-3",
            source_capture_id="cap-3",
            status="partial",
            agent=AgentIdentity(runtime="test", model=None),
            claims=(),
            warnings=(),
            created_at="",
        )


def test_construct_failed_with_claims_raises():
    with pytest.raises(ValueError, match="zero claims"):
        AgentObservation(
            observation_id="obs-4",
            source_capture_id="cap-4",
            status="failed",
            agent=AgentIdentity(runtime="test", model=None),
            claims=(Claim(
                claim_id="c1", text="test", status="supported",
            ),),
            warnings=("reason",),
            created_at="",
        )


def test_construct_bad_claim_status():
    with pytest.raises(ValueError, match="claim status"):
        Claim(claim_id="c1", text="test", status="bad")


def test_construct_bad_confidence():
    with pytest.raises(ValueError, match="confidence"):
        Claim(claim_id="c1", text="test", status="supported", confidence=1.5)


def test_construct_bad_observation_status():
    with pytest.raises(ValueError, match="observation status"):
        AgentObservation(
            observation_id="obs-5",
            source_capture_id="cap-5",
            status="BAD",
            agent=AgentIdentity(runtime="test", model=None),
            created_at="",
        )


# ── to_dict round-trip ────────────────────────────────────────────

def test_round_trip():
    obs = AgentObservation(
        observation_id="obs-rt",
        source_capture_id="cap-rt",
        status="partial",
        agent=AgentIdentity(runtime="claude-code", model="opus"),
        claims=(
            Claim(
                claim_id="c1",
                text="claim text",
                status="supported",
                confidence=0.5,
                evidence_refs=(
                    EvidenceRef(
                        artifact_id="a1",
                        locator={"kind": "page", "page": 1},
                    ),
                ),
            ),
        ),
        warnings=("w1",),
        created_at="2026-08-06T00:00:00Z",
    )
    d = obs.to_dict()
    assert d["schema_version"] == OBSERVATION_VERSION
    assert d["observation_id"] == "obs-rt"
    assert d["agent"]["runtime"] == "claude-code"
    assert len(d["claims"]) == 1
    assert d["claims"][0]["evidence_refs"][0]["artifact_id"] == "a1"


# ── validate_observation ──────────────────────────────────────────

def test_validate_valid_dict():
    d = {
        "schema_version": OBSERVATION_VERSION,
        "observation_id": "obs-v",
        "source_capture_id": "cap-v",
        "status": "full",
        "agent": {"runtime": "test", "model": None},
        "claims": [{
            "claim_id": "c1",
            "text": "test",
            "status": "supported",
            "evidence_refs": [
                {"artifact_id": "a1", "locator": {"kind": "page", "page": 1}},
            ],
        }],
        "warnings": [],
        "created_at": "2026-08-06T00:00:00Z",
    }
    report = validate_observation(d)
    assert report["valid"] is True
    assert report["errors"] == []


def test_validate_valid_dc(valid_dc_obs):
    """Accept AgentObservation directly."""
    report = validate_observation(valid_dc_obs)
    assert report["valid"] is True


def test_validate_invalid():
    report = validate_observation({"bad": "object"})
    assert report["valid"] is False


# ── write / load ──────────────────────────────────────────────────

def test_write_and_load(tmp_path, valid_dc_obs):
    dest = tmp_path / "obs.json"
    write_observation(valid_dc_obs, dest)
    assert dest.is_file()
    loaded = load_observation(dest)
    assert loaded["observation_id"] == "obs-test-001"
    assert loaded["source_capture_id"] == "cap-test-001"


def test_write_dict_and_load(tmp_path):
    d = {
        "schema_version": OBSERVATION_VERSION,
        "observation_id": "obs-dict",
        "source_capture_id": "cap-dict",
        "status": "full",
        "agent": {"runtime": "test", "model": None},
        "claims": [{
            "claim_id": "c1",
            "text": "test",
            "status": "supported",
            "evidence_refs": [
                {"artifact_id": "a1", "locator": {"kind": "page", "page": 1}},
            ],
        }],
        "warnings": [],
        "created_at": "2026-08-06T00:00:00Z",
    }
    dest = tmp_path / "dict-obs.json"
    write_observation(d, dest)
    loaded = load_observation(dest)
    assert loaded["observation_id"] == "obs-dict"


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_observation(tmp_path / "nonexistent.json")


# ── write_observation_sidecar ──────────────────────────────────────

def test_sidecar_matching_capture_id(tmp_path, valid_dc_obs):
    """Write sidecar into a mock Raw Bundle."""
    bundle = tmp_path / "bundle"
    derived = bundle / "derived"
    derived.mkdir(parents=True)
    (bundle / "metadata.json").write_text(
        json.dumps({"capture_id": "cap-test-001"}), encoding="utf-8",
    )
    dest = write_observation_sidecar(valid_dc_obs, bundle)
    assert dest.parent == derived
    assert dest.name == "agent-observation.json"
    assert dest.is_file()


def test_sidecar_mismatched_capture_id(tmp_path, valid_dc_obs):
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(
        json.dumps({"capture_id": "WRONG-ID"}), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source_capture_id"):
        write_observation_sidecar(valid_dc_obs, bundle)


def test_sidecar_missing_metadata(tmp_path, valid_dc_obs):
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        write_observation_sidecar(valid_dc_obs, bundle)


# ── load existing fixture ─────────────────────────────────────────

@pytest.mark.skipif(not FIXTURE.is_file(), reason="fixture not present")
def test_load_fixture():
    loaded = load_observation(FIXTURE)
    assert loaded["schema_version"] == OBSERVATION_VERSION
    assert len(loaded.get("claims", [])) >= 1
