"""``oks raw commit`` ? validate and persist an Agent-submitted evidence bundle.

Protocol: the Agent submits a directory containing:

    <manifest-dir>/
    ??? source-envelope.json
    ??? evidence-manifest.json
    ??? fragments/                  # optional fragment snapshots
    ??? artifacts/                  # all evidence files

``oks raw commit`` validates against the formal JSON Schemas in
``schemas/``, checks cross-references, artifact existence + hash
matching, and locator legality.  On success it assembles a Raw Bundle
v0.2 and atomically writes it to ``raw/``.

This module does NOT call AI APIs, select extractors, or judge content
quality (CONSTITUTION P4, P5).
"""

from __future__ import annotations

import json
import os as _os
import re
import shutil
import tempfile as _tempfile
import uuid
from datetime import datetime, timezone
from hashlib import sha256 as _sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from knowledge_studio.store import repo_root


def create_run_workspace(source: str) -> dict[str, Any]:
    """Create an isolated Run Workspace for a source without invoking any Agent.

    Returns ``{run_id, workspace, source}`` ready for handoff to an Agent host.
    This function does NOT call any AI API or select any provider.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    knowledge_root = Path(_os.environ.get("OKS_ROOT", repo_root()))
    runs_dir = knowledge_root / ".oks" / "runs" / run_id
    workspace_dir = runs_dir / "work"
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # best effort

    return {
        "run_id": run_id,
        "workspace": str(workspace_dir),
        "source": source,
        "instruction": (
            "Open this workspace with a supported Agent Host (Claude Code, Codex) "
            "and run the /ingest skill."
        ),
    }


# ?? Artifact kind ? derived kind mapping (v0.2) ?

_ARTIFACT_KIND_TO_DERIVED: dict[str, str] = {
    "primary_text": "other",
    "page_image": "visual_observation",
    "ocr_result": "ocr",
    "subtitle": "other",
    "transcript": "other",
    "screenshot": "visual_observation",
    "dom_snapshot": "layout",
    "api_response": "other",
    "rendered_page": "visual_observation",
    "other": "other",
}


# ?? Error codes ???????????????????????????????????????????????????

class CommitError(Exception):
    """Structured rejection from oks raw commit."""
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# ?? Schema loading (cached) ???????????????????????????????????????

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}
_REGISTRY_CACHE: dict[str, Any] = {}
_VALIDATOR_AVAILABLE: bool | None = None  # tri-state: None=unchecked, True/False=checked


def _require_validator() -> None:
    """Ensure ``jsonschema`` and ``referencing`` are importable.

    Called at the entry point of ``raw_commit()`` so that *every* validation
    site is fail-closed: if the validator is unavailable, the commit is
    rejected rather than silently skipping schema enforcement.
    """
    global _VALIDATOR_AVAILABLE
    if _VALIDATOR_AVAILABLE is True:
        return
    missing: list[str] = []
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        missing.append("jsonschema")
    try:
        import referencing  # noqa: F401
    except ImportError:
        missing.append("referencing")
    if missing:
        _VALIDATOR_AVAILABLE = False
        raise CommitError(
            "SCHEMA_VALIDATOR_UNAVAILABLE",
            f"Schema validation requires {', '.join(missing)}. "
            f"Install with: pip install {' '.join(missing)}. "
            f"Raw Bundle commit is rejected when the formal Schema "
            f"validator cannot be loaded ? fail-closed by design.",
        )
    _VALIDATOR_AVAILABLE = True

def _load_schema(name: str) -> dict[str, Any]:
    """Load a JSON Schema from the packaged schemas directory."""
    if name not in _SCHEMA_CACHE:
        schema_text = (
            files("knowledge_studio.schemas").joinpath(name).read_text(encoding="utf-8")
        )
        _SCHEMA_CACHE[name] = json.loads(schema_text)
    return _SCHEMA_CACHE[name]


def _build_registry() -> Any | None:
    """Build a :mod:`referencing` Registry for ``$ref`` resolution.

    Returns ``None`` when ``referencing`` is not installed.
    The registry is cached; schemas are loaded on first call.
    """
    if "registry" in _REGISTRY_CACHE:
        return _REGISTRY_CACHE["registry"]
    try:
        from referencing import Registry, Resource as RefResource
    except ImportError:
        _REGISTRY_CACHE["registry"] = None
        return None

    schema_ids = [
        "source-envelope-v0.1.schema.json",
        "evidence-manifest-v0.1.schema.json",
        "evidence-fragment-v0.1.schema.json",
        "locator-v0.1.schema.json",
        "raw-bundle-v0.2.schema.json",
    ]
    resources: list[tuple[str, Any]] = []
    for name in schema_ids:
        s = _load_schema(name)
        resources.append((s["$id"], RefResource.from_contents(s)))

    _REGISTRY_CACHE["registry"] = Registry().with_resources(resources)
    return _REGISTRY_CACHE["registry"]


# ?? Validation helpers ????????????????????????????????????????????

def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CommitError("FILE_NOT_FOUND", str(exc)) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommitError("INVALID_JSON", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CommitError("INVALID_JSON", f"{path}: must be a JSON object")
    return value


def _validate_envelope(envelope: dict[str, Any]) -> None:
    """Validate source-envelope.json against the formal JSON Schema."""
    from jsonschema import validate, ValidationError as JsValidationError

    schema = _load_schema("source-envelope-v0.1.schema.json")
    registry = _build_registry()
    kwargs: dict[str, Any] = {}
    if registry is not None:
        kwargs["registry"] = registry
    try:
        validate(envelope, schema, **kwargs)
    except JsValidationError as exc:
        raise CommitError(
            "INVALID_ENVELOPE",
            f"source-envelope.json: {exc.message}",
            {"json_path": exc.json_path, "schema_path": list(exc.relative_schema_path)},
        ) from exc

    # Semantic checks beyond what JSON Schema can express
    ch = envelope.get("content_hash", "")
    if not re.fullmatch(r"[a-f0-9]{64}", str(ch)):
        raise CommitError(
            "INVALID_ENVELOPE",
            "source-envelope.json: content_hash must be 64 hex chars",
        )


def _validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate evidence-manifest.json against the formal JSON Schema."""
    from jsonschema import validate, ValidationError as JsValidationError

    schema = _load_schema("evidence-manifest-v0.1.schema.json")
    registry = _build_registry()
    kwargs: dict[str, Any] = {}
    if registry is not None:
        kwargs["registry"] = registry
    try:
        validate(manifest, schema, **kwargs)
    except JsValidationError as exc:
        raise CommitError(
            "INVALID_MANIFEST",
            f"evidence-manifest.json: {exc.message}",
            {"json_path": exc.json_path, "schema_path": list(exc.relative_schema_path)},
        ) from exc

    # Semantic check: partial must not use 'none' disposition
    if manifest.get("status") == "partial":
        fd = manifest.get("failure_disposition", "none")
        if fd == "none":
            raise CommitError(
                "INVALID_MANIFEST",
                "partial manifest must declare a non-'none' failure_disposition",
            )


def _cross_check(envelope: dict[str, Any], manifest: dict[str, Any]) -> None:
    if envelope["source_id"] != manifest["source_id"]:
        raise CommitError(
            "MANIFEST_SOURCE_MISMATCH",
            f"source-envelope.source_id ({envelope['source_id']!r}) != "
            f"evidence-manifest.source_id ({manifest['source_id']!r})",
            {
                "envelope_source_id": envelope["source_id"],
                "manifest_source_id": manifest["source_id"],
            },
        )


def _check_artifacts(manifest: dict[str, Any], artifacts_dir: Path) -> None:
    all_arts = [manifest["primary_artifact"]] + manifest.get("supplementary_artifacts", [])
    artifact_ids: set[str] = set()

    for art in all_arts:
        aid = art.get("artifact_id", "")
        path_str = art.get("path", "")
        declared_hash = art.get("sha256", "")

        if not aid or not path_str or not declared_hash:
            raise CommitError(
                "INVALID_ARTIFACT",
                f"artifact missing required fields: {art}",
            )

        if aid in artifact_ids:
            raise CommitError("DUPLICATE_ARTIFACT_ID", f"duplicate artifact_id: {aid!r}")
        artifact_ids.add(aid)

        fp = artifacts_dir / path_str
        # Prevent directory traversal
        try:
            fp.resolve().relative_to(artifacts_dir.resolve())
        except ValueError:
            raise CommitError(
                "PATH_TRAVERSAL",
                f"artifact path escapes artifacts/: {path_str}",
                {"artifact_id": aid, "path": path_str},
            )

        if not fp.is_file():
            raise CommitError(
                "MISSING_ARTIFACT",
                f"artifact file not found: {path_str}",
                {"artifact_id": aid, "path": path_str},
            )

        actual = _sha256(fp.read_bytes()).hexdigest()
        if actual != declared_hash:
            raise CommitError(
                "ARTIFACT_HASH_MISMATCH",
                f"hash mismatch for {aid!r}: "
                f"declared {declared_hash[:16]}..., actual {actual[:16]}...",
                {"artifact_id": aid, "expected": declared_hash, "actual": actual},
            )


def _check_evidence_cross_ref(manifest: dict[str, Any]) -> None:
    all_arts = [manifest["primary_artifact"]] + manifest.get("supplementary_artifacts", [])
    aid_set = {a["artifact_id"] for a in all_arts}

    for rec in manifest["evidence_records"]:
        rec_aid = rec.get("artifact_id", "")
        if rec_aid not in aid_set:
            raise CommitError(
                "ORPHAN_EVIDENCE",
                f"evidence record {rec.get('evidence_id', '?')!r} "
                f"references unknown artifact_id {rec_aid!r}",
                {"evidence_id": rec.get("evidence_id"), "artifact_id": rec_aid},
            )

    # Modality count consistency
    declared = sum(
        m.get("evidence_count", 0) for m in manifest["modalities"].values()
    )
    actual = len(manifest["evidence_records"])
    if declared != actual:
        raise CommitError(
            "EVIDENCE_COUNT_MISMATCH",
            f"modality evidence_count total ({declared}) != "
            f"actual evidence records ({actual})",
        )


def _check_fragment_manifest_consistency(
    manifest: dict[str, Any], manifest_dir: Path
) -> list[str]:
    """Validate Fragment ? Manifest evidence consistency.

    For each fragment_id in manifest.fragment_refs:
    1. If fragments/ dir does not exist, the check is skipped (backward
       compat ? older manifests may not have fragment snapshots).
    2. The fragment file must exist in fragments/ (MISSING_FRAGMENT).
    3. Every evidence_id in the fragment must exist in manifest
       evidence_records (FRAGMENT_EVIDENCE_NOT_IN_MANIFEST).
    4. For matching evidence_ids, compare stable core fields:
       artifact_id, kind, method, agent_judgment.
       If both sides declare the same field but values conflict ?
       FRAGMENT_MANIFEST_MISMATCH.

    This is a minimal mechanical check ? not a full lineage validator.
    Fields that are absent or null on either side are skipped (no false
    positives from incomplete fragments).

    Returns a list of warning strings (for locator_warnings-style output).
    """
    fragment_refs = manifest.get("fragment_refs", [])
    if not fragment_refs:
        return []  # No fragments to validate (shouldn't happen per schema minItems:1)

    fragments_dir = manifest_dir / "fragments"
    if not fragments_dir.is_dir():
        # Backward compat: older manifests may not include fragment snapshots.
        # When the directory does not exist, we skip the check rather than
        # breaking existing valid manifests.
        return [
            f"fragments/ directory not found ? "
            f"fragment_refs ({', '.join(fragment_refs)}) "
            f"could not be validated"
        ]

    manifest_records: dict[str, dict[str, Any]] = {
        rec["evidence_id"]: rec for rec in manifest["evidence_records"]
    }

    # Fields to compare when both sides declare them
    _COMPARE_FIELDS = ("artifact_id", "kind", "method", "agent_judgment")

    warnings: list[str] = []

    for frag_id in fragment_refs:
        frag_path = fragments_dir / f"{frag_id}.json"
        if not frag_path.is_file():
            raise CommitError(
                "MISSING_FRAGMENT",
                f"fragment_ref {frag_id!r} has no corresponding file at "
                f"fragments/{frag_id}.json",
                {"fragment_id": frag_id, "expected_path": str(frag_path)},
            )

        try:
            fragment = _read_json(frag_path)
        except CommitError as exc:
            raise CommitError(
                "INVALID_FRAGMENT",
                f"fragment file fragments/{frag_id}.json is not valid JSON: {exc}",
                {"fragment_id": frag_id, "error": str(exc)},
            ) from exc

        fragment_evidence = fragment.get("evidence", [])
        if not isinstance(fragment_evidence, list):
            raise CommitError(
                "INVALID_FRAGMENT",
                f"fragment {frag_id!r}: evidence must be an array",
                {"fragment_id": frag_id},
            )

        for fev in fragment_evidence:
            fev_id = fev.get("evidence_id", "")
            if not fev_id:
                raise CommitError(
                    "INVALID_FRAGMENT",
                    f"fragment {frag_id!r}: evidence record missing evidence_id",
                    {"fragment_id": frag_id},
                )

            # (1) Evidence must exist in manifest
            if fev_id not in manifest_records:
                raise CommitError(
                    "FRAGMENT_EVIDENCE_NOT_IN_MANIFEST",
                    f"fragment {frag_id!r} evidence {fev_id!r} not found "
                    f"in manifest evidence_records",
                    {"fragment_id": frag_id, "evidence_id": fev_id},
                )

            mev = manifest_records[fev_id]

            # (2) Compare core fields ? only when both sides declare a value
            mismatches: list[dict[str, Any]] = []
            for field in _COMPARE_FIELDS:
                f_val = fev.get(field)
                m_val = mev.get(field)
                # Only compare when both sides declare a non-None value
                if f_val is not None and m_val is not None and f_val != m_val:
                    mismatches.append({
                        "field": field,
                        "fragment_value": f_val,
                        "manifest_value": m_val,
                    })

            if mismatches:
                raise CommitError(
                    "FRAGMENT_MANIFEST_MISMATCH",
                    f"fragment {frag_id!r} evidence {fev_id!r}: "
                    f"{len(mismatches)} field(s) conflict between "
                    f"Fragment and Manifest",
                    {
                        "fragment_id": frag_id,
                        "evidence_id": fev_id,
                        "mismatches": mismatches,
                    },
                )

    return warnings


# Providers that do NOT produce external work/ output files.
# text-read: pre-filled by ingest prepare, no external tool execution
# agent-runtime: Agent's own multimodal observation, no external tool
# runtime-tool: ad-hoc tools (curl, playwright), not registered providers
# human: manually supplied by user
_NO_WORK_OUTPUT_PROVIDERS = frozenset({
    "text-read", "agent-runtime", "runtime-tool", "human",
})


def _verify_provenance_artifacts(
    manifest: dict[str, Any], manifest_dir: str | Path
) -> None:
    """Verify registered providers have work/ output files.

    When status is 'complete', every registered provider declared in
    manifest.steps[] with status 'succeeded' or 'degraded' must have
    corresponding work/<provider>/output.* files that exist and contain
    content (>0 bytes).

    This is a mechanical check ? Agent self-reported "I saved it" is not
    trusted.  If the work/ directory or output file is missing, the
    evidence provenance is unverifiable and the commit is rejected.

    Providers that don't produce external output (text-read, agent-runtime,
    runtime-tool, human) are excluded from this check.
    """
    if manifest.get("status") != "complete":
        return

    work_dir = manifest_dir.parent / "work"
    if not work_dir.is_dir():
        # No work/ directory at all ? but there may be no registered
        # providers that need one.  Check steps first.
        pass

    missing: list[str] = []
    empty: list[str] = []

    for step in manifest.get("steps", []):
        provider = step.get("provider", "")
        if not provider or provider in _NO_WORK_OUTPUT_PROVIDERS:
            continue
        if step.get("status") not in ("succeeded", "degraded"):
            continue

        pdir = work_dir / provider
        if not pdir.is_dir():
            missing.append(provider)
            continue

        files = list(pdir.iterdir())
        if not files:
            empty.append(provider)
            continue

        has_content = any(
            f.is_file() and f.stat().st_size > 0 for f in files
        )
        if not has_content:
            empty.append(provider)

    if missing or empty:
        raise CommitError(
            "PROVENANCE_UNVERIFIABLE",
            "Manifest status is 'complete' but registered provider raw "
            f"output is missing ({', '.join(missing) if missing else 'none'}) "
            f"or empty ({', '.join(empty) if empty else 'none'}). "
            f"Every registered provider must persist its raw output to "
            f"work/<provider>/output.<ext> before declaring complete. "
            f"Self-reported save is not proof.",
            {"missing_work_dirs": missing, "empty_work_dirs": empty},
        )


def _check_locators(manifest: dict[str, Any]) -> list[str]:
    """Validate each evidence locator against the formal Locator Schema v0.1.

    Legacy locators (missing ``kind``) are **rejected** ? they are no
    longer silently accepted.  Agents MUST declare locator structure
    explicitly per ``locator-v0.1.schema.json``.
    """
    locator_schema = _load_schema("locator-v0.1.schema.json")
    from jsonschema import validate, ValidationError as JsValidationError

    for rec in manifest["evidence_records"]:
        loc = rec.get("locator", {})
        if not isinstance(loc, dict) or not loc:
            raise CommitError(
                "INVALID_LOCATOR",
                f"evidence {rec.get('evidence_id', '?')!r}: "
                f"locator must be a non-empty object",
            )
        try:
            validate(loc, locator_schema)
        except JsValidationError as exc:
            raise CommitError(
                "INVALID_LOCATOR",
                f"evidence {rec.get('evidence_id', '?')!r}: "
                f"locator validation failed ? {exc.message}",
                {
                    "evidence_id": rec.get("evidence_id"),
                    "json_path": list(exc.json_path) if exc.json_path else [],
                    "validator": exc.validator,
                },
            ) from exc

    return []


# ?? Assembly ??????????????????????????????????????????????????????

def _assemble_bundle(
    envelope: dict[str, Any],
    manifest: dict[str, Any],
    manifest_dir: Path,
    output: Path,
) -> Path:
    """Assemble a Raw Bundle v0.2 on disk.

    Writes:
      - bundle.json  (v0.2 bundle manifest)
      - content.md
      - evidence.jsonl
      - quality-report.json
      - processing-runs.jsonl
      - source-envelope.json (snapshot)
      - evidence-manifest.json (snapshot)
      - raw.md (entry point)
      - source/   (original files)
      - assets/   (empty, reserved)
      - derived/  (fragments, supplementary artifacts)
    """
    artifacts_dir = manifest_dir / "artifacts"
    fragments_dir = manifest_dir / "fragments"

    final_output = output.expanduser().resolve()

    # ?? Atomic write helper ??
    def _atomic_write(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = _tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with _os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                _os.fsync(stream.fileno())
            _os.replace(tmp, str(path))
            try:
                fd = _os.open(str(path.parent), _os.O_RDONLY)
                _os.fsync(fd)
                _os.close(fd)
            except OSError:
                pass
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ?? Stage in a temp directory for atomic commit ??
    # Write everything to staging first; only promote to final_output
    # after bundle.json passes schema validation AND all declared
    # paths physically exist.  On any error the staging directory is
    # removed ? no partial bundle is left behind.
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(_tempfile.mkdtemp(
        prefix=f".{final_output.name}.", dir=final_output.parent))
    output = staging  # shadow ? all writes below go to staging

    try:
        # staging directory already created by mkdtemp above
        (output / "source").mkdir()
        (output / "assets").mkdir()
        (output / "derived").mkdir()
        (output / "derived" / "fragments").mkdir()

        # ?? Generate stable identifiers ??
        source_hash = envelope["content_hash"]
        source_id = envelope["source_id"]
        bundle_id = f"bundle:{source_hash[:16]}"
        generated_at = datetime.now(timezone.utc).isoformat()
        # Preserve the Agent's run_id from the manifest directory path
        run_id = manifest_dir.parent.name if manifest_dir.parent.name.startswith("run-") else f"run-{uuid.uuid4().hex[:12]}"

        primary = manifest["primary_artifact"]
        primary_src = artifacts_dir / primary["path"]

        # ?? Copy primary source file to source/ ??
        source_dest = output / "source" / primary["path"]
        source_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(primary_src, source_dest)

        # ?? content.md ? text rendering ??
        # Resolve text-vs-binary by checking, in order:
        #   1. media_type (explicit)
        #   2. artifact kind  (primary_text ? text)
        #   3. file extension  (common text formats)
        media_type = primary.get("media_type", "")
        art_kind = primary.get("kind", "")
        ext = primary["path"].rsplit(".", 1)[-1].lower() if "." in primary["path"] else ""
        _TEXT_EXTENSIONS: frozenset[str] = frozenset({
            "md", "txt", "json", "csv", "yaml", "yml", "xml", "html", "htm",
            "py", "js", "ts", "css", "sh", "bat", "ini", "cfg", "toml",
            "rst", "log", "text",
        })
        text_like = (
            media_type.startswith("text/")
            or media_type in ("application/json", "application/xml")
            or (not media_type and art_kind == "primary_text")
            or (not media_type and ext in _TEXT_EXTENSIONS)
        )
        if text_like:
            content_text = primary_src.read_text(encoding="utf-8")
            _atomic_write(output / "content.md", content_text.rstrip() + "\n")
        else:
            byte_size = primary.get("byte_size", primary_src.stat().st_size)
            _atomic_write(
                output / "content.md",
                f"Binary artifact: {primary['path']} ({media_type}, {byte_size} bytes)\n"
                f"See source/{primary['path']} for the original file.\n",
            )

        # ?? evidence.jsonl ??
        evidence_lines = []
        for rec in manifest["evidence_records"]:
            evidence_lines.append(json.dumps(rec, ensure_ascii=False) + "\n")
        _atomic_write(output / "evidence.jsonl", "".join(evidence_lines))

        # ?? Supplementary artifacts ? derived/ ??
        all_arts = [manifest["primary_artifact"]] + manifest.get("supplementary_artifacts", [])
        for art in all_arts:
            src = artifacts_dir / art["path"]
            if art is primary:
                continue
            dest = output / "derived" / art["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        # ?? Fragment snapshots ? derived/fragments/ ??
        if fragments_dir.is_dir():
            for fp in fragments_dir.iterdir():
                if fp.is_file():
                    shutil.copy2(fp, output / "derived" / "fragments" / fp.name)

        # ?? bundle.json (Raw Bundle v0.2 manifest) ??
        sources_list: list[dict[str, Any]] = [
            {
                "entity_id": primary["artifact_id"],
                "path": f"source/{primary['path']}",
                "sha256": primary.get("sha256", source_hash),
                "media_type": media_type or None,
                "snapshot_kind": "content",
                "content_hash_status": "verified",
                "primary_source": True,
            }
        ]
        # Supplementary artifacts are *derived* content (screenshots, OCR, etc.)
        # ? they belong in derived/, not sources/.  Only the primary artifact
        # represents the original captured material.
        derived_list: list[dict[str, Any]] = []
        derived_entities: list[str] = []
        for art in manifest.get("supplementary_artifacts", []):
            art_kind = art.get("kind", "other")
            derived_kind = _ARTIFACT_KIND_TO_DERIVED.get(art_kind, "other")
            entity_id = f"derived-{art['artifact_id']}"
            derived_list.append({
                "entity_id": entity_id,
                "kind": derived_kind,
                "path": f"derived/{art['path']}",
                "generated_by": "agent-ingest",
                "derived_from": [primary["artifact_id"]],
                "review_status": "not_applicable",
            })
            derived_entities.append(entity_id)

        provenance = {
            "entities": [
                {"id": eid, "type": "file"}
                for eid in [primary["artifact_id"]]
                + [a["artifact_id"] for a in manifest.get("supplementary_artifacts", [])]
                + derived_entities
            ],
            "activities": [
                {
                    "id": f"ingest-{run_id}",
                    "type": "agent-ingest",
                    "started_at": envelope.get("captured_at", generated_at),
                    "finished_at": generated_at,
                }
            ],
            "agents": [
                {
                    "id": envelope.get("captured_by", {}).get("runtime", "oks-agent"),
                    "type": "agent-runtime",
                }
            ],
            "relations": [
                {"type": "wasGeneratedBy", "subject": primary["artifact_id"], "object": f"ingest-{run_id}"},
            ],
        }

        bundle_json = {
            "schema_version": "raw-multimodal/v0.2",
            "bundle_id": bundle_id,
            "capture_id": source_id,
            "content_hash": source_hash,
            "recipe_version": "oks-agent-native-ingest/v0.1",
            "processing_status": manifest["status"],
            "files": {
                "manifest": "bundle.json",
                "content": "content.md",
                "evidence": "evidence.jsonl",
                "quality_report": "quality-report.json",
                "processing_runs": "processing-runs.jsonl",
                "source_dir": "source/",
                "assets_dir": "assets/",
                "derived_dir": "derived/",
            },
            "sources": sources_list,
            "derived": derived_list,
            "provenance": provenance,
            "warnings": list(manifest.get("warnings", [])),
        }

        # ?? Validate bundle_json against the formal Raw Bundle v0.2 Schema
        #     BEFORE persisting ? catch structural errors at assembly time.
        from jsonschema import validate, ValidationError as JsValidationError

        bundle_schema = _load_schema("raw-bundle-v0.2.schema.json")
        registry = _build_registry()
        kwargs_b: dict[str, Any] = {}
        if registry is not None:
            kwargs_b["registry"] = registry
        try:
            validate(bundle_json, bundle_schema, **kwargs_b)
        except JsValidationError as exc:
            raise CommitError(
                "INVALID_BUNDLE",
                f"assembled bundle.json fails schema validation: {exc.message}",
                {"json_path": list(exc.json_path) if exc.json_path else [],
                 "validator": exc.validator},
            ) from exc

        _atomic_write(
            output / "bundle.json",
            json.dumps(bundle_json, ensure_ascii=False, indent=2) + "\n",
        )

        # ?? source-envelope.json + evidence-manifest.json snapshots ??
        _atomic_write(
            output / "source-envelope.json",
            json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write(
            output / "evidence-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

        # ?? quality-report.json ??
        coverage: dict[str, dict[str, Any]] = {}
        for name, mod in manifest.get("modalities", {}).items():
            ec = mod.get("evidence_count", 0)
            coverage[name] = {
                "expected": 1,
                "observed": 1 if ec > 0 else 0,
                "status": "passed" if ec > 0 else "partial",
            }
        quality = {
            "schema_version": "raw-multimodal/v0.1",
            "processing_status": manifest["status"],
            "review_status": "pending",
            "evidence_count": len(manifest["evidence_records"]),
            "asset_count": max(0, len(all_arts) - 1),
            "coverage_status": manifest["status"],
            "coverage_checks": coverage,
            "warnings": list(manifest.get("warnings", [])),
            "errors": [],
            "human_fallback": (
                "Agent-native ingest.  Review the evidence manifest before "
                "creating a Candidate."
            ),
        }
        _atomic_write(
            output / "quality-report.json",
            json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        )

        # ?? raw.md (entry point) ??
        warnings_text = (
            "\n".join(f"- {w}" for w in manifest.get("warnings", [])) or "- ?\n"
        )
        raw_md = (
            f"---\nschema_version: raw-multimodal/v0.2\n"
            f"capture_id: {source_id}\n"
            f"processing_status: {manifest['status']}\n"
            f"review_status: pending\n"
            f"execution_protocol: {manifest['schema_version']}\n"
            f"---\n\n"
            f"# {envelope.get('title') or 'Agent-captured source'}\n\n"
            f"## ??\n\n- URI?`{envelope.get('source_uri', '')}`\n"
            f"- Agent?`{envelope.get('captured_by', {}).get('runtime', '?')}`\n\n"
            f"## Raw ???\n\n- [Bundle Manifest](bundle.json)\n"
            f"- [??](content.md)\n"
            f"- [????](evidence.jsonl)?{len(manifest['evidence_records'])} ?\n"
            f"- [Source Envelope](source-envelope.json)\n"
            f"- [Evidence Manifest](evidence-manifest.json)\n\n"
            f"## ????\n\n{warnings_text}"
        )
        _atomic_write(output / "raw.md", raw_md)

        # ?? processing-runs.jsonl (preserves Agent run_id) ??
        run_entry = {
            "run_id": run_id,
            "capture_id": source_id,
            "status": manifest["status"],
            "recipe_version": "oks-agent-native-ingest/v0.1",
            "started_at": envelope.get("captured_at", generated_at),
            "finished_at": generated_at,
        }
        _atomic_write(
            output / "processing-runs.jsonl",
            json.dumps(run_entry, ensure_ascii=False) + "\n",
        )

        # ?? Validate all declared paths exist on disk ??
        for s in sources_list:
            fp = output / s["path"]
            if not fp.is_file():
                raise CommitError(
                    "MISSING_BUNDLE_FILE",
                    f"declared source path not found in bundle: {s['path']}",
                    {"entity_id": s["entity_id"], "path": s["path"]},
                )
        for d in derived_list:
            fp = output / d["path"]
            if not fp.is_file():
                raise CommitError(
                    "MISSING_BUNDLE_FILE",
                    f"declared derived path not found in bundle: {d['path']}",
                    {"entity_id": d["entity_id"], "path": d["path"]},
                )

        # ?? Atomic commit: promote staging ? final output ??
        if final_output.exists():
            shutil.rmtree(final_output)
        shutil.move(str(output), str(final_output))
        return final_output

    except BaseException:
        # Clean up staging on ANY error ? no partial bundle left behind
        shutil.rmtree(staging, ignore_errors=True)
        raise


# ?? Main entry point ??????????????????????????????????????????????

def raw_commit(
    manifest_dir: str | Path,
    *,
    output: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate and commit an Agent-submitted evidence bundle.

    Args:
        manifest_dir: Path to the directory containing
            source-envelope.json, evidence-manifest.json, and artifacts/.
        output: Target directory for the Raw Bundle.  If None, a
            date-based path under ``raw/`` is generated.
        overwrite: If True, replace an existing bundle directory.

    Returns:
        ``{status: "committed", bundle_id, bundle_path, source_id, ...}``

    Raises:
        CommitError: On any structural or integrity violation.
    """
    md = Path(manifest_dir).expanduser().resolve()
    if not md.is_dir():
        raise CommitError(
            "MANIFEST_DIR_NOT_FOUND",
            f"manifest directory does not exist: {md}",
        )

    # ?? Fail-closed guard: schema validator MUST be available ??
    _require_validator()

    envelope_path = md / "source-envelope.json"
    manifest_path = md / "evidence-manifest.json"
    artifacts_dir = md / "artifacts"

    # ?? Step 1-2: Read files ??
    gather: list[CommitError] = []
    envelope: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None

    try:
        envelope = _read_json(envelope_path)
    except CommitError as exc:
        gather.append(exc)

    try:
        manifest = _read_json(manifest_path)
    except CommitError as exc:
        gather.append(exc)

    # ?? Schema validation: use iter_errors() for ALL violations ??
    # Independent error-count gates: a schema failure on one document
    # must NOT block semantic checks on the other, and semantic checks
    # that depend on specific fields must be skipped when their parent
    # schema validation failed (avoids KeyError on missing keys).

    # ?? Envelope schema validation ??
    _eg_pre = len(gather)
    if envelope is not None:
        from jsonschema import Draft202012Validator
        try:
            envelope_schema = _load_schema("source-envelope-v0.1.schema.json")
        except CommitError as exc:
            gather.append(exc)
            envelope_schema = None
        if envelope_schema is not None:
            for exc in Draft202012Validator(envelope_schema).iter_errors(envelope):
                gather.append(CommitError(
                    "INVALID_ENVELOPE",
                    f"source-envelope.json: {exc.message}",
                    {"json_path": exc.json_path,
                     "schema_path": list(exc.relative_schema_path)},
                ))
            # Semantic: content_hash format
            ch = envelope.get("content_hash", "")
            if not re.fullmatch(r"[a-f0-9]{64}", str(ch)):
                gather.append(CommitError(
                    "INVALID_ENVELOPE",
                    "source-envelope.json: content_hash must be 64 hex chars",
                ))
    envelope_schema_ok = (envelope is not None and len(gather) == _eg_pre)

    # ?? Manifest schema validation ??
    _mg_pre = len(gather)
    if manifest is not None:
        from jsonschema import Draft202012Validator
        try:
            manifest_schema = _load_schema("evidence-manifest-v0.1.schema.json")
        except CommitError as exc:
            gather.append(exc)
            manifest_schema = None
        if manifest_schema is not None:
            registry = _build_registry()
            validator_kwargs: dict[str, Any] = {}
            if registry is not None:
                validator_kwargs["registry"] = registry
            for exc in Draft202012Validator(
                manifest_schema, **validator_kwargs,
            ).iter_errors(manifest):
                gather.append(CommitError(
                    "INVALID_MANIFEST",
                    f"evidence-manifest.json: {exc.message}",
                    {"json_path": exc.json_path,
                     "schema_path": list(exc.relative_schema_path)},
                ))
            # Semantic: partial must declare failure_disposition
            if manifest.get("status") == "partial":
                fd = manifest.get("failure_disposition", "none")
                if fd == "none":
                    gather.append(CommitError(
                        "INVALID_MANIFEST",
                        "partial manifest must declare a non-'none' failure_disposition",
                    ))
    manifest_schema_ok = (manifest is not None and len(gather) == _mg_pre)

    # ?? Step 3: Cross-reference (only if BOTH schemas passed) ??
    if envelope_schema_ok and manifest_schema_ok:
        try:
            _cross_check(envelope, manifest)
        except CommitError as exc:
            gather.append(exc)

    # ?? Step 4-6: Artifact, evidence cross-ref, fragment consistency, locator ??
    locator_warnings: list[str] = []
    fragment_warnings: list[str] = []
    if manifest_schema_ok:
        if not artifacts_dir.is_dir():
            gather.append(CommitError(
                "MISSING_ARTIFACTS_DIR",
                f"artifacts/ directory not found: {artifacts_dir}",
            ))
        else:
            try:
                _check_artifacts(manifest, artifacts_dir)
            except CommitError as exc:
                gather.append(exc)

        try:
            _check_evidence_cross_ref(manifest)
        except CommitError as exc:
            gather.append(exc)

        try:
            fragment_warnings = _check_fragment_manifest_consistency(manifest, md)
        except CommitError as exc:
            gather.append(exc)

        try:
            _verify_provenance_artifacts(manifest, md)
        except CommitError as exc:
            gather.append(exc)

        try:
            locator_warnings = _check_locators(manifest)
        except CommitError as exc:
            gather.append(exc)
            locator_warnings = []

    # Combine warnings from all checks
    all_warnings: list[str] = fragment_warnings + locator_warnings

    # ?? Raise all errors at once ??
    if gather:
        raise CommitError(
            "VALIDATION_FAILED",
            f"Found {len(gather)} problem(s)",
            {"errors": [
                {"code": e.code, "message": e.message, "details": e.details}
                for e in gather
            ]},
        )

    # envelope and manifest are guaranteed non-None after gather check
    assert envelope is not None and manifest is not None

    # ?? Step 7: Determine output path ??
    if output is None:
        root = repo_root()
        today = datetime.now(timezone.utc)
        date_part = today.strftime("%Y/%m/%d")
        source_hash = envelope["content_hash"]
        output = (
            Path(root) / "raw" / date_part / "agent-capture"
            / f"bundle-{source_hash[:16]}"
        )
    else:
        output = Path(output).expanduser().resolve()

    if output.exists() and not overwrite:
        raise CommitError(
            "BUNDLE_ALREADY_EXISTS",
            f"output directory already exists: {output}. "
            f"Use --overwrite to replace.",
        )

    if output.exists() and overwrite:
        shutil.rmtree(output)

    # ?? Step 8: Assemble Raw Bundle v0.2 ??
    bundle_path = _assemble_bundle(envelope, manifest, md, output)

    return {
        "status": "committed",
        "bundle_id": f"bundle:{envelope['content_hash'][:16]}",
        "bundle_path": str(bundle_path),
        "source_id": envelope["source_id"],
        "content_hash": envelope["content_hash"],
        "evidence_count": len(manifest.get("evidence_records", [])),
        "artifact_count": 1 + len(manifest.get("supplementary_artifacts", [])),
        "locator_warnings": all_warnings,
    }
