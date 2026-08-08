"""Structured degradation chain for evidence capture.

When a primary capture returns ``partial`` or ``failed``, the degradation
engine determines the next fallback step from the EvidencePlan and records
the reason.  It never calls a provider — it only computes the next action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from evidence_plan import CaptureCandidate, EvidencePlan, FallbackCandidate

DEGRADATION_VERSION = "oks-degradation/v0.1"

DegradationDecision = Literal[
    "proceed",           # primary succeeded — no fallback needed
    "fallback",          # try the next fallback step
    "human_required",    # stop — a human must act
    "exhausted",         # all fallbacks tried, none succeeded
    "blocked",           # cannot proceed (e.g. missing capability)
]

# A step in the chain can be either the primary or a fallback.
ChainStep = CaptureCandidate | FallbackCandidate


@dataclass(frozen=True)
class DegradationState:
    """Immutable snapshot of where we are in a degradation chain."""

    plan_id: str
    step_index: int          # 0 = primary, 1..N = fallbacks
    step: ChainStep
    decision: DegradationDecision
    reason: str = ""
    total_steps: int = 0
    previous_status: str = ""   # status of the step that triggered this state

    @property
    def is_terminal(self) -> bool:
        return self.decision in {"human_required", "exhausted", "blocked"}

    @property
    def is_primary(self) -> bool:
        return self.step_index == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "step": self.step.to_dict(),
            "decision": self.decision,
            "reason": self.reason,
            "total_steps": self.total_steps,
            "previous_status": self.previous_status,
        }


@dataclass(frozen=True)
class DegradationChain:
    """Tracks progression through an EvidencePlan's capture steps.

    Usage::

        chain = DegradationChain(plan)
        state = chain.evaluate(primary_result)
        while state.decision == "fallback":
            next_result = run_capture(state.step)  # caller's responsibility
            state = chain.evaluate(next_result)
    """

    plan: EvidencePlan
    history: tuple[DegradationState, ...] = ()
    schema_version: str = field(default=DEGRADATION_VERSION, init=False)

    @property
    def steps(self) -> tuple[ChainStep, ...]:
        return (self.plan.primary_capture,) + self.plan.fallback_capture

    @property
    def current_index(self) -> int:
        if not self.history:
            return 0
        return self.history[-1].step_index

    def evaluate(
        self, capture_status: str, *, reason: str = ""
    ) -> DegradationState:
        """Determine the next action after a capture attempt.

        Args:
            capture_status: One of ``"complete"``, ``"partial"``, ``"failed"``.
            reason: Human-readable reason for the status (e.g. error message).

        Returns:
            A DegradationState describing what to do next.
        """
        steps = self.steps

        # Initial state — start with primary
        if not self.history:
            if capture_status == "complete":
                return DegradationState(
                    plan_id=self.plan.plan_id,
                    step_index=0,
                    step=steps[0],
                    decision="proceed",
                    reason="primary capture succeeded",
                    total_steps=len(steps),
                    previous_status=capture_status,
                )
            # Primary did not succeed — evaluate fallback
            return self._evaluate_fallback(
                0, steps, capture_status, reason
            )

        # Continuing from a previous step.
        prev = self.history[-1]
        current_idx = prev.step_index

        if capture_status == "complete":
            step_safe = steps[current_idx] if current_idx < len(steps) else steps[-1]
            return DegradationState(
                plan_id=self.plan.plan_id,
                step_index=current_idx,
                step=step_safe,
                decision="proceed",
                reason=f"step {current_idx} succeeded",
                total_steps=len(steps),
                previous_status=capture_status,
            )
        return self._evaluate_fallback(
            current_idx, steps, capture_status, reason
        )

    def _evaluate_fallback(
        self,
        from_idx: int,
        steps: tuple[ChainStep, ...],
        status: str,
        reason: str,
    ) -> DegradationState:
        """Internal: decide what fallback to try next."""
        next_idx = from_idx + 1

        # Check human gate
        if self.plan.human_gate == "required":
            safe_idx = min(from_idx, len(steps) - 1)
            return DegradationState(
                plan_id=self.plan.plan_id,
                step_index=safe_idx,
                step=steps[safe_idx],
                decision="human_required",
                reason=self.plan.human_gate_reason or "human gate is required",
                total_steps=len(steps),
                previous_status=status,
            )

        # Is there a next fallback?
        safe_idx = min(from_idx, len(steps) - 1)
        if next_idx >= len(steps):
            return DegradationState(
                plan_id=self.plan.plan_id,
                step_index=safe_idx,
                step=steps[safe_idx],
                decision="exhausted",
                reason=(
                    f"all {len(steps)} capture steps exhausted; "
                    f"last status was '{status}'"
                ),
                total_steps=len(steps),
                previous_status=status,
            )

        next_step = steps[next_idx]
        condition = getattr(next_step, "condition", "")

        # Check whether this fallback's condition matches
        if condition:
            if "primary_returned_partial" in condition and status != "partial":
                return self._evaluate_fallback(
                    next_idx, steps, status, reason
                )
            if "primary_returned_failed" in condition and status != "failed":
                return self._evaluate_fallback(
                    next_idx, steps, status, reason
                )

        return DegradationState(
            plan_id=self.plan.plan_id,
            step_index=next_idx,
            step=next_step,
            decision="fallback",
            reason=f"step {from_idx} returned '{status}': {reason}",
            total_steps=len(steps),
            previous_status=status,
        )

    def extend(self, state: DegradationState) -> DegradationChain:
        """Return a new chain with *state* appended to history."""
        return DegradationChain(
            plan=self.plan,
            history=self.history + (state,),
        )


# ── convenience function ───────────────────────────────────────────


def apply_degradation(
    plan: EvidencePlan,
    capture_status: str,
    *,
    chain: DegradationChain | None = None,
    reason: str = "",
) -> tuple[DegradationState, DegradationChain]:
    """One-shot: evaluate capture_status against plan, return next action.

    Args:
        plan: The EvidencePlan being executed.
        capture_status: ``"complete"``, ``"partial"``, or ``"failed"``.
        chain: An existing DegradationChain to continue, or None for a new one.
        reason: Why the capture has this status.

    Returns:
        (next_state, updated_chain) — the caller should inspect
        ``state.decision`` and act accordingly.
    """
    c = chain or DegradationChain(plan)
    state = c.evaluate(capture_status, reason=reason)
    return state, c.extend(state)


# ── degradation path descriptions (for Agent context) ──────────────


def describe_degradation_path(plan: EvidencePlan) -> str:
    """Return a human-readable description of the degradation path.

    This is designed to be injected into Agent context so the Agent
    understands what fallbacks are available and when to use them.
    """
    primary = plan.primary_capture
    parts = [
        f"Evidence plan for {plan.source_modality} source:",
        f"  1. PRIMARY: {primary.strategy} via {primary.provider}"
        f" ({primary.expected_status})",
    ]
    for i, fb in enumerate(plan.fallback_capture, start=2):
        cond = f" when {fb.condition}" if fb.condition else ""
        parts.append(
            f"  {i}. FALLBACK: {fb.strategy} via {fb.provider}{cond}"
        )
    if plan.human_gate == "required":
        parts.append(f"  ⚠ HUMAN GATE: {plan.human_gate_reason}")
    if plan.warnings:
        parts.append("  Warnings:")
        for w in plan.warnings:
            parts.append(f"    - {w}")
    return "\n".join(parts)
