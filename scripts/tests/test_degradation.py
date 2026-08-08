from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evidence_plan import (  # noqa: E402
    CaptureCandidate,
    EvidencePlan,
    FallbackCandidate,
)
from degradation import (  # noqa: E402
    DegradationChain,
    DegradationState,
    apply_degradation,
    describe_degradation_path,
)


# ── fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def simple_plan():
    return EvidencePlan(
        plan_id="degrad-test-1",
        source_modality="text",
        access_mode="local_file",
        primary_capture=CaptureCandidate(
            strategy="direct",
            provider="oks-connector",
            capability="text.markdown",
        ),
    )


@pytest.fixture
def plan_with_fallbacks():
    return EvidencePlan(
        plan_id="degrad-test-2",
        source_modality="pdf",
        access_mode="local_file",
        primary_capture=CaptureCandidate(
            strategy="text_layer",
            provider="pymupdf4llm",
            capability="pdf.text-layer",
        ),
        fallback_capture=(
            FallbackCandidate(
                strategy="agent_observation",
                provider="agent",
                capability="agent.vision",
                condition="primary_returned_partial",
            ),
            FallbackCandidate(
                strategy="manual",
                provider="human",
                capability="manual.paste",
                condition="primary_returned_failed",
            ),
        ),
    )


@pytest.fixture
def gated_plan():
    return EvidencePlan(
        plan_id="degrad-test-3",
        source_modality="web",
        access_mode="authenticated_remote",
        primary_capture=CaptureCandidate(
            strategy="remote_api",
            provider="agentkey",
            capability="social.article",
        ),
        human_gate="required",
        human_gate_reason="login required",
    )


# ── primary complete ───────────────────────────────────────────────

def test_primary_complete(simple_plan):
    chain = DegradationChain(simple_plan)
    state = chain.evaluate("complete")
    assert state.decision == "proceed"
    assert state.is_terminal is False
    assert state.step_index == 0
    assert state.is_primary is True


# ── primary partial → fallback ─────────────────────────────────────

def test_primary_partial_triggers_fallback(plan_with_fallbacks):
    chain = DegradationChain(plan_with_fallbacks)
    state = chain.evaluate("partial", reason="text layer empty")
    assert state.decision == "fallback"
    assert state.step_index == 1
    assert state.step.provider == "agent"
    assert "partial" in state.reason.lower()


def test_primary_failed_skips_partial_condition(plan_with_fallbacks):
    """Primary failed → fb0 condition is 'primary_returned_partial',
    which doesn't match 'failed', so it skips to fb1 (index 2)."""
    chain = DegradationChain(plan_with_fallbacks)
    state = chain.evaluate("failed", reason="extraction error")
    assert state.decision == "fallback"
    assert state.step_index == 2
    assert state.step.provider == "human"


# ── fallback succeeds ──────────────────────────────────────────────

def test_fallback_succeeds(plan_with_fallbacks):
    chain = DegradationChain(plan_with_fallbacks)
    state1 = chain.evaluate("partial")
    assert state1.decision == "fallback"
    chain2 = chain.extend(state1)

    state2 = chain2.evaluate("complete")
    assert state2.decision == "proceed"
    assert state2.step_index == 1
    assert state2.step.provider == "agent"


# ── exhaustion ─────────────────────────────────────────────────────

def test_all_fallbacks_exhausted(plan_with_fallbacks):
    chain = DegradationChain(plan_with_fallbacks)
    s1 = chain.evaluate("partial")
    c1 = chain.extend(s1)
    s2 = c1.evaluate("partial")
    c2 = c1.extend(s2)
    s3 = c2.evaluate("failed")
    assert s3.decision == "exhausted"
    assert s3.is_terminal is True
    assert s3.step_index == 2


def test_single_step_exhausted(simple_plan):
    chain = DegradationChain(simple_plan)
    state = chain.evaluate("failed")
    assert state.decision == "exhausted"
    assert state.is_terminal is True


# ── human gate ─────────────────────────────────────────────────────

def test_gated_plan_blocks(gated_plan):
    chain = DegradationChain(gated_plan)
    state = chain.evaluate("partial", reason="challenge detected")
    assert state.decision == "human_required"
    assert state.is_terminal is True


# ── history ────────────────────────────────────────────────────────

def test_chain_history(simple_plan):
    chain = DegradationChain(simple_plan)
    state = chain.evaluate("complete")
    extended = chain.extend(state)
    assert len(extended.history) == 1
    assert extended.history[0].decision == "proceed"


# ── apply_degradation ──────────────────────────────────────────────

def test_apply_degradation_success():
    plan = EvidencePlan(
        plan_id="apply-test",
        source_modality="text",
        access_mode="local_file",
        primary_capture=CaptureCandidate(
            strategy="direct",
            provider="markitdown",
            capability="office.markitdown",
        ),
    )
    state, chain = apply_degradation(plan, "complete")
    assert state.decision == "proceed"
    assert len(chain.history) == 1


def test_apply_degradation_with_existing_chain(plan_with_fallbacks):
    chain = DegradationChain(plan_with_fallbacks)
    s1 = chain.evaluate("partial")
    c1 = chain.extend(s1)

    state, c2 = apply_degradation(
        plan_with_fallbacks, "complete", chain=c1, reason="agent recovered text",
    )
    assert state.decision == "proceed"
    assert len(c2.history) == 2


# ── describe_degradation_path ──────────────────────────────────────

def test_describe_path_simple(simple_plan):
    desc = describe_degradation_path(simple_plan)
    assert "text_layer" in desc or "direct" in desc
    assert "oks-connector" in desc


def test_describe_path_with_fallbacks(plan_with_fallbacks):
    desc = describe_degradation_path(plan_with_fallbacks)
    assert "PRIMARY" in desc
    assert "FALLBACK" in desc
    assert "agent" in desc


def test_describe_path_with_gate(gated_plan):
    desc = describe_degradation_path(gated_plan)
    assert "HUMAN GATE" in desc


# ── DegradationState serialization ─────────────────────────────────

def test_state_to_dict(simple_plan):
    chain = DegradationChain(simple_plan)
    state = chain.evaluate("complete")
    d = state.to_dict()
    assert d["decision"] == "proceed"
    assert d["step_index"] == 0
    assert "step" in d
    assert "reason" in d
