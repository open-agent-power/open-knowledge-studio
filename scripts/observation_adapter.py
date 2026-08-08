"""Bridge AgentObservation sidecars into the Candidate / Draft pipeline.

An AgentObservation is a derived interpretation of a Raw Bundle — it carries
Claim-level assertions with artifact_id + locator references back to evidence.
This module converts a validated observation into a CandidateDraft that can
be written to ``drafts/`` and reviewed by a human before promotion to Wiki.

Key rules (per CONSTITUTION P3 and STATUS-AND-ARCHITECTURE):
- ``supported`` claims → Candidate sections labeled ``[verified]``
- ``uncertain`` claims → Candidate sections labeled ``[inferred]``
- ``not_observed`` claims → ``## 未观察到的方面`` appendix
- The Candidate always carries ``source_capture_id`` for provenance
- This module NEVER writes to Wiki or bypasses human review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OBSERVATION_ADAPTER_VERSION = "oks-observation-adapter/v0.1"

CLAIM_STATUS_LABEL: dict[str, str] = {
    "supported": "[verified]",
    "uncertain": "[inferred]",
    "not_observed": "[not-observed]",
}


@dataclass(frozen=True)
class CandidateDraft:
    """Minimal in-memory representation of a Candidate draft file.

    This is NOT a wiki page.  It carries the draft content and enough
    metadata to write a ``drafts/{slug}.md`` file.  Human review is
    mandatory before promotion.
    """

    slug: str
    title: str
    draft_type: str = "strategy"
    draft_area: str = "computing"
    source_capture_id: str = ""
    source_observation_id: str = ""
    body: str = ""
    source_pages: tuple[str, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if not self.slug.strip():
            raise ValueError("slug must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.body.strip():
            raise ValueError("body must not be empty")

    def to_markdown(self) -> str:
        """Render the draft as a Markdown file suitable for ``drafts/``."""
        sources = "\n".join(
            f"- {page}" for page in self.source_pages
        ) if self.source_pages else "- (derived from AgentObservation)"

        return (
            f"---\n"
            f"draft_type: {self.draft_type}\n"
            f"draft_area: {self.draft_area}\n"
            f"source_capture_id: {self.source_capture_id}\n"
            f"source_observation_id: {self.source_observation_id}\n"
            f"source_pages:\n{sources}\n"
            f"created_at: {self.created_at}\n"
            f"adapter_version: {OBSERVATION_ADAPTER_VERSION}\n"
            f"review_status: pending\n"
            f"---\n\n"
            f"# {self.title}\n\n"
            f"> 本文由 AgentObservation 自动生成，必须经过人工审核后才能晋升 Wiki。\n\n"
            f"{self.body}\n"
        )


# ── conversion ─────────────────────────────────────────────────────


def observation_to_candidate(
    observation: Mapping[str, Any],
    *,
    target_domain: str = "computing",
    draft_type: str = "strategy",
    title: str | None = None,
    slug: str | None = None,
    source_pages: tuple[str, ...] | None = None,
) -> CandidateDraft:
    """Convert a validated AgentObservation into a Candidate draft.

    Accepts an ``AgentObservation`` dataclass or a dict representation.
    Validation is performed by constructing the dataclass (__post_init__).

    Mapping rules:
        - ``supported`` claims → ``[verified]`` sections in the body
        - ``uncertain`` claims → ``[inferred]`` sections in the body
        - ``not_observed`` claims → appendix section
        - Every claim MUST have at least one evidence_ref with
          non-empty artifact_id + locator — raises ValueError otherwise.
        - The Candidate carries the observation's ``source_capture_id``
          and ``observation_id`` for full provenance.

    Args:
        observation: A validated dict or AgentObservation dataclass.
        target_domain: Wiki domain for the draft (default: computing).
        draft_type: Draft type (default: strategy).
        title: Override title.  Defaults to the observation's first
            supported claim text (truncated).
        slug: Override slug.  Defaults to a date-based slug.
        source_pages: Additional source page references.

    Returns:
        A CandidateDraft ready to write to ``drafts/``.

    Raises:
        ValueError: If the observation is invalid, has no claims, or
            any claim lacks artifact_id + locator evidence refs.
    """
    from agent_observation import (
        AgentObservation as ObsDC,
        Claim as ClaimDC,
        EvidenceRef,
    )

    # Accept both dataclass and dict — validate via dataclass construction
    if isinstance(observation, ObsDC):
        obs_dc = observation
    else:
        # Bridge dict → dataclass for validation
        claims_raw: list[ClaimDC] = []
        for c in observation.get("claims", []):
            refs: list[EvidenceRef] = []
            for r in c.get("evidence_refs", []):
                loc = r.get("locator", {})
                if not isinstance(loc, dict) or not loc:
                    raise ValueError(
                        f"claim {c.get('claim_id', '?')!r}: "
                        f"evidence_ref.locator must be a non-empty object"
                    )
                aid = r.get("artifact_id", "")
                if not aid or not str(aid).strip():
                    raise ValueError(
                        f"claim {c.get('claim_id', '?')!r}: "
                        f"evidence_ref.artifact_id must be a non-empty string"
                    )
                refs.append(EvidenceRef(
                    artifact_id=str(aid),
                    locator=dict(loc),
                ))
            if not refs:
                raise ValueError(
                    f"claim {c.get('claim_id', '?')!r}: "
                    f"must have at least one evidence_ref"
                )
            claims_raw.append(ClaimDC(
                claim_id=c.get("claim_id", "claim-?"),
                text=c.get("text", ""),
                status=c.get("status", "uncertain"),
                confidence=c.get("confidence"),
                evidence_refs=tuple(refs),
            ))
        if not claims_raw:
            raise ValueError("AgentObservation must contain at least one claim")
        from agent_observation import AgentIdentity

        agent_raw = observation.get("agent", {})
        obs_dc = ObsDC(
            observation_id=observation.get("observation_id", ""),
            source_capture_id=observation.get("source_capture_id", ""),
            status=observation.get("status", "partial"),
            agent=AgentIdentity(
                runtime=agent_raw.get("runtime", ""),
                model=agent_raw.get("model"),
                skill=agent_raw.get("skill"),
            ),
            claims=tuple(claims_raw),
            warnings=tuple(observation.get("warnings", [])),
            created_at=observation.get("created_at", ""),
        )

    # From here down, work with the validated dataclass
    claims = obs_dc.claims
    if not claims:
        raise ValueError("AgentObservation must contain at least one claim")

    source_capture_id = obs_dc.source_capture_id
    observation_id = obs_dc.observation_id
    obs_status = obs_dc.status

    # Build title
    if title is None:
        first_supported = next(
            (c for c in claims if c.status == "supported"), None
        )
        if first_supported:
            title = _truncate_title(first_supported.text)
        else:
            title = f"Agent 观察结果 ({observation_id[:12]})"

    # Build slug
    if slug is None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = f"{today}-agent-candidate"

    # Build body
    body_parts: list[str] = []

    # Observation status header
    status_note = (
        "完整" if obs_status == "full" else
        "部分" if obs_status == "partial" else
        "失败"
    )
    body_parts.append(
        f"## 观察状态\n\n"
        f"- 来源采集 ID：`{source_capture_id}`\n"
        f"- 观察 ID：`{observation_id}`\n"
        f"- 状态：{status_note}\n"
    )

    # Warnings section
    warnings_list = obs_dc.warnings
    if warnings_list:
        body_parts.append("## 已知限制\n")
        for w in warnings_list:
            body_parts.append(f"- {w}")
        body_parts.append("")

    # Supported claims
    supported = [c for c in claims if c.status == "supported"]
    if supported:
        body_parts.append("## 已验证的观察\n")
        for i, claim in enumerate(supported, 1):
            body_parts.append(_format_dc_claim(claim, i))
        body_parts.append("")

    # Uncertain claims
    uncertain = [c for c in claims if c.status == "uncertain"]
    if uncertain:
        body_parts.append("## 不确定的观察\n")
        body_parts.append(
            "> 以下结论为 Agent 推断，尚未经过独立验证。"
            "审核时请对照原始证据。\n"
        )
        for i, claim in enumerate(uncertain, 1):
            body_parts.append(_format_dc_claim(claim, i))
        body_parts.append("")

    # Not-observed claims
    not_observed = [c for c in claims if c.status == "not_observed"]
    if not_observed:
        body_parts.append("## 未观察到的方面\n")
        for i, claim in enumerate(not_observed, 1):
            body_parts.append(_format_dc_claim(claim, i))
        body_parts.append("")

    # Evidence traceability section
    body_parts.append("## 证据可追溯性\n")
    all_refs: set[str] = set()
    for claim in claims:
        for ref in claim.evidence_refs:
            aid = ref.artifact_id
            loc = ref.locator
            kind = loc.get("kind", "?")
            detail = _describe_locator(loc)
            all_refs.add(f"- `{aid}` ({kind}): {detail}")
    for ref_line in sorted(all_refs):
        body_parts.append(ref_line)

    body = "\n".join(body_parts)

    # Source pages
    pages: list[str] = []
    if source_pages:
        pages.extend(source_pages)
    pages.append(f"capture:{source_capture_id}")

    return CandidateDraft(
        slug=slug,
        title=title,
        draft_type=draft_type,
        draft_area=target_domain,
        source_capture_id=source_capture_id,
        source_observation_id=observation_id,
        body=body,
        source_pages=tuple(pages),
    )


# ── helpers ─────────────────────────────────────────────────────────


def _truncate_title(text: str, max_len: int = 80) -> str:
    """Produce a title from claim text."""
    cleaned = text.strip().replace("\n", " ").replace("\r", "")
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 3].rstrip() + "..."


def _format_dc_claim(claim: Any, index: int) -> str:
    """Format a Claim dataclass as a Markdown subsection."""
    from agent_observation import Claim as ClaimDC, EvidenceRef

    if isinstance(claim, ClaimDC):
        status = claim.status
        text = claim.text.strip()
        claim_id = claim.claim_id
        confidence = claim.confidence
        refs = claim.evidence_refs
    else:
        # Dict fallback for loose callers
        status = claim.get("status", "uncertain")
        text = claim.get("text", "").strip()
        claim_id = claim.get("claim_id", f"claim-{index}")
        confidence = claim.get("confidence")
        refs = claim.get("evidence_refs", [])

    label = CLAIM_STATUS_LABEL.get(status, "[inferred]")

    lines = [
        f"### {index}. {label} {text}",
        f"",
        f"- Claim ID: `{claim_id}`",
    ]
    if confidence is not None:
        lines.append(f"- 置信度: {confidence:.0%}")

    if refs:
        lines.append("- 证据引用:")
        for ref in refs:
            if isinstance(ref, EvidenceRef):
                aid = ref.artifact_id
                loc = ref.locator
            else:
                aid = ref.get("artifact_id", "?")
                loc = ref.get("locator", {})
            lines.append(f"  - `{aid}` → {_describe_locator(loc)}")

    lines.append("")
    return "\n".join(lines)


def _format_claim(claim: Mapping[str, Any], index: int) -> str:
    """Format one claim dict as a Markdown subsection. (backward compat)"""
    return _format_dc_claim(claim, index)


def _describe_locator(locator: Mapping[str, Any]) -> str:
    """Human-readable description of a locator."""
    kind = locator.get("kind", "")
    if kind == "page":
        page = locator.get("page", "?")
        region = locator.get("region", "")
        return f"第 {page} 页" + (f" ({region})" if region else "")
    if kind == "bbox":
        bbox = locator.get("bbox", [])
        page = locator.get("bbox_page", "")
        base = f"bbox {bbox}"
        return f"{base} (第 {page} 页)" if page else base
    if kind == "timestamp":
        start = locator.get("start_ms", 0)
        end = locator.get("end_ms", 0)
        return f"{start}ms–{end}ms"
    if kind == "dom":
        xpath = locator.get("xpath_fragment", "?")
        return f"DOM: {xpath}"
    if kind == "document":
        section = locator.get("document_section", "")
        return f"文档" + (f" ({section})" if section else "")
    if kind == "custom":
        label = locator.get("custom_label", "?")
        return f"自定义: {label}"
    # Legacy free-form locator
    return str(dict(locator))
