"""Agent Observation — structurable claims anchored to CaptureResult evidence.

Schema: schemas/agent-observation-v0.1.schema.json

An AgentObservation records what the Agent learned from a CaptureResult.
Each claim carries evidence_refs that trace back to specific locators
inside the Raw Bundle's artifacts, making the chain from source →
evidence → claim → candidate fully auditable.

The frozen dataclasses (AgentObservation, Claim, EvidenceRef, AgentIdentity)
are the canonical model.  Compatibility functions (validate_observation,
write_observation, load_observation, write_observation_sidecar) are thin
wrappers that bridge dict representations to the dataclass model for use
by downstream consumers like ``observation_adapter``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OBSERVATION_VERSION = "oks-agent-observation/v0.1"


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer into a specific artifact locator within the Raw Bundle."""
    artifact_id: str
    locator: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "locator": dict(self.locator)}


@dataclass(frozen=True)
class Claim:
    """One claim made by the Agent, backed by one or more evidence refs."""
    claim_id: str
    text: str
    status: str  # supported, uncertain, not_observed
    confidence: float | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"supported", "uncertain", "not_observed"}:
            raise ValueError(f"invalid claim status: {self.status}")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "claim_id": self.claim_id,
            "text": self.text,
            "status": self.status,
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
        }
        if self.confidence is not None:
            value["confidence"] = self.confidence
        return value


@dataclass(frozen=True)
class AgentIdentity:
    runtime: str      # claude-code, codex, luna, deepseek, ...
    model: str | None = None
    skill: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"runtime": self.runtime}
        if self.model is not None:
            value["model"] = self.model
        if self.skill is not None:
            value["skill"] = self.skill
        return value


@dataclass(frozen=True)
class AgentObservation:
    observation_id: str
    source_capture_id: str
    status: str  # full, partial, failed
    agent: AgentIdentity
    claims: tuple[Claim, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: str = ""
    schema_version: str = field(default=OBSERVATION_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.status not in {"full", "partial", "failed"}:
            raise ValueError(f"invalid observation status: {self.status}")
        if self.status == "partial" and not self.warnings:
            raise ValueError("partial observation must have warnings")
        if self.status == "failed" and self.claims:
            raise ValueError("failed observation must have zero claims")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "source_capture_id": self.source_capture_id,
            "status": self.status,
            "agent": self.agent.to_dict(),
            "claims": [c.to_dict() for c in self.claims],
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }


# ── Compatibility bridge functions ───────────────────────────────────
#
# These functions accept dict representations (as written by prior
# versions) and bridge them through the frozen dataclass model.
# Downstream consumers that work with dicts can call them without
# knowing about the dataclass internals.


def _obs_from_dict(value: dict[str, Any]) -> AgentObservation:
    """Convert a validated dict into an AgentObservation dataclass.

    Raises ValueError (via __post_init__) if the dict is invalid.
    """
    from pathlib import Path  # noqa: used by bridge fns
    claims: list[Claim] = []
    for c in value.get("claims", []):
        refs: list[EvidenceRef] = []
        for r in c.get("evidence_refs", []):
            refs.append(EvidenceRef(
                artifact_id=r["artifact_id"],
                locator=dict(r.get("locator", {})),
            ))
        claims.append(Claim(
            claim_id=c["claim_id"],
            text=c["text"],
            status=c.get("status", "supported"),
            confidence=c.get("confidence"),
            evidence_refs=tuple(refs),
        ))

    agent_raw = value.get("agent", {})
    agent = AgentIdentity(
        runtime=agent_raw.get("runtime", ""),
        model=agent_raw.get("model"),
        skill=agent_raw.get("skill"),
    )

    return AgentObservation(
        observation_id=value.get("observation_id", ""),
        source_capture_id=value.get("source_capture_id", ""),
        status=value.get("status", "partial"),
        agent=agent,
        claims=tuple(claims),
        warnings=tuple(value.get("warnings", [])),
        created_at=value.get("created_at", ""),
    )


def validate_observation(
    value: dict[str, Any] | AgentObservation | Any,
) -> dict[str, Any]:
    """Validate an observation and return ``{valid, errors}``.

    Accepts an ``AgentObservation`` dataclass (already validated by
    __post_init__) or a dict representation.  Returns a report dict
    compatible with the pre-dataclass API.
    """
    if isinstance(value, AgentObservation):
        return {"valid": True, "errors": []}

    if not isinstance(value, dict):
        return {"valid": False, "errors": ["observation must be a dict or AgentObservation"]}

    try:
        _obs_from_dict(value)
        return {"valid": True, "errors": []}
    except (ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "errors": [str(exc)]}


def write_observation(
    observation: dict[str, Any] | AgentObservation,
    destination: Path,
) -> dict[str, Any]:
    """Validate and atomically write an observation as UTF-8 JSON.

    Accepts a dict or an AgentObservation dataclass.  The written file
    is a stable JSON dict that ``load_observation`` can round-trip.
    """
    import json as _json
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path

    report = validate_observation(observation)
    if not report["valid"]:
        raise ValueError(
            "invalid AgentObservation: " + "; ".join(report["errors"])
        )

    # Normalise to dict for stable serialisation
    if isinstance(observation, AgentObservation):
        payload = _json.dumps(
            observation.to_dict(), ensure_ascii=False, indent=2
        ) + "\n"
    else:
        payload = _json.dumps(observation, ensure_ascii=False, indent=2) + "\n"

    dest = Path(destination).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = _tempfile.mkstemp(
        prefix=f".{dest.name}.", dir=dest.parent,
    )
    try:
        with _os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            _os.fsync(stream.fileno())
        _os.replace(tmp, str(dest))
        # Directory fsync per CONSTITUTION A5
        try:
            fd = _os.open(str(dest.parent), _os.O_RDONLY)
            _os.fsync(fd)
            _os.close(fd)
        except OSError:
            pass
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    return report


def load_observation(path: Path | str) -> dict[str, Any]:
    """Load, validate, and return an observation dict from a UTF-8 JSON file."""
    import json as _json
    from pathlib import Path

    raw = Path(path).expanduser().resolve().read_text(encoding="utf-8")
    value = _json.loads(raw)
    report = validate_observation(value)
    if not report["valid"]:
        raise ValueError(
            "invalid AgentObservation: " + "; ".join(report["errors"])
        )
    return dict(value)


def write_observation_sidecar(
    observation: dict[str, Any] | AgentObservation,
    raw_bundle: Path | str,
) -> Path:
    """Write an observation under an existing Raw Bundle's ``derived/`` folder.

    The Raw Bundle remains the source of evidence.  The sidecar is only a
    derived interpretation and must refer to the bundle's capture id.
    """
    import json as _json
    import sys
    from pathlib import Path

    bundle = Path(raw_bundle).expanduser().resolve()
    metadata_path = bundle / "metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"Raw Bundle metadata.json not found: {metadata_path}"
        )
    metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
    capture_id = metadata.get("capture_id")

    # Get source_capture_id from whichever representation
    if isinstance(observation, AgentObservation):
        obs_capture_id = observation.source_capture_id
    else:
        obs_capture_id = observation.get("source_capture_id", "")

    if obs_capture_id != capture_id:
        raise ValueError(
            "observation.source_capture_id does not match "
            "Raw Bundle metadata.capture_id"
        )

    # ── locator validation ─────────────────────────────────
    _validate_sidecar_locators(observation)

    destination = bundle / "derived" / "agent-observation.json"
    write_observation(observation, destination)
    return destination


def _validate_sidecar_locators(
    observation: dict[str, Any] | AgentObservation,
) -> None:
    """Check that every evidence_ref.locator has a recognized ``kind`` field."""
    import sys

    VALID_LOCATOR_KINDS = {
        "page", "bbox", "timestamp", "dom", "document", "custom",
    }

    if isinstance(observation, AgentObservation):
        obs_claims = observation.claims
    else:
        obs_claims = []
        for c in observation.get("claims", []):
            obs_claims.append(c)

    for claim in obs_claims:
        if isinstance(claim, Claim):
            claim_id = claim.claim_id
            refs = claim.evidence_refs
        else:
            claim_id = claim.get("claim_id", "?")
            refs = claim.get("evidence_refs", [])

        for ref in refs:
            if isinstance(ref, EvidenceRef):
                locator = ref.locator
            else:
                locator = ref.get("locator", {})

            if not isinstance(locator, dict) or not locator:
                raise ValueError(
                    f"claim {claim_id!r}: evidence_ref.locator "
                    f"must be a non-empty object"
                )

            kind = locator.get("kind")
            if kind is None:
                print(
                    f"WARNING [agent_observation]: claim {claim_id!r} "
                    f"uses a legacy locator without 'kind'. "
                    f"Consider upgrading to locator-v0.1 schema.",
                    file=sys.stderr,
                )
            elif kind not in VALID_LOCATOR_KINDS:
                raise ValueError(
                    f"claim {claim_id!r}: locator kind {kind!r} is not "
                    f"one of {sorted(VALID_LOCATOR_KINDS)}"
                )
