"""``oks ingest prepare`` — generate protocol skeleton for Agent ingestion.

Core principle: the Agent should fill in *evidence content*, not protocol
plumbing.  This module handles source detection, workspace creation, and
protocol skeleton generation so the Agent never needs to hand-craft a
SourceEnvelope, EvidenceManifest, or EvidenceFragment.
"""

from __future__ import annotations

import json
import os as _os
import uuid
from datetime import datetime, timezone
from hashlib import sha256 as _sha256
from pathlib import Path
from typing import Any

from importlib.resources import files as _resource_files

from knowledge_studio.store import repo_root
from knowledge_studio.security.redaction import redact_text
from knowledge_studio.security.sensitive_fields import REDACTED

# ── Source modality detection ──────────────────────────────────────

_MODALITY_MAP: dict[str, str] = {
    ".md": "text",
    ".txt": "text",
    ".csv": "text",
    ".json": "text",
    ".yaml": "text",
    ".yml": "text",
    ".pdf": "pdf",
    ".docx": "office",
    ".pptx": "office",
    ".xlsx": "office",
    ".html": "web",
    ".htm": "web",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp4": "video",
    ".mkv": "video",
    ".mov": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
}

_URL_PATTERNS: dict[str, str] = {
    "bilibili.com": "video",
    "youtube.com": "video",
    "youtu.be": "video",
    "douyin.com": "video",
}


def _detect_modality(source: str) -> str:
    """Detect source modality from file extension or URL pattern."""
    path = Path(source.split("?", 1)[0])
    suffix = path.suffix.lower()
    if suffix in _MODALITY_MAP:
        return _MODALITY_MAP[suffix]
    # Try URL patterns
    source_lower = source.lower()
    for domain, modality in _URL_PATTERNS.items():
        if domain in source_lower:
            return modality
    # Generic URL
    if source_lower.startswith(("http://", "https://")):
        return "web"
    return "text"


def _detect_access_mode(source: str) -> str:
    """Detect access mode from source string."""
    path = Path(source.split("?", 1)[0])
    if path.is_file() or path.exists():
        return "local_file"
    if source.startswith(("http://", "https://")):
        return "public_url"
    return "manual"


# ── prepare_ingest ─────────────────────────────────────────────────


def prepare_ingest(source: str, kb_root: Path | None = None) -> dict[str, Any]:
    """Create a run workspace and generate protocol skeleton for *source*.

    Returns a dict the CLI serializes to JSON:

    ```json
    {
      "run_id": "...",
      "workspace": "/path/to/.oks/runs/run-xxx/",
      "manifest_dir": "/path/to/.oks/runs/run-xxx/manifest/",
      "source": "...",
      "modality": "text",
      "source_id": "src-xxx",
      "content_hash": "sha256...",
      "files_generated": ["source-envelope.json", "evidence-manifest.json", ...],
      "next_step": "Fill evidence_records in evidence-manifest.json, then run: oks raw-commit ...",
      "text_ready": true   (only true when the scaffold includes pre-filled evidence)
    }
    ```
    """
    root = kb_root or Path(_os.environ.get("OKS_ROOT", repo_root()))
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    runs_dir = root / ".oks" / "runs" / run_id
    manifest_dir = runs_dir / "manifest"
    artifacts_dir = manifest_dir / "artifacts"
    fragments_dir = manifest_dir / "fragments"

    for d in [manifest_dir, artifacts_dir, fragments_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # ── Determine source metadata ──
    modality = _detect_modality(source)
    access_mode = _detect_access_mode(source)
    recipe = _load_recipe(modality)
    source_id = f"src-{uuid.uuid4().hex[:12]}"
    captured_at = datetime.now(timezone.utc).isoformat()
    is_text = modality == "text" and access_mode == "local_file"
    # ── Read and hash (local files only) ──
    source_bytes = b""
    content_hash = ""
    _artifact_hash = ""
    _sensitive_redacted = False
    _redaction_count = 0
    _missing_assets: list[str] = []
    if access_mode == "local_file":
        try:
            if is_text:
                raw_bytes = Path(source).read_bytes()
                # Source provenance hash uses original bytes, before sanitization.
                content_hash = _sha256(raw_bytes).hexdigest()
                # ── Deterministic sanitization (never modifies source file) ──
                _text = raw_bytes.decode("utf-8", errors="replace")
                _sanitized = redact_text(_text)
                _redaction_count = _sanitized.count(REDACTED)
                if _redaction_count > 0:
                    _sensitive_redacted = True
                    source_bytes = _sanitized.encode("utf-8")
                else:
                    source_bytes = raw_bytes
                # ── Artifact integrity hash (after sanitization, for _check_artifacts) ──
                _artifact_hash = _sha256(source_bytes).hexdigest()
            else:
                # Media can be many gigabytes; hash it without loading it all.
                content_hash = _hash_file(Path(source))
        except OSError:
            source_bytes = b""
            content_hash = ""

    if not content_hash:
        content_hash = _sha256(source.encode("utf-8")).hexdigest()

    # ── Build source-envelope.json ──
    envelope = {
        "schema_version": "oks-source-envelope/v0.1",
        "source_id": source_id,
        "source_uri": str(Path(source).resolve()) if access_mode == "local_file" else source,
        "source_modality": modality,
        "access_mode": access_mode,
        "captured_at": captured_at,
        "captured_by": {
            "runtime": "claude-code",
            "model": None,
            "skill": "ingest",
        },
        "content_hash": content_hash,
        "evidence_manifest_ref": f"manifest-{run_id}",
        "title": _title_from_source(source),
        "user_note": None,
        "policy": {
            # A reachable URL is not consent to send its content to a third-party
            # Provider. The Agent must resolve "ask" with the user before any
            # remote processing; local and manual sources remain local-only.
            "remote_processing": "ask" if access_mode == "public_url" else "deny",
            "sensitivity": "internal",
        },
    }

    # ── Build evidence-manifest.json skeleton ──
    manifest_id = f"manifest-{run_id}"
    fragment_id = f"frag-{uuid.uuid4().hex[:12]}"
    artifact_id = f"art-{uuid.uuid4().hex[:12]}"
    artifact_path = f"content{Path(source).suffix}" if is_text else "content.txt"

    manifest: dict[str, Any] = {
        "schema_version": "oks-evidence-manifest/v0.1",
        "manifest_id": manifest_id,
        "source_id": source_id,
        "status": "complete" if is_text else "partial",
        "fragment_refs": [fragment_id],
        "primary_artifact": {
            "artifact_id": artifact_id,
            "kind": "primary_text",
            "path": artifact_path,
            "media_type": _media_type(source),
            "sha256": _artifact_hash or content_hash,
            "locator_kind": "document",
        },
        "evidence_records": [],
        "modalities": {},
        "provenance": {
            "agent": {
                "runtime": "claude-code",
                "model": None,
                "skill": "ingest",
            },
            "latency_ms": None,
        },
        "steps": [],
        "notes": {},
    }

    # ── For text sources: pre-fill evidence ──
    text_ready = False
    if is_text and source_bytes:
        # Write artifact
        (artifacts_dir / artifact_path).write_bytes(source_bytes)

        # Pre-fill evidence record with text content
        text_content = source_bytes.decode("utf-8", errors="replace")
        manifest["evidence_records"] = [
            {
                "evidence_id": f"ev-{uuid.uuid4().hex[:12]}",
                "artifact_id": artifact_id,
                "kind": "text_content",
                "method": "text-read",
                "locator": {"kind": "document"},
                "text": text_content,
                "confidence": 1.0,
                "agent_judgment": "mechanical",
            }
        ]
        manifest["modalities"] = {
            "text": {
                "modality": "text",
                "status": "succeeded",
                "evidence_count": 1,
                "error_code": None,
            }
        }
        manifest["steps"] = [
            {
                "capability": "document.text.extract",
                "provider": "text-read",
                "status": "succeeded",
                "reason": None,
            }
        ]
        text_ready = True

        # ── Record sanitization metadata (never the secret itself) ──
        if _sensitive_redacted:
            manifest["notes"]["sensitive_content_redacted"] = True
            manifest["notes"]["redaction_count"] = _redaction_count

        # ── Scan Markdown for missing local image references ──
        _md_image_refs: list[str] = []
        _missing_assets: list[str] = []
        _md_image_re = __import__("re").compile(r'!\[[^\]]*\]\(([^)]+)\)')
        _md_image_refs = _md_image_re.findall(text_content)
        for _ref in _md_image_refs:
            # Skip URL and data-URI references (not locally checkable)
            if _ref.startswith(("http://", "https://", "data:")):
                continue
            _img_path = Path(source).parent / _ref if not Path(_ref).is_absolute() else Path(_ref)
            if not _img_path.exists():
                _missing_assets.append(_ref)

        if _missing_assets:
            manifest["status"] = "partial"
            manifest["failure_disposition"] = "needs_user_action"
            manifest["notes"]["missing_assets"] = _missing_assets
            manifest["notes"]["missing_assets_count"] = len(_missing_assets)
            manifest["notes"]["missing_assets_note"] = (
                f"文本已完整摄入，但 {len(_missing_assets)} 个本地图片资源不可访问。"
            )

    # ── For non-text sources: record the capability plan, not fake results ──
    if not is_text and recipe:
        required_caps = _parse_recipe_capabilities(recipe, "required_capabilities")
        if required_caps:
            # steps[], modalities{} and evidence_records[] describe what ran, and
            # the schema constrains only that shape. Pre-filling them with
            # provider: null / status: "pending" / locator-less records made every
            # non-text prepare emit a manifest that violated the schema 7 ways —
            # a skeleton raw-commit could never accept. The plan goes in notes,
            # which the schema leaves free-form.
            manifest["notes"]["planned_capabilities"] = [
                {
                    "capability": cap,
                    "modality": _capability_modality(cap),
                    "expected_kind": _capability_to_kind(cap),
                    "expected_method": _capability_to_method(cap),
                    "expected_locator_kind": _capability_to_locator_kind(cap),
                    "default_agent_judgment": _capability_default_judgment(cap),
                }
                for cap in required_caps
            ]
            manifest["primary_artifact"]["sha256"] = content_hash

    # ── Build evidence fragment skeleton ──
    fragment = {
        "schema_version": "oks-evidence-fragment/v0.1",
        "fragment_id": fragment_id,
        "source_id": source_id,
        "producer": {
            "runtime": "oks",
            "provider": "text-read" if is_text else "ok-ingest-prepare",
            "tool": "agent-runtime" if is_text else "ingest-prepare",
        },
        "status": "succeeded" if (is_text and not _missing_assets) else ("partial" if (is_text and _missing_assets) else "pending"),
        "artifacts": [
            {
                "artifact_id": artifact_id,
                "kind": "primary_text",
                "path": artifact_path,
                "sha256": _artifact_hash or content_hash,
            }
        ],
        "evidence": manifest["evidence_records"],
        "modalities": manifest["modalities"],
        "agent_notes": "Pre-filled by oks ingest prepare" if is_text else None,
    }

    # ── Write files ──
    _write_json(manifest_dir / "source-envelope.json", envelope)
    _write_json(manifest_dir / "evidence-manifest.json", manifest)
    _write_json(fragments_dir / f"{fragment_id}.json", fragment)

    files_generated = [
        "source-envelope.json",
        "evidence-manifest.json",
        f"fragments/{fragment_id}.json",
    ]
    if is_text and source_bytes:
        files_generated.append(f"artifacts/{artifact_path}")

    # ── For text_ready sources: persist work/ output for provenance check ──
    if text_ready and source_bytes:
        work_dir = runs_dir / "work" / "text-read"
        work_dir.mkdir(parents=True, exist_ok=True)
        _work_path = work_dir / "output.md"
        _work_path.write_bytes(source_bytes)
        _work_hash = _sha256(source_bytes).hexdigest()

    # ── Build candidate providers (filtered from capability registry) ──
    candidate_providers = _build_candidate_providers(
        recipe,
        modality,
        remote_processing=envelope["policy"]["remote_processing"],
    )

    next_step = _next_step(text_ready, run_id)

    return {
        "run_id": run_id,
        "workspace": str(runs_dir),
        "manifest_dir": str(manifest_dir),
        "source": source,
        "modality": modality,
        "access_mode": access_mode,
        "source_id": source_id,
        "content_hash": content_hash,
        "files_generated": files_generated,
        "text_ready": text_ready,
        "sensitive_content_redacted": _sensitive_redacted,
        "redaction_count": _redaction_count,
        "status": manifest.get("status", "complete"),
        "missing_assets": _missing_assets,
        "recipe": recipe,
        "candidate_providers": candidate_providers,
        "next_step": next_step,
    }


# ── helpers ─────────────────────────────────────────────────────────


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = _sha256()
    with path.open("rb") as source_file:
        while chunk := source_file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic JSON write."""
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            _os.fsync(f.fileno())
        _os.replace(tmp, str(path))
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _title_from_source(source: str) -> str:
    """Derive a human-readable title from a file path or URL."""
    path = Path(source.split("?", 1)[0])
    if path.suffix:
        return path.stem.replace("-", " ").replace("_", " ")
    if source.startswith(("http://", "https://")):
        return "Web Content"
    return "Untitled Source"


def _media_type(source: str) -> str | None:
    """Map file extension to media type."""
    suffix = Path(source.split("?", 1)[0]).suffix.lower()
    known = {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return known.get(suffix)


def _load_recipe(modality: str) -> str | None:
    """Load the Recipe markdown for *modality* from the package resource.

    Recipes live in ``knowledge_studio/recipes/`` inside the installed
    package — this is the canonical source.  The Agent receives recipe
    content through ``oks ingest prepare`` output rather than reading
    a file path that does not exist in the user's knowledge base.
    """
    try:
        recipe_path = _resource_files("knowledge_studio.recipes").joinpath(f"{modality}.md")
        if recipe_path.is_file():
            return recipe_path.read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError):
        pass
    return None


def _next_step(text_ready: bool, run_id: str) -> str:
    if text_ready:
        return (
            "Protocol skeleton is complete.  Evidence is pre-filled for this text source. "
            f"Run: oks raw-commit .oks/runs/{run_id}/manifest/ "
            "Then generate Candidate and proceed to /promote."
        )
    return (
        "Protocol skeleton created. `notes.planned_capabilities` lists the "
        "capabilities to cover; evidence_records, steps and modalities are "
        "empty on purpose — author one real entry per provider you actually "
        "run, and persist each provider's raw output to "
        "work/<provider>/output.<ext>.  "
        f"Then run: oks raw-commit .oks/runs/{run_id}/manifest/"
    )


# ── R4-5: Recipe parsing and capability-to-evidence-field mapping ────


def _parse_recipe_capabilities(recipe_text: str, section: str) -> list[str]:
    """Parse capability IDs from a recipe markdown section.

    Handles the indented YAML list format used in recipe markdown:
        required_capabilities:
          - document.text.extract
          - metadata.fetch
    """
    caps: list[str] = []
    in_section = False
    for line in recipe_text.splitlines():
        stripped = line.strip()
        if stripped == f"{section}:":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- ") and not stripped.startswith("- -"):
                cap = stripped[2:].strip()
                if cap:
                    caps.append(cap)
            elif stripped and not stripped.startswith("-"):
                # Next top-level key — exit the list
                if not line.startswith(" ") and not line.startswith("\t"):
                    break
    return caps


def _capability_to_kind(cap: str) -> str:
    """Map a capability ID to a default evidence kind."""
    mapping: dict[str, str] = {
        "document.text.extract": "text_content",
        "document.structure.extract": "structure",
        "document.render": "page_image",
        "web.fetch": "source_capture",
        "web.extract": "text_content",
        "web.screenshot": "screenshot",
        "image.ocr": "ocr_result",
        "image.observe": "observation",
        "metadata.fetch": "metadata",
        "media.download": "media_file",
        "subtitle.fetch": "subtitle",
        "speech.transcribe": "transcript",
        "audio.extract": "audio_track",
        "video.keyframes": "keyframe",
        "media.transcode": "media_file",
        "media.probe": "metadata",
        "layout.understand": "observation",
        "chart.interpret": "observation",
        "evidence.cross_check": "cross_check",
        "social.content.fetch": "text_content",
        "social.search": "text_content",
        "social.comments.fetch": "text_content",
        "social.creator.fetch": "metadata",
        "human.supply": "text_content",
    }
    return mapping.get(cap, "text_content")


def _capability_to_method(cap: str) -> str:
    """Map a capability ID to a default evidence method."""
    mapping: dict[str, str] = {
        "document.text.extract": "text_extraction",
        "document.structure.extract": "structure_extraction",
        "web.fetch": "http_fetch",
        "web.extract": "html_extract",
        "web.screenshot": "screenshot_capture",
        "image.ocr": "ocr_engine",
        "image.observe": "agent_multimodal_observation",
        "metadata.fetch": "metadata_extraction",
        "media.download": "media_download",
        "subtitle.fetch": "subtitle_extraction",
        "speech.transcribe": "asr_transcription",
        "audio.extract": "audio_extraction",
        "video.keyframes": "keyframe_extraction",
        "media.transcode": "media_transcode",
        "media.probe": "media_probe",
        "layout.understand": "agent_layout_analysis",
        "chart.interpret": "agent_chart_reading",
        "evidence.cross_check": "agent_cross_check",
        "social.content.fetch": "platform_content_fetch",
        "social.search": "platform_search",
        "social.comments.fetch": "platform_comments_fetch",
        "social.creator.fetch": "platform_creator_fetch",
        "human.supply": "human_supplied",
    }
    return mapping.get(cap, cap.replace(".", "_"))


def _capability_to_locator_kind(cap: str) -> str:
    """Map a capability ID to a default locator kind."""
    mapping: dict[str, str] = {
        "image.ocr": "bbox",
        "web.screenshot": "page",
        "subtitle.fetch": "timestamp",
        "speech.transcribe": "timestamp",
        "video.keyframes": "timestamp",
        "audio.extract": "timestamp",
    }
    return mapping.get(cap, "document")


def _capability_default_judgment(cap: str) -> str:
    """Return the default agent_judgment for a capability."""
    agent_observed_caps = {
        "image.observe", "layout.understand", "chart.interpret",
        "evidence.cross_check",
    }
    if cap in agent_observed_caps:
        return "agent_observed"
    if cap == "human.supply":
        return "human_supplied"
    return "mechanical"


def _capability_modality(cap: str) -> str:
    """Map a capability ID to a modality key for the manifest."""
    for prefix, mod in [
        ("document.", "text"),
        ("web.", "text"),
        ("image.", "image"),
        ("layout.", "layout"),
        ("speech.", "speech"),
        ("audio.", "speech"),
        ("video.", "video"),
        ("subtitle.", "text"),
        ("metadata.", "text"),
        ("media.", "video"),
        ("social.", "text"),
        ("human.", "text"),
        ("chart.", "layout"),
        ("evidence.", "text"),
    ]:
        if cap.startswith(prefix):
            return mod
    return "text"


def _build_candidate_providers(
    recipe: str | None,
    modality: str,
    *,
    remote_processing: str = "ask",
) -> list[dict[str, Any]]:
    """Return 2-4 candidate providers covering required capabilities.

    Filters the full capability registry to only providers that can satisfy
    at least one required capability for this modality's recipe.  Providers
    are sorted by availability (ready first, then configurable, then
    unavailable).

    This reduces the Agent's decision space from 17 providers to 2-4
    relevant ones — the Agent does not need to scan the full registry.
    """
    if not recipe:
        return []

    required_caps = _parse_recipe_capabilities(recipe, "required_capabilities")
    if not required_caps:
        return []

    # Lazy import to avoid circular dependency
    from knowledge_studio.capability_commands import capability_status

    status = capability_status()

    # Find providers that cover at least one required capability
    candidates: dict[str, dict[str, Any]] = {}
    for cap in required_caps:
        provider_ids = status.get("by_action", {}).get(cap, [])
        for pid in provider_ids:
            if pid in candidates:
                continue
            # Find the full provider entry
            for p in status.get("providers", []):
                if p["id"] == pid:
                    if (
                        remote_processing == "deny"
                        and p.get("execution") == "external"
                    ):
                        break
                    candidates[pid] = {
                        "id": pid,
                        "label": p.get("label", pid),
                        "execution": p.get("execution", ""),
                        "status": p.get("status", "unknown"),
                        "capabilities": p.get("capabilities", []),
                        "known_limits": p.get("known_limits", []),
                        "user_impact": p.get("user_impact", {}),
                    }
                    break

    # Sort: ready first, then runtime_only, then configurable, then unavailable
    status_order = {"ready": 0, "runtime_only": 1, "not_configured": 2,
                    "unavailable": 3, "blocked": 4, "experimental": 5}

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda p: status_order.get(p.get("status", "unknown"), 99),
    )

    # Return up to 4, but ensure all required capabilities are covered
    # If a required cap has only 1 provider, it must be included
    essential_ids: set[str] = set()
    for cap in required_caps:
        provider_ids = status.get("by_action", {}).get(cap, [])
        ready_ids = [
            pid for pid in provider_ids
            if candidates.get(pid, {}).get("status") == "ready"
        ]
        if len(provider_ids) == 1:
            essential_ids.add(provider_ids[0])
        elif ready_ids:
            # At least one ready provider per capability
            essential_ids.add(ready_ids[0])
        elif provider_ids:
            essential_ids.add(provider_ids[0])

    # Ensure essential providers come first, then fill to 4
    result = [p for p in sorted_candidates if p["id"] in essential_ids]
    for p in sorted_candidates:
        if p["id"] not in essential_ids and len(result) < 4:
            result.append(p)

    return result
