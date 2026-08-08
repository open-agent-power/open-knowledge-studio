"""UTF-8-safe normalization of saved AgentKey responses into CaptureResult."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from capture_contract import (
    CaptureCost,
    CaptureEvidence,
    CaptureRequest,
    CaptureResult,
    ModalityResult,
)


CLASSIFICATIONS = {
    "full", "partial", "metadata_only", "challenge", "needs_user_auth", "failed",
}
_BV_RE = re.compile(r"BV[0-9A-Za-z]{8,16}")
_TEXT_KEYS = {"content", "text", "body", "transcript", "caption", "subtitle"}


def write_utf8_json(path: Path, payload: Any) -> Path:
    """Persist untrusted provider data as UTF-8 bytes without terminal encoding."""
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write((serialized + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def comparison_text(value: str) -> str:
    """Normalize only for matching; callers must retain the original value."""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    return " ".join(normalized.split())


def ascii_summary(result: CaptureResult) -> str:
    classification = _classification_from_warnings(result.warnings)
    value = {
        "classification": classification,
        "evidence_count": len(result.evidence),
        "has_content": bool(result.content_markdown.strip()),
        "provider": result.provider,
        "status": result.status,
    }
    summary = json.dumps(value, ensure_ascii=True, sort_keys=True)
    summary.encode("ascii")
    return summary


def _classification_from_warnings(warnings: Iterable[str]) -> str:
    prefix = "agentkey_classification="
    for warning in warnings:
        if warning.startswith(prefix):
            return warning[len(prefix):]
    return "full"


def _walk(value: Any, ancestors: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    yield ancestors, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, (*ancestors, str(key).lower()))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, (*ancestors, str(index)))
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"{", "["}:
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return
            yield from _walk(decoded, (*ancestors, "decoded_json"))


def _first_string(payload: Any, keys: set[str]) -> str | None:
    for path, value in _walk(payload):
        if path and path[-1] in keys and isinstance(value, str) and value.strip():
            return value
    return None


def _bvid(payload: Any) -> str | None:
    explicit = _first_string(payload, {"bvid", "bv_id", "bvid_str"})
    if explicit:
        match = _BV_RE.search(explicit)
        if match:
            return match.group(0)
    for _path, value in _walk(payload):
        if isinstance(value, str):
            match = _BV_RE.search(value)
            if match:
                return match.group(0)
    return None


def _subtitle_strings(payload: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for path, value in _walk(payload):
        if not isinstance(value, str) or not value.strip() or value.startswith(("http://", "https://")):
            continue
        context = set(path)
        has_subtitle_context = any(
            any(token in part for token in ("subtitle", "caption", "transcript"))
            for part in context
        )
        if not has_subtitle_context:
            continue
        leaf = path[-1] if path else ""
        if leaf not in _TEXT_KEYS and not leaf.isdigit():
            continue
        if value not in seen:
            seen.add(value)
            found.append(value)
    return found


def _challenge(payload: Any) -> bool:
    signals = (
        "login required", "need login", "needs_user_auth", "authentication required",
        "扫码登录", "需要登录", "请登录", "验证码", "captcha",
    )
    for _path, value in _walk(payload):
        if isinstance(value, str):
            normalized = comparison_text(value).lower()
            if any(signal in normalized for signal in signals):
                return True
    return False


@dataclass(frozen=True)
class BilibiliExtraction:
    classification: str
    title: str | None
    bvid: str | None
    subtitle_text: str
    matched_anchors: tuple[str, ...]


def classify_bilibili(payload: Any, *, anchors: Iterable[str]) -> BilibiliExtraction:
    title = _first_string(payload, {"title"})
    bvid = _bvid(payload)
    subtitle_text = "\n".join(_subtitle_strings(payload)).strip()
    normalized_subtitle = comparison_text(subtitle_text)
    anchor_values = tuple(anchors)
    matched = tuple(anchor for anchor in anchor_values if comparison_text(anchor) in normalized_subtitle)
    if _challenge(payload):
        classification = "needs_user_auth"
    elif subtitle_text and matched:
        classification = "full"
    elif subtitle_text:
        classification = "partial"
    elif title or bvid:
        classification = "metadata_only"
    else:
        classification = "failed"
    return BilibiliExtraction(classification, title, bvid, subtitle_text, matched)


class AgentKeyBilibiliAdapter:
    """Interpret one already-saved AgentKey Bilibili response without network I/O."""

    def __init__(
        self,
        response_path: Path,
        *,
        anchors: Iterable[str],
        provider: str,
        provider_version: str,
        credits: float | None = None,
        latency_ms: int | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.response_path = response_path.expanduser().resolve()
        self.anchors = tuple(anchors)
        self.provider = provider
        self.provider_version = provider_version
        self.credits = credits
        self.latency_ms = latency_ms
        self.started_at = started_at
        self.finished_at = finished_at

    def capture(self, request: CaptureRequest) -> CaptureResult:
        started_at = self.started_at or datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        raw = self.response_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        extraction = classify_bilibili(payload, anchors=self.anchors)
        measured_latency = round((time.monotonic() - started) * 1000)
        finished_at = self.finished_at or datetime.now(timezone.utc).isoformat()

        content = [f"# {extraction.title or extraction.bvid or 'Bilibili capture'}"]
        if extraction.bvid:
            content.append(f"- BV: `{extraction.bvid}`")
        if extraction.subtitle_text:
            content.extend(["## Subtitle", extraction.subtitle_text])
        evidence = tuple(
            CaptureEvidence(
                kind="text",
                method="agentkey_subtitle_anchor",
                locator={"anchor_index": index},
                text=anchor,
            )
            for index, anchor in enumerate(extraction.matched_anchors, start=1)
        )
        if not evidence and (extraction.title or extraction.bvid):
            evidence = (CaptureEvidence(
                kind="metadata",
                method="agentkey_video_metadata",
                locator={"bvid": extraction.bvid},
                text=extraction.title,
            ),)

        if extraction.classification == "full":
            status = "complete"
            modality_status = "succeeded"
            disposition = "none"
            warnings: tuple[str, ...] = ()
        elif extraction.classification in {"partial", "metadata_only", "needs_user_auth"}:
            status = "partial"
            modality_status = "partial"
            disposition = (
                "needs_user_auth"
                if extraction.classification == "needs_user_auth" else "needs_user_action"
            )
            warnings = (f"agentkey_classification={extraction.classification}",)
        else:
            status = "failed"
            modality_status = "failed"
            disposition = "final"
            warnings = ("agentkey_classification=failed",)

        return CaptureResult(
            status=status,
            provider=self.provider,
            provider_version=self.provider_version,
            capability="platform.bilibili",
            source_uri=request.source_uri,
            snapshot_path=self.response_path,
            snapshot_media_type="application/json",
            content_markdown="\n\n".join(content),
            title=extraction.title,
            modalities={
                "subtitle": ModalityResult(modality_status, evidence_count=len(evidence))
            },
            evidence=evidence,
            latency_ms=self.latency_ms if self.latency_ms is not None else measured_latency,
            cost=(CaptureCost(self.credits, "credits") if self.credits is not None else None),
            warnings=warnings,
            failure_disposition=disposition,
            raw_response_reference=self.response_path,
            started_at=started_at,
            finished_at=finished_at,
        )
