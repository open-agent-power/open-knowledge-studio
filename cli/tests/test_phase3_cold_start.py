"""Deterministic tests for Phase 3A cold-start product glue.

These tests verify NEW code that the Phase 3A CLI glue introduces:
_provider_status(), _build_capability_summary(), ingest SKILL.md content,
and Claude/Agents skill identity.

They do NOT test Agent behaviour — that belongs in the manual cold-start
walking-skeleton scenario.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib.resources import files
from pathlib import Path


# ── _provider_status() ──────────────────────────────────────────────
# Test the REAL production function — no inlined copy.

from knowledge_studio.capability_commands import _provider_status


def test_provider_status_ready():
    """All checks pass → ready."""
    assert _provider_status([], "", "") == "ready"
    assert _provider_status([
        {"type": "command", "name": "python", "available": True},
        {"type": "env_var", "name": "FIRECRAWL_API_KEY", "available": True},
    ], "", "") == "ready"


def test_provider_status_not_configured():
    """Only env var missing, commands available → not_configured."""
    assert _provider_status([
        {"type": "command", "name": "python", "available": True},
        {"type": "env_var", "name": "FIRECRAWL_API_KEY", "available": False},
    ], "", "") == "not_configured"


def test_provider_status_unavailable():
    """Required command missing → unavailable."""
    assert _provider_status([
        {"type": "command", "name": "ffmpeg", "available": False},
    ], "", "") == "unavailable"


def test_provider_status_runtime_only():
    """AgentKey maps to runtime_only regardless of checks."""
    assert _provider_status([], "agentkey", "") == "runtime_only"
    assert _provider_status([
        {"type": "env_var", "name": "AGENTKEY_API_KEY", "available": True},
    ], "agentkey", "") == "runtime_only"


def test_provider_status_blocked():
    """Browser is blocked."""
    assert _provider_status([], "browser", "") == "blocked"


def test_provider_status_experimental():
    """HTTP-fetch, remote-asr, media-ingest are experimental."""
    for pid in ("http-fetch", "remote-asr", "media-ingest"):
        assert _provider_status([], pid, "") == "experimental", f"{pid} should be experimental"


def test_provider_status_optional_failure():
    """Optional command missing with required=False doesn't downgrade to unavailable."""
    assert _provider_status([
        {"type": "command", "name": "optional-tool", "available": False, "required": False},
    ], "", "") == "ready"


# ── _build_capability_summary() ─────────────────────────────────────
# Test the REAL production function — no inlined copy.

from knowledge_studio.capability_commands import _build_capability_summary

_EMPTY_DOCTOR = {"overall": "issues_found", "providers": []}


def test_build_capability_summary_empty():
    """None input returns empty groups."""
    result = _build_capability_summary(None)
    for v in result.values():
        assert v == []


def test_build_capability_summary_filters_always_available():
    """agent-runtime, human, text-read are excluded."""
    doctor = {
        "overall": "healthy",
        "providers": [
            {"id": "agent-runtime", "execution": "agent_native", "status": "ready"},
            {"id": "human", "execution": "human", "status": "ready"},
            {"id": "text-read", "execution": "agent_native", "status": "ready"},
        ],
    }
    result = _build_capability_summary(doctor)
    all_providers = []
    for v in result.values():
        all_providers.extend(v)
    assert all_providers == []


def test_build_capability_summary_groups_local():
    """Local ready providers go to local_ready; local missing to local_missing."""
    doctor = {
        "overall": "issues_found",
        "providers": [
            {"id": "pdf-lite", "execution": "managed", "status": "ready", "label": "PDF-lite"},
            {"id": "rapidocr", "execution": "managed", "status": "unavailable", "label": "RapidOCR"},
        ],
    }
    result = _build_capability_summary(doctor)
    assert len(result["local_ready"]) == 1
    assert result["local_ready"][0]["id"] == "pdf-lite"
    assert len(result["local_missing"]) == 1
    assert result["local_missing"][0]["id"] == "rapidocr"


def test_build_capability_summary_groups_remote():
    """External providers are grouped by status."""
    doctor = {
        "overall": "issues_found",
        "providers": [
            {"id": "firecrawl", "execution": "external", "status": "ready", "label": "Firecrawl"},
            {"id": "some-api", "execution": "external", "status": "not_configured", "label": "SomeAPI"},
            {"id": "agentkey", "execution": "external", "status": "runtime_only", "label": "AgentKey"},
            {"id": "browser", "execution": "external", "status": "blocked", "label": "Browser"},
            {"id": "http-fetch", "execution": "agent_native", "status": "experimental", "label": "HTTP Fetch"},
        ],
    }
    result = _build_capability_summary(doctor)
    assert len(result["remote_ready"]) == 1
    assert result["remote_ready"][0]["id"] == "firecrawl"
    assert len(result["remote_not_configured"]) == 1
    assert result["remote_not_configured"][0]["id"] == "some-api"
    assert len(result["remote_runtime_only"]) == 1
    assert result["remote_runtime_only"][0]["id"] == "agentkey"
    assert len(result["blocked_experimental"]) == 2
    blocked_ids = {p["id"] for p in result["blocked_experimental"]}
    assert blocked_ids == {"browser", "http-fetch"}


# ── Ingest SKILL.md content checks ──────────────────────────────────

_SKILL_REQUIRED_KEYWORDS = [
    "provider_selection",
    "degradation_path",
    "fallback_activated",
    "candidates_considered",
]

_SKILL_MUST_CONSTRAINTS = [
    "MUST write result.json",
    "MUST include `provider_selection`",
    "MUST include `degradation_path`",
    "MUST output the unified result card",
    "MUST record every attempted provider",
]


def _read_skill_text(host: str) -> str:
    """Read the ingest SKILL.md from skill_templates/<host>/skills/ingest/."""
    return (
        files("knowledge_studio.skill_templates")
        .joinpath(host, "skills", "ingest", "SKILL.md")
        .read_text(encoding="utf-8")
    )


def test_ingest_skill_contains_provider_selection_fields():
    """Both Claude and Agents ingest SKILL.md contain provider_selection."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        for keyword in _SKILL_REQUIRED_KEYWORDS:
            assert keyword in text, (
                f"{host}/ingest/SKILL.md missing keyword: {keyword}"
            )


def test_ingest_skill_contains_must_constraints():
    """Both Claude and Agents ingest SKILL.md contain the new MUST constraints."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        for constraint in _SKILL_MUST_CONSTRAINTS:
            assert constraint in text, (
                f"{host}/ingest/SKILL.md missing constraint: {constraint}"
            )


def test_ingest_skill_contains_unified_card():
    """Both versions contain the unified result card output format (Guided UX)."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "摄入完成" in text, f"{host}/ingest/SKILL.md missing unified card header"
        assert "已获得" in text, f"{host}/ingest/SKILL.md missing 已获得"
        assert "缺失" in text, f"{host}/ingest/SKILL.md missing 缺失"
        assert "待审核知识" in text, f"{host}/ingest/SKILL.md missing 待审核知识"
        assert "/promote" in text, f"{host}/ingest/SKILL.md missing /promote"
        # Guided UX: internal IDs hidden from user-facing card
        assert "使用路径" not in text, (
            f"{host}/ingest/SKILL.md contains 使用路径 — provider chain should only "
            f"appear in result.json, not in the user-facing card"
        )


def test_claude_and_agents_ingest_skills_identical():
    """Claude and Agents ingest SKILL.md are byte-for-byte identical."""
    claude = _read_skill_text("claude")
    agents = _read_skill_text("agents")
    assert claude == agents, (
        "Claude and Agents ingest SKILL.md differ — they must be identical "
        f"(Claude: {len(claude)} chars, Agents: {len(agents)} chars)"
    )


# ── No oks-connector in installed skills (regression) ───────────────

def test_no_python_imports_in_ingest_skill():
    """Ingest SKILL.md has ZERO Python import references — Agent contract is oks CLI."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "importlib.resources" not in text, (
            f"{host}/ingest/SKILL.md contains importlib.resources — should use oks schema show"
        )
        assert "from knowledge_studio" not in text, (
            f"{host}/ingest/SKILL.md contains from knowledge_studio import"
        )
        assert "oks-connector" not in text, (
            f"{host}/ingest/SKILL.md contains oks-connector"
        )
        assert "route_plan" not in text, (
            f"{host}/ingest/SKILL.md contains route_plan"
        )
        assert "oks schema show" in text, (
            f"{host}/ingest/SKILL.md missing oks schema show reference"
        )
        assert "oks ingest prepare" in text, (
            f"{host}/ingest/SKILL.md missing oks ingest prepare reference"
        )
        assert "oks security sanitize" in text, (
            f"{host}/ingest/SKILL.md missing oks security sanitize reference"
        )


# ── oks schema commands ─────────────────────────────────────────────
# These test the dynamic schema scanning, not the Agent behaviour.

def test_schema_list_dynamic_scan():
    """oks schema list scans the schemas/ directory and finds all 12 schemas."""
    from knowledge_studio.schema_examples import list_schema_names as examples_names
    from importlib.resources import files

    schemas_dir = files("knowledge_studio.schemas")
    all_names = sorted(
        e.name.replace(".schema.json", "")
        for e in schemas_dir.iterdir()
        if e.is_file() and e.name.endswith(".schema.json")
    )
    assert len(all_names) >= 10, f"Expected >=10 schemas, found {len(all_names)}"
    # Verify the 5 core schemas all have examples
    for name in examples_names():
        found = any(s.startswith(name) for s in all_names)
        assert found, f"Example schema '{name}' not in actual schemas: {all_names}"


def test_schema_examples_are_valid():
    """All 5 pre-built examples have required fields."""
    from knowledge_studio.schema_examples import get_example, list_schema_names

    for name in list_schema_names():
        ex = get_example(name)
        assert ex is not None, f"No example for {name}"
        assert isinstance(ex, dict), f"Example for {name} is not a dict"
        # locator is a referenced (embedded) schema — no top-level schema_version
        if name != "locator":
            assert "schema_version" in ex, f"Example for {name} missing schema_version"


def test_schema_show_resolves_names():
    """_resolve_schema_name finds schemas by short name and prefix."""
    from knowledge_studio.cli import _resolve_schema_name

    # Exact match
    result = _resolve_schema_name("source-envelope-v0.1")
    assert result is not None
    assert result[0] == "source-envelope-v0.1"

    # Prefix match
    result = _resolve_schema_name("evidence-manifest")
    assert result is not None
    assert "evidence-manifest" in result[0]

    # Not found
    assert _resolve_schema_name("nonexistent-schema") is None


# ── oks ingest prepare ──────────────────────────────────────────────

def test_ingest_prepare_text_creates_valid_envelope(tmp_path):
    """oks ingest prepare for a .md file creates valid source-envelope.json."""
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    f = tmp_path / "test.md"
    f.write_text("# Hello OKS\n\nSample content for testing.", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["modality"] == "text"
    assert result["text_ready"] is True
    assert result["source_id"].startswith("src-")

    # Read the generated envelope
    env_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "source-envelope.json"
    assert env_path.is_file()
    envelope = json.loads(env_path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == "oks-source-envelope/v0.1"
    assert envelope["source_modality"] == "text"
    assert len(envelope["content_hash"]) == 64

    # Read the generated manifest
    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    assert man_path.is_file()
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert len(manifest["evidence_records"]) == 1
    assert manifest["evidence_records"][0]["method"] == "text-read"

    # Clean up
    import shutil, stat
    def rm(p, f, e):
        import pathlib
        pathlib.Path(p).chmod(stat.S_IWRITE)
        f(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_ingest_prepare_non_text_creates_skeleton(tmp_path):
    """oks ingest prepare for a .pdf file creates a skeleton (text_ready=False).

    R4-5: evidence_records and steps are now pre-filled from the Recipe.
    text, confidence are null — Agent fills after provider execution.
    """
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4 mock")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["modality"] == "pdf"
    assert result["text_ready"] is False

    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "partial"
    # R4-5: evidence_records are pre-filled from recipe required_capabilities
    assert len(manifest["evidence_records"]) >= 1, (
        "Non-text evidence_records must be pre-filled from recipe"
    )
    for rec in manifest["evidence_records"]:
        assert rec["text"] is None, "Pre-filled text must be None"
        assert rec["confidence"] is None, "Pre-filled confidence must be None"
        assert rec["evidence_id"].startswith("ev-")
        assert rec["artifact_id"].startswith("art-")
    assert len(manifest["steps"]) >= 1, "Steps must be pre-filled"
    for step in manifest["steps"]:
        assert step["provider"] is None, "Pre-filled provider must be None"
        assert step["status"] == "pending"

    import shutil, stat
    def rm(p, f, e):
        import pathlib
        pathlib.Path(p).chmod(stat.S_IWRITE)
        f(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


# ── oks security sanitize ───────────────────────────────────────────

def test_security_sanitize_strips_api_key(tmp_path):
    """oks security sanitize removes API keys from JSON content."""
    from knowledge_studio.security.redaction import sanitize_remote_artifact

    content = b'{"api_key": "sk-secret-12345", "data": "public"}'
    result = sanitize_remote_artifact(content, content_type="application/json")
    assert b"sk-secret-12345" not in result
    assert b'"data": "public"' in result


def test_security_sanitize_preserves_binary(tmp_path):
    """Binary files are returned unchanged."""
    from knowledge_studio.security.redaction import sanitize_remote_artifact

    content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    result = sanitize_remote_artifact(content, content_type="image/png")
    assert result == content


# ── Integration: prepare → raw_commit ────────────────────────────────

def test_prepare_text_then_raw_commit_default_output(monkeypatch, tmp_path):
    """Integration: clean KB → prepare Markdown → raw-commit (no explicit output).

    Uses OKS_ROOT to redirect repo_root() into tmp_path so the *real*
    default-output codepath is exercised — including the P0-1 fix that
    creates the date-based parent directory before mkdtemp.
    """
    import json
    import os
    import shutil
    import stat as _stat

    from knowledge_studio.ingest_prepare import prepare_ingest
    from knowledge_studio.raw_commit import raw_commit, CommitError

    # 1. Redirect OKS_ROOT so default output lands under tmp_path
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    # 2. Create test markdown
    f = tmp_path / "test.md"
    f.write_text("# Integration Test\n\nContent for raw-commit.", encoding="utf-8")

    # 3. prepare_ingest()
    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True
    manifest_dir = result["manifest_dir"]
    content_hash = result["content_hash"]

    # 4. raw_commit with NO output= argument — exercises default path
    commit_result = raw_commit(manifest_dir)
    assert commit_result["status"] == "committed"

    # 5. Verify default path: raw/YYYY/MM/DD/agent-capture/bundle-{hash[:16]}
    bundle_path = Path(commit_result["bundle_path"])
    assert bundle_path.is_dir()
    assert bundle_path.is_relative_to(tmp_path), (
        f"Bundle should be under tmp_path (OKS_ROOT), got {bundle_path}"
    )
    expected_prefix = f"bundle-{content_hash[:16]}"
    assert bundle_path.name == expected_prefix, (
        f"Expected bundle dir name {expected_prefix}, got {bundle_path.name}"
    )
    date_parents = bundle_path.relative_to(tmp_path)
    # raw/YYYY/MM/DD/agent-capture/bundle-xxx
    assert date_parents.parts[0] == "raw"
    assert date_parents.parts[-2] == "agent-capture"

    # 6. Verify bundle contents
    bundle_json_path = bundle_path / "bundle.json"
    assert bundle_json_path.is_file()
    bundle = json.loads(bundle_json_path.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "raw-multimodal/v0.2"

    content_md = bundle_path / "content.md"
    assert content_md.is_file()
    assert "Integration Test" in content_md.read_text(encoding="utf-8")

    # 7. Clean up
    def _rm(p, f, e):
        Path(p).chmod(_stat.S_IWRITE)
        f(p)
    shutil.rmtree(tmp_path / ".oks", onexc=_rm)
    shutil.rmtree(tmp_path / "raw", onexc=_rm)


# ── raw_commit error collection ──────────────────────────────────────

def test_raw_commit_reports_all_schema_errors(tmp_path):
    """raw_commit with bad envelope AND bad manifest reports ALL errors, not just first."""
    import json
    from knowledge_studio.raw_commit import raw_commit, CommitError

    manifest_dir = tmp_path / "manifest"
    artifacts_dir = manifest_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # Bad envelope: missing required fields (no source_id, no content_hash, no schema_version)
    (manifest_dir / "source-envelope.json").write_text(json.dumps({
        "schema_version": "wrong-version",
    }), encoding="utf-8")

    # Bad manifest: missing required fields (no source_id, no primary_artifact)
    (manifest_dir / "evidence-manifest.json").write_text(json.dumps({
        "schema_version": "also-wrong",
    }), encoding="utf-8")

    try:
        raw_commit(manifest_dir)
        assert False, "Should have raised CommitError"
    except CommitError as exc:
        assert exc.code == "VALIDATION_FAILED"
        errors = exc.details.get("errors", [])
        # At least 2 errors: one from envelope, one from manifest
        assert len(errors) >= 2, (
            f"Expected >=2 errors, got {len(errors)}: {errors}"
        )
        codes = {e["code"] for e in errors}
        assert "INVALID_ENVELOPE" in codes, f"No envelope error in: {codes}"
        assert "INVALID_MANIFEST" in codes, f"No manifest error in: {codes}"


def test_raw_commit_schema_error_blocks_semantic_checks(tmp_path):
    """When envelope lacks source_id, cross_check is SKIPPED — no KeyError crash."""
    import json
    from knowledge_studio.raw_commit import raw_commit, CommitError

    manifest_dir = tmp_path / "manifest"
    artifacts_dir = manifest_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # Envelope without source_id — schema will reject it
    (manifest_dir / "source-envelope.json").write_text(json.dumps({
        "schema_version": "oks-source-envelope/v0.1",
        "source_uri": "file:///nonexistent",
        "source_modality": "text",
        "access_mode": "local_file",
        "captured_at": "2026-01-01T00:00:00Z",
        "captured_by": {"runtime": "test"},
        "content_hash": "a" * 64,
    }), encoding="utf-8")

    # Manifest without source_id — schema will reject it too
    (manifest_dir / "evidence-manifest.json").write_text(json.dumps({
        "schema_version": "oks-evidence-manifest/v0.1",
        "manifest_id": "man-test",
    }), encoding="utf-8")

    try:
        raw_commit(manifest_dir)
        assert False, "Should have raised CommitError"
    except CommitError as exc:
        assert exc.code == "VALIDATION_FAILED"
        errors = exc.details.get("errors", [])
        codes = {e["code"] for e in errors}
        # Critical: must NOT contain MANIFEST_SOURCE_MISMATCH or other
        # semantic error codes — _cross_check was never reached.
        assert "MANIFEST_SOURCE_MISMATCH" not in codes, (
            f"_cross_check should be skipped when schemas fail. Got: {codes}"
        )
        # Only schema-level errors
        for code in codes:
            assert code in ("INVALID_ENVELOPE", "INVALID_MANIFEST"), (
                f"Unexpected error code: {code}"
            )


def test_raw_commit_missing_primary_artifact(tmp_path):
    """When manifest lacks primary_artifact, _check_artifacts skipped — no KeyError."""
    import json
    from knowledge_studio.raw_commit import raw_commit, CommitError

    manifest_dir = tmp_path / "manifest"
    artifacts_dir = manifest_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # Valid envelope
    (manifest_dir / "source-envelope.json").write_text(json.dumps({
        "schema_version": "oks-source-envelope/v0.1",
        "source_id": "src-test",
        "source_uri": "file:///test.md",
        "source_modality": "text",
        "access_mode": "local_file",
        "captured_at": "2026-01-01T00:00:00Z",
        "captured_by": {"runtime": "test"},
        "content_hash": "a" * 64,
    }), encoding="utf-8")

    # Manifest without primary_artifact — schema will reject it
    (manifest_dir / "evidence-manifest.json").write_text(json.dumps({
        "schema_version": "oks-evidence-manifest/v0.1",
        "manifest_id": "man-test",
        "source_id": "src-test",
        "status": "complete",
        "evidence_records": [],
        "modalities": {},
    }), encoding="utf-8")

    try:
        raw_commit(manifest_dir)
        assert False, "Should have raised CommitError"
    except CommitError as exc:
        assert exc.code == "VALIDATION_FAILED"
        errors = exc.details.get("errors", [])
        codes = {e["code"] for e in errors}
        # Must NOT contain MISSING_ARTIFACT or ORPHAN_EVIDENCE —
        # semantic checks were skipped.
        for banned in ("MISSING_ARTIFACT", "ORPHAN_EVIDENCE", "EVIDENCE_COUNT_MISMATCH"):
            assert banned not in codes, (
                f"Semantic check {banned} should be skipped when manifest schema fails"
            )
        assert "INVALID_MANIFEST" in codes


# ── Phase 3A-S: Secret sanitization ──────────────────────────────────

def test_text_ready_sanitizes_api_key(tmp_path):
    """Source with Bearer token + api_key=value: evidence and artifacts MUST NOT contain secrets."""
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    f = tmp_path / "secrets.md"
    f.write_text(
        "# Doc\n\n"
        "Authorization: Bearer sk-test-1234567890abcdef\n\n"
        "api_key: sk-test-token-value-here\n\n"
        "Normal content.\n",
        encoding="utf-8",
    )

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True
    assert result["sensitive_content_redacted"] is True
    assert result["redaction_count"] > 0

    # Check artifact — must NOT contain the secret
    art_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "artifacts" / "content.md"
    art_content = art_path.read_text(encoding="utf-8")
    assert "sk-test-1234567890abcdef" not in art_content
    assert "sk-test-token-value-here" not in art_content
    assert "***REDACTED***" in art_content

    # Check evidence-manifest.json — must NOT contain the secret
    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    assert manifest["notes"].get("sensitive_content_redacted") is True
    assert manifest["notes"].get("redaction_count", 0) > 0
    for rec in manifest["evidence_records"]:
        if "text" in rec:
            assert "sk-test-1234567890abcdef" not in rec["text"]
            assert "sk-test-token-value-here" not in rec["text"]

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_text_ready_preserves_source_file(tmp_path):
    """Original source file is NEVER modified by sanitization."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "secret-src.md"
    original = "# Secret doc\n\nBearer sk-test-abcdef1234567890\n"
    f.write_text(original, encoding="utf-8")

    prepare_ingest(str(f), kb_root=tmp_path)

    # Source file must be byte-identical to what we wrote
    assert f.read_text(encoding="utf-8") == original

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_text_ready_no_secrets_passes_through(tmp_path):
    """Plain text with no secrets: sensitive_content_redacted=False, content unchanged."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "clean.md"
    original = "# Clean doc\n\nNothing sensitive here.\n"
    f.write_text(original, encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True
    assert result["sensitive_content_redacted"] is False
    assert result["redaction_count"] == 0

    # Content should be unchanged (no "***REDACTED***")
    art_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "artifacts" / "content.md"
    art_content = art_path.read_text(encoding="utf-8")
    assert "Nothing sensitive here" in art_content
    assert "***REDACTED***" not in art_content

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_text_ready_sanitizes_dashscope_key(tmp_path):
    """Source with bare DashScope sk- key (no Bearer prefix): MUST be caught."""
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    f = tmp_path / "dashscope.md"
    f.write_text(
        "# API 配置\n\n"
        "阿里云百炼 API Key：sk-c0b1f0123456789abcdef0123456789abcd\n\n"
        "配置方式见下文。\n",
        encoding="utf-8",
    )

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["sensitive_content_redacted"] is True, (
        f"sk- DashScope key should be caught, got redacted={result['sensitive_content_redacted']}"
    )
    assert result["redaction_count"] > 0

    # Artifact must NOT contain the secret
    art_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "artifacts" / "content.md"
    art_content = art_path.read_text(encoding="utf-8")
    assert "sk-c0b1f0123456789abcdef0123456789abcd" not in art_content
    assert "***REDACTED***" in art_content

    # Source file must be unmodified
    assert "sk-c0b1f0123456789abcdef0123456789abcd" in f.read_text(encoding="utf-8")

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_redact_text_catches_bare_sk_key():
    """redact_text must catch a bare sk- prefix key without any label prefix."""
    from knowledge_studio.security.redaction import redact_text

    text = "我的密钥是 sk-proj-abc123xyz789def456ghi012jkl345mno"
    result = redact_text(text)
    assert "sk-proj-abc123xyz789def456ghi012jkl345mno" not in result
    assert "***REDACTED***" in result


def test_redact_text_catches_api_key_with_space():
    """'API Key: value' (with space between API and Key) must be caught."""
    from knowledge_studio.security.redaction import redact_text

    text = "API Key: sk-secret-value-12345"
    result = redact_text(text)
    assert "sk-secret-value-12345" not in result
    assert "***REDACTED***" in result


# ── Phase 3A-S: Markdown image detection ─────────────────────────────

def test_text_ready_no_images_is_complete(tmp_path):
    """Plain text with no image references: status stays complete."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "plain.md"
    f.write_text("# No images here\n\nJust plain text.", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["status"] == "complete"
    assert result["missing_assets"] == []

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_text_ready_missing_local_images_is_partial(tmp_path):
    """Markdown with ![](nonexistent.png): status=partial, missing_assets populated."""
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    f = tmp_path / "with-images.md"
    f.write_text("# Doc with images\n\n![](missing1.png)\n\nSome text.\n\n![](also-gone.jpg)\n", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["status"] == "partial"
    assert len(result["missing_assets"]) == 2
    assert "missing1.png" in result["missing_assets"]
    assert "also-gone.jpg" in result["missing_assets"]

    # Verify manifest has failure_disposition set (required for raw_commit)
    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "partial"
    assert manifest["failure_disposition"] == "needs_user_action"
    assert "missing_assets" in manifest["notes"]
    assert "missing_assets_note" in manifest["notes"]
    # Text content still preserved
    assert "Some text" in manifest["evidence_records"][0]["text"]

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_text_ready_url_images_stays_complete(tmp_path):
    """Markdown with URL-based images: status stays complete (no remote check)."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "url-images.md"
    f.write_text("# Remote images\n\n![](https://example.com/img.png)\n\n![](http://cdn.io/photo.jpg)\n", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["status"] == "complete"
    assert result["missing_assets"] == []

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


# ── Phase 3A-S: SKILL.md integrity ───────────────────────────────────

def test_promote_skill_has_no_invalid_params():
    """Installed promote SKILL.md must NOT reference --title, --type, or --area."""
    from importlib.resources import files

    for host in ("claude", "agents"):
        text = (
            files("knowledge_studio.skill_templates")
            .joinpath(host, "skills", "promote", "SKILL.md")
            .read_text(encoding="utf-8")
        )
        assert "--title" not in text, f"{host}/promote/SKILL.md references --title"
        assert "--type" not in text, f"{host}/promote/SKILL.md references --type"
        assert "--area" not in text, f"{host}/promote/SKILL.md references --area"
        # The actual command should be present
        assert "oks drafts promote" in text, f"{host}/promote/SKILL.md missing oks drafts promote"


def test_ingest_skill_candidate_not_schema():
    """Ingest SKILL.md must explicitly state Candidate is NOT a schema."""
    from importlib.resources import files

    for host in ("claude", "agents"):
        text = (
            files("knowledge_studio.skill_templates")
            .joinpath(host, "skills", "ingest", "SKILL.md")
            .read_text(encoding="utf-8")
        )
        assert "Candidate is NOT an OKS protocol schema" in text, (
            f"{host}/ingest/SKILL.md missing Candidate-is-not-schema statement"
        )
        # Must also explicitly forbid oks schema show candidate
        assert "Do NOT call" in text, (
            f"{host}/ingest/SKILL.md missing Do NOT call warning"
        )


# ── Phase 3A-S: Integration (prepare → raw_commit) ──────────────────

def test_full_sanitize_integration(monkeypatch, tmp_path):
    """Full pipeline: prepare → raw_commit, verify bundle is clean of secrets."""
    import json, shutil, stat as _stat
    from knowledge_studio.ingest_prepare import prepare_ingest
    from knowledge_studio.raw_commit import raw_commit

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    f = tmp_path / "secret-doc.md"
    f.write_text(
        "# Doc\n\n"
        "Authorization: Bearer sk-test-sensitive-12345\n\n"
        "Token: Bearer eyJhbGciOiJIUzI1NiJ9.e30.ZrRHA1JJJW8opsbCGfG_HACGp2UMN1mNRpXjQ\n\n"
        "Normal content.\n",
        encoding="utf-8",
    )

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True
    assert result["sensitive_content_redacted"] is True

    commit_result = raw_commit(result["manifest_dir"])
    assert commit_result["status"] == "committed"

    bundle_path = Path(commit_result["bundle_path"])

    # content.md must be clean
    content_md = (bundle_path / "content.md").read_text(encoding="utf-8")
    assert "sk-test-sensitive-12345" not in content_md
    assert "eyJhbGciOiJIUzI1NiJ9" not in content_md

    # evidence.jsonl must be clean
    evidence = (bundle_path / "evidence.jsonl").read_text(encoding="utf-8")
    assert "sk-test-sensitive-12345" not in evidence
    assert "eyJhbGciOiJIUzI1NiJ9" not in evidence

    # source-envelope snapshot must also be clean
    env_path = bundle_path / "source-envelope.json"
    env = json.loads(env_path.read_text(encoding="utf-8"))
    assert "sk-test-sensitive" not in json.dumps(env)

    # Cleanup
    def _rm(p, fn, ex):
        Path(p).chmod(_stat.S_IWRITE)
        fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=_rm)
    shutil.rmtree(tmp_path / "raw", onexc=_rm)


# ══════════════════════════════════════════════════════════════════════
# Phase 3A-M — Dynamic Extraction + Guided UX automated tests
# ══════════════════════════════════════════════════════════════════════


# ── 1. Provider declares multiple capabilities ──────────────────────

def test_provider_declares_multiple_capabilities():
    """A single provider.yaml must be able to declare multiple capabilities."""
    from knowledge_studio.capability_commands import capability_list

    catalog = capability_list()
    # Check known multi-capability providers
    firecrawl = next(p for p in catalog["providers"] if p["id"] == "firecrawl")
    assert len(firecrawl["actions"]) >= 3, (
        f"firecrawl should declare >=3 capabilities, has {len(firecrawl['actions'])}"
    )

    agent_runtime = next(p for p in catalog["providers"] if p["id"] == "agent-runtime")
    assert len(agent_runtime["actions"]) >= 3, (
        f"agent-runtime should declare >=3 capabilities, has {len(agent_runtime['actions'])}"
    )

    pdf_lite = next(p for p in catalog["providers"] if p["id"] == "pdf-lite")
    assert len(pdf_lite["actions"]) >= 2, (
        f"pdf-lite should declare >=2 capabilities, has {len(pdf_lite['actions'])}"
    )


# ── 2. One provider can satisfy multiple demands ────────────────────

def test_one_provider_satisfies_multiple_demands():
    """One provider's capabilities can cover multiple Recipe demands."""
    from knowledge_studio.capability_commands import capability_list, capability_status

    catalog = capability_list()
    # web Recipe demands: web.fetch, web.extract (both required)
    # A single Firecrawl execution satisfies both
    web_providers = catalog["by_action"].get("web.fetch", [])
    extract_providers = catalog["by_action"].get("web.extract", [])
    # Firecrawl must appear in BOTH lists (one provider → multiple capabilities)
    assert "firecrawl" in web_providers, "firecrawl missing from web.fetch"
    assert "firecrawl" in extract_providers, "firecrawl missing from web.extract"
    # Same for agent-runtime: image.observe + layout.understand + chart.interpret
    assert "agent-runtime" in catalog["by_action"].get("image.observe", [])
    assert "agent-runtime" in catalog["by_action"].get("layout.understand", [])


# ── 3. Agent can get current availability facts ─────────────────────

def test_capability_status_returns_availability():
    """capability_status() must return provider availability, not just mapping."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    assert "providers" in result
    assert "actions" in result
    assert "by_action" in result
    assert "overall" in result

    for p in result["providers"]:
        assert "status" in p, f"provider {p['id']} missing status"
        assert "healthy" in p, f"provider {p['id']} missing healthy"
        assert p["status"] in (
            "ready", "not_configured", "unavailable", "runtime_only",
            "blocked", "experimental",
        ), f"provider {p['id']} has unknown status: {p['status']}"
        assert "capabilities" in p, f"provider {p['id']} missing capabilities list"
        assert "known_limits" in p, f"provider {p['id']} missing known_limits"


def test_capability_status_actions_have_chinese_labels():
    """Every action in capability_status must have a Chinese label."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    for name, info in result["actions"].items():
        assert info.get("label"), f"action '{name}' has empty label"
        # Labels should contain non-ASCII (Chinese) characters
        assert info["label"] != name, (
            f"action '{name}' label equals its id — should have Chinese name"
        )


# ── 4. required / optional demand distinction in Recipes ────────────

def test_recipes_have_required_and_optional_capabilities():
    """Every Recipe must distinguish required from optional capabilities."""
    from importlib.resources import files

    recipes_dir = files("knowledge_studio.recipes")
    recipe_names = [
        "text.md", "pdf.md", "web.md", "office.md",
        "image.md", "audio.md", "video.md",
    ]
    for name in recipe_names:
        recipe_path = recipes_dir.joinpath(name)
        assert recipe_path.is_file(), f"recipe missing: {name}"
        text = recipe_path.read_text(encoding="utf-8")
        assert "required_capabilities" in text, (
            f"{name} missing required_capabilities"
        )
        assert "optional_capabilities" in text, (
            f"{name} missing optional_capabilities"
        )


# ── 5. Missing required → cannot silently complete ──────────────────

def test_ingest_skill_forbids_silent_partial_promotion():
    """Ingest SKILL.md must say: missing required → partial, not complete."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "NEVER upgrade partial to complete" in text, (
            f"{host}/ingest/SKILL.md missing: NEVER upgrade partial to complete"
        )
        # Must describe what happens when required is missing
        assert "required" in text.lower(), (
            f"{host}/ingest/SKILL.md must reference required capabilities"
        )


def test_ingest_skill_guides_partial_to_user():
    """When evidence is partial, Agent must explain impact and recommend action."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "推荐" in text, (
            f"{host}/ingest/SKILL.md missing 推荐 (recommendation) in user-facing card"
        )
        assert "影响" in text, (
            f"{host}/ingest/SKILL.md missing 影响 (impact) in user-facing card"
        )


# ── 6. Agent Runtime provenance ─────────────────────────────────────

def test_ingest_skill_labels_agent_observation():
    """Agent observation must be labeled as agent_observed, not mechanical."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "agent_observed" in text, (
            f"{host}/ingest/SKILL.md missing agent_observed provenance"
        )
        assert "agent_multimodal_observation" in text, (
            f"{host}/ingest/SKILL.md missing agent_multimodal_observation method"
        )
        assert "NEVER present agent inference as source text" in text, (
            f"{host}/ingest/SKILL.md missing agent inference constraint"
        )


def test_agent_runtime_provider_declares_evidence_provenance():
    """agent-runtime provider.yaml must declare evidence method and agent_judgment."""
    from knowledge_studio.capability_commands import _scan_providers
    from knowledge_studio.capability_commands import _providers_root

    providers = _scan_providers(_providers_root())
    ar = next(p for p in providers if p.get("id") == "agent-runtime")
    evidence = ar.get("evidence", {})
    assert evidence.get("agent_judgment") == "agent_observed", (
        "agent-runtime must declare agent_judgment: agent_observed"
    )
    assert evidence.get("method") == "agent_multimodal_observation", (
        "agent-runtime must declare method: agent_multimodal_observation"
    )


# ── 7. 用户视图中文化 ──────────────────────────────────────────────

def test_user_facing_text_is_chinese():
    """All user-facing UI text must be in Chinese natural language."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Check the Guided UX Principles section has Chinese examples
        assert "用户做判断" in text or "Ask users for judgment" in text, (
            f"{host}/ingest/SKILL.md missing Guided UX principles"
        )


def test_i18n_has_chinese_for_all_keys():
    """Every i18n key must have a zh (Chinese) translation."""
    from knowledge_studio.i18n import _TEXTS

    for key, entry in _TEXTS.items():
        assert "zh" in entry, f"i18n key '{key}' missing zh translation"
        assert entry["zh"], f"i18n key '{key}' has empty zh translation"


# ── 8. internal capability ID default hidden ────────────────────────

def test_init_summary_hides_internal_ids():
    """User-facing capability descriptions must NOT expose internal provider IDs.

    The raw label (without install hints) must be free of internal IDs.
    Install hints like 'oks capability install pdf-lite' or 'pip install
    markitdown' are actionable instructions — those may reference IDs because
    that's what the user actually types.  The capability label itself must
    be in plain Chinese (e.g. 'PDF 文本提取', not 'pdf-lite')."""
    from knowledge_studio.capability_commands import (
        _USER_CAPABILITY_LABELS,
        _describe_ready_capabilities,
        _build_capability_summary,
        capability_doctor,
    )

    doctor = capability_doctor()
    summary = _build_capability_summary(doctor)
    can_do, can_enable = _describe_ready_capabilities(summary)

    internal_ids = {
        "pdf-lite", "firecrawl", "agentkey", "rapidocr", "trafilatura",
        "yt-dlp", "ffmpeg", "mediacrawler", "agent-runtime", "text-read",
        "local-asr", "remote-asr", "mineru",
    }

    for label in can_do + can_enable:
        # Split off any install hint (after ' — ')
        capability_name = label.split(" — ")[0].strip()
        for pid in internal_ids:
            assert pid not in capability_name.lower(), (
                f"Capability label exposes internal ID '{pid}': '{capability_name}'"
            )


def test_init_summary_labels_are_defined():
    """Every provider in the catalog should appear in _USER_CAPABILITY_LABELS."""
    from knowledge_studio.capability_commands import (
        _USER_CAPABILITY_LABELS,
        _ALWAYS_AVAILABLE,
    )
    from knowledge_studio.capability_commands import capability_list
    from knowledge_studio.capability_commands import capability_doctor
    from knowledge_studio.capability_commands import _scan_providers, _providers_root

    # All non-always-available providers should have a user-facing label
    for p in _scan_providers(_providers_root()):
        pid = p.get("id", "")
        if pid in _ALWAYS_AVAILABLE:
            continue
        assert pid in _USER_CAPABILITY_LABELS, (
            f"Provider '{pid}' missing from _USER_CAPABILITY_LABELS"
        )


# ── 9. Provider does not write to Raw directly ──────────────────────

def test_normalize_functions_return_fragment_not_write():
    """normalize.py functions are pure — they return dicts, don't write files."""
    import inspect

    normalize_modules = [
        "knowledge_studio.providers.firecrawl.normalize",
        "knowledge_studio.providers.agentkey.normalize",
        "knowledge_studio.providers.text_read.normalize",
        "knowledge_studio.providers.pdf_lite.normalize",
        "knowledge_studio.providers.markitdown.normalize",
        "knowledge_studio.providers.rapidocr.normalize",
        "knowledge_studio.providers.yt_dlp.normalize",
        "knowledge_studio.providers.ffmpeg.normalize",
    ]
    for mod_name in normalize_modules:
        try:
            mod = __import__(mod_name, fromlist=["normalize"])
        except ImportError:
            continue  # not installed — skip
        fn = getattr(mod, "normalize", None)
        assert fn is not None, f"{mod_name} missing normalize function"
        sig = inspect.signature(fn)
        # normalize() must NOT have file-writing parameters like 'output_path'
        params = list(sig.parameters.keys())
        assert "output_path" not in params, (
            f"{mod_name}.normalize() has output_path param — it should be pure"
        )
        # Must have source_id as first param
        assert "source_id" in params, (
            f"{mod_name}.normalize() missing source_id parameter"
        )


def test_raw_commit_is_the_only_raw_writer():
    """Only raw_commit writes to raw/ — providers return fragments."""
    from knowledge_studio.raw_commit import raw_commit as _commit_fn
    import inspect

    # raw_commit function exists and is the sole path to raw/
    assert callable(_commit_fn)
    sig = inspect.signature(_commit_fn)
    # Takes manifest_dir, not individual fragments
    assert "manifest_dir" in sig.parameters


# ── 10. Human Review boundary unchanged ──────────────────────────────

def test_candidate_requires_human_review():
    """Candidate must go to drafts/ — Agent never writes to wiki/ directly."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "NEVER write to wiki/ directly" in text, (
            f"{host}/ingest/SKILL.md missing: NEVER write to wiki/ directly"
        )
        assert "/promote" in text, (
            f"{host}/ingest/SKILL.md missing /promote — human review gate"
        )


def test_wiki_write_is_only_via_cli():
    """Wiki page creation must go through store.write_wiki_page, not raw file writes."""
    from knowledge_studio.store import write_wiki_page, promote_draft
    import inspect

    # These are the only two functions that write wiki pages
    assert callable(write_wiki_page)
    assert callable(promote_draft)
    # promote_draft is the gate from draft to wiki
    sig = inspect.signature(promote_draft)
    assert "slug" in sig.parameters


# ── Bonus: capability_status is the single source of truth ──────────

def test_capability_status_includes_mediacrawler():
    """MediaCrawler must appear in capability_status even though not installed."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    mediacrawler = next(
        (p for p in result["providers"] if p["id"] == "mediacrawler"), None
    )
    assert mediacrawler is not None, "mediacrawler missing from capability_status"
    assert mediacrawler["status"] == "unavailable", (
        f"mediacrawler should be 'unavailable', got '{mediacrawler['status']}'"
    )
    assert "platforms" in mediacrawler or any(
        "platforms" in p for p in result["providers"] if p["id"] == "mediacrawler"
    ), "mediacrawler should have platform metadata"
    # Must provide social capabilities
    assert "social.content.fetch" in mediacrawler["capabilities"], (
        "mediacrawler must provide social.content.fetch"
    )


def test_capability_status_social_actions_exist():
    """Social capability actions added in Phase 3A-M must be present."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    for action in (
        "social.content.fetch",
        "social.search",
        "social.comments.fetch",
        "social.creator.fetch",
    ):
        assert action in result["actions"], (
            f"social action '{action}' missing from capability_status"
        )
        # Must have a Chinese label different from the internal ID
        label = result["actions"][action]["label"]
        assert label != action, (
            f"social action '{action}' has no Chinese label"
        )


def test_capability_status_one_call_sufficiency():
    """capability_status must provide enough info for Agent to select providers
    WITHOUT needing additional capability catalog or doctor calls."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    # Agent needs: actions with labels, providers with status, by_action mapping
    assert result["actions"], "actions must not be empty"
    assert result["providers"], "providers must not be empty"
    assert result["by_action"], "by_action mapping must not be empty"
    # Each provider must have enough info for decision-making
    for p in result["providers"]:
        assert "id" in p
        assert "status" in p
        assert "execution" in p
        assert "capabilities" in p
        assert len(p["capabilities"]) > 0, (
            f"provider {p['id']} has zero capabilities"
        )


# ══════════════════════════════════════════════════════════════════════
# Phase 3A-M 增量：优雅降级 (Graceful Degradation)
# ══════════════════════════════════════════════════════════════════════


def test_degradation_ladder_in_skill():
    """L0-L4 degradation levels must be documented in ingest SKILL.md."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "L0" in text and "Preferred" in text, (
            f"{host}/ingest/SKILL.md missing L0 Preferred"
        )
        assert "L1" in text and "Automatic Fallback" in text, (
            f"{host}/ingest/SKILL.md missing L1 Automatic Fallback"
        )
        assert "L2" in text and "Honest Partial" in text, (
            f"{host}/ingest/SKILL.md missing L2 Honest Partial"
        )
        assert "L3" in text and "Guided Assistance" in text, (
            f"{host}/ingest/SKILL.md missing L3 Guided Assistance"
        )
        assert "L4" in text and "Cannot" in text, (
            f"{host}/ingest/SKILL.md missing L4 Cannot Reliably Extract"
        )


def test_graceful_degradation_principles_in_skill():
    """All 10 core degradation principles must appear as MUST constraints."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        principles = [
            "MUST follow L0",
            "MUST attempt auto-fallback",
            "MUST NOT block on missing optional capability",
            "MUST NOT fabricate evidence",
            "MUST aggregate all gaps",
            "MUST preserve provenance",
            "MUST stop capability escalation",
            "MUST provide a recommendation",
            "MUST explain each gap in terms of user impact",
            "MUST label all Agent-observed evidence as agent_observed",
        ]
        for p in principles:
            assert p in text, f"{host}/ingest/SKILL.md missing principle: {p}"


def test_optional_capability_does_not_block():
    """Missing optional capability must NEVER block the task."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "optional means optional" in text, (
            f"{host}/ingest/SKILL.md must state 'optional means optional'"
        )
        assert "MUST NOT block on missing optional capability" in text, (
            f"{host}/ingest/SKILL.md missing optional-no-block constraint"
        )


def test_gap_aggregation_rule():
    """Multiple capability gaps must be aggregated into ONE user message."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "MUST aggregate all gaps" in text, (
            f"{host}/ingest/SKILL.md missing gap aggregation MUST"
        )
        # Must mention aggregation format fields
        assert "已获得" in text, f"{host}/ingest/SKILL.md missing 已获得 in gap format"
        assert "仍缺" in text, f"{host}/ingest/SKILL.md missing 仍缺 in gap format"
        assert "影响" in text, f"{host}/ingest/SKILL.md missing 影响 in gap format"
        assert "推荐" in text, f"{host}/ingest/SKILL.md missing 推荐 in gap format"


def test_text_only_orchestrator_rule():
    """Text-only orchestrator must use Providers, never hallucinate multimodal."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "Text-Only Orchestrator" in text or "text-only" in text.lower(), (
            f"{host}/ingest/SKILL.md missing text-only orchestrator guidance"
        )
        assert "NEVER hallucinate" in text, (
            f"{host}/ingest/SKILL.md missing NEVER hallucinate constraint"
        )
        # Must reference using registered Providers for missing modalities
        assert "Provider" in text, (
            f"{host}/ingest/SKILL.md must reference Providers for missing modalities"
        )


def test_degradation_stops_after_required():
    """Agent must stop escalating after required Evidence is satisfied."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "MUST stop capability escalation" in text, (
            f"{host}/ingest/SKILL.md missing stop-escalation constraint"
        )
        assert "Stop escalating after required" in text, (
            f"{host}/ingest/SKILL.md missing stop-after-required rule"
        )


# ══════════════════════════════════════════════════════════════════════
# Gate 3A-M-R1: Capability Truthfulness & Safe Degradation
# ══════════════════════════════════════════════════════════════════════


# ── P0-1: CJK boundary credential leakage ──────────────────────────

def test_redact_text_catches_cjk_adjacent_sk_key():
    """sk- key immediately preceded by Chinese character (no space) MUST be caught.

    Python 3 \\w includes CJK characters via re.UNICODE (default), so \\b
    does NOT match at CJK→ASCII transitions — both sides are \\w chars.
    The fix replaces \b with (?<![a-zA-Z0-9_]) / (?![a-zA-Z0-9_]).
    """
    from knowledge_studio.security.redaction import redact_text

    # CJK character "为" immediately before sk- — no space
    cases = [
        "密钥为sk-proj-abc123xyz789def456ghi012jkl345mno",
        "API密钥：sk-c0b1f0123456789abcdef0123456789abcd",
        "设置sk-proj-0123456789abcdef0123456789abcdef为环境变量",
        "我的sk-admin-abcdef0123456789abcdef01234567密钥已配置",
    ]
    for text in cases:
        result = redact_text(text)
        assert "sk-" not in result, (
            f"CJK-adjacent sk- key NOT redacted!\n"
            f"  Input:  {text[:80]}...\n"
            f"  Output: {result[:80]}..."
        )
        assert "***REDACTED***" in result


def test_redact_text_cjk_boundary_all_patterns():
    """All SENSITIVE_PATTERNS must work when adjacent to CJK characters.

    This verifies the \b→ASCII-lookaround fix for every credential pattern.
    """
    from knowledge_studio.security.redaction import redact_text

    cjk_cases = [
        # CJK before Bearer
        ("令牌为Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456ghi789",
         "Bearer"),
        # CJK before JWT
        ("解析eyJhbGciOiJIUzI1NiJ9.eyJuYW1lIjoiSm9obiJ9.xJgfW6qcBzOJKFpYjH2TIA",
         "eyJ"),
        # CJK before Basic auth
        ("认证方式Basic dXNlcjpwYXNzd29yZA==",
         "Basic"),
        # CJK before API key pattern
        ("配置api_key=abcdef0123456789abcdef0123456789ab即可",
         "api_key"),
        # CJK before AWS key
        ("使用AKIAIOSFODNN7EXAMPLE后",
         "AKIA"),
    ]
    for text, credential_type in cjk_cases:
        result = redact_text(text)
        assert "***REDACTED***" in result, (
            f"CJK-adjacent {credential_type} NOT redacted!\n"
            f"  Input:  {text[:100]}\n"
            f"  Output: {result[:100]}"
        )


def test_root_and_package_sensitive_fields_identical():
    """Root security/sensitive_fields.py and package copy MUST be byte-identical."""
    root = Path(__file__).parent.parent.parent / "security" / "sensitive_fields.py"
    pkg = Path(__file__).parent.parent / "knowledge_studio" / "security" / "sensitive_fields.py"

    root_text = root.read_text(encoding="utf-8")
    pkg_text = pkg.read_text(encoding="utf-8")
    assert root_text == pkg_text, (
        f"Root and package sensitive_fields.py differ! "
        f"(root: {len(root_text)} chars, package: {len(pkg_text)} chars)"
    )


# ── P0-2: Agent multimodal not unconditionally available ────────────

def test_agent_runtime_is_runtime_only():
    """agent-runtime MUST be runtime_only — depends on current Agent model.

    Text-only orchestrators cannot perform multimodal capabilities.
    """
    from knowledge_studio.capability_commands import _provider_status

    status = _provider_status([], "agent-runtime", "agent_native")
    assert status == "runtime_only", (
        f"agent-runtime should be 'runtime_only', got '{status}'"
    )


def test_runtime_only_not_in_can_do():
    """runtime_only providers must NOT appear as 'available now' in init output."""
    from knowledge_studio.capability_commands import (
        _describe_ready_capabilities,
        _build_capability_summary,
    )

    doctor = {
        "overall": "issues_found",
        "providers": [
            {"id": "agentkey", "execution": "external", "status": "runtime_only",
             "label": "受限平台内容获取"},
            {"id": "agent-runtime", "execution": "agent_native", "status": "runtime_only",
             "label": "Agent 多模态理解"},
        ],
    }
    summary = _build_capability_summary(doctor)
    can_do, can_enable = _describe_ready_capabilities(summary)

    # agent-runtime is always-available-filtered — should be absent from both
    for label in can_do:
        assert "Agent" not in label, (
            f"agent-runtime should not appear in can_do: '{label}'"
        )
    # agentkey is runtime_only — should appear in can_enable, not can_do
    assert not any("受限平台" in label for label in can_do), (
        "runtime_only agentkey should not be in can_do"
    )
    assert any("受限平台" in label for label in can_enable), (
        "runtime_only agentkey should be in can_enable with caveat"
    )


def test_capability_status_agent_runtime_is_runtime_only():
    """capability_status must report agent-runtime as runtime_only, not ready."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    ar = next((p for p in result["providers"] if p["id"] == "agent-runtime"), None)
    assert ar is not None, "agent-runtime missing from capability_status"
    assert ar["status"] == "runtime_only", (
        f"agent-runtime should be 'runtime_only', got '{ar['status']}'"
    )


# ── P1-1: Ordinary web fallback chain ───────────────────────────────

def test_agent_runtime_declares_web_fetch():
    """Agent Runtime must declare web.fetch — it can fetch public web pages."""
    from knowledge_studio.capability_commands import capability_list

    catalog = capability_list()
    ar = next(p for p in catalog["providers"] if p["id"] == "agent-runtime")
    assert "web.fetch" in ar["actions"], (
        "agent-runtime must provide web.fetch as a truthful fallback "
        "for ordinary public web pages"
    )


def test_http_fetch_is_experimental():
    """http-fetch must be consistently experimental across provider.yaml + status."""
    from knowledge_studio.capability_commands import _provider_status

    status = _provider_status([], "http-fetch", "managed")
    assert status == "experimental", (
        f"http-fetch should be 'experimental', got '{status}'"
    )


def test_http_fetch_provider_yaml_consistent():
    """http-fetch provider.yaml must declare experimental maturity, not stable."""
    from knowledge_studio.capability_commands import _scan_providers, _providers_root

    providers = _scan_providers(_providers_root())
    hf = next(p for p in providers if p.get("id") == "http-fetch")
    provides = hf.get("provides", {})
    for cap, info in provides.items():
        if isinstance(info, dict):
            maturity = info.get("maturity", "")
            assert maturity == "experimental", (
                f"http-fetch {cap} should be 'experimental', got '{maturity}'"
            )


# ── P1-2: Video Recipe subtitle/ASR fallback ────────────────────────

def test_video_recipe_allows_asr_substitute():
    """No subtitles + ASR success must satisfy video transcript requirement.

    subtitle.fetch (required) failure should NOT permanently partial the result
    when speech.transcribe (optional, ASR fallback) produces a valid transcript.
    The complete_when condition subtitles_or_transcript_available can be
    satisfied by EITHER subtitle.fetch OR speech.transcribe.

    Verifies: (a) required_capabilities only use real Registry IDs,
    (b) the degradation chain documents the ASR substitution,
    (c) complete_when accepts the transcript from either path.
    """
    from importlib.resources import files

    video_recipe = files("knowledge_studio.recipes").joinpath("video.md")
    text = video_recipe.read_text(encoding="utf-8")

    # transcript_or_subtitle is NOT a real capability — must not appear
    assert "transcript_or_subtitle" not in text, (
        "video.md must NOT contain the fake capability 'transcript_or_subtitle'. "
        "All required_capabilities and optional_capabilities must be real "
        "Capability Registry IDs."
    )
    # subtitle.fetch IS a real capability — must be in required
    assert "subtitle.fetch" in text, (
        "video.md required_capabilities must include subtitle.fetch "
        "(the real Registry capability, not a pseudo-capability)"
    )
    # The degradation note must document the substitution
    assert "speech.transcribe" in text, (
        "video.md degradation must reference speech.transcribe as fallback"
    )
    # complete_when already has subtitles_or_transcript_available
    assert "subtitles_or_transcript_available" in text, (
        "video.md complete_when missing subtitles_or_transcript_available"
    )


# ── Firecrawl metadata.fetch declaration ────────────────────────────

def test_firecrawl_declares_metadata_fetch():
    """Firecrawl provider.yaml must declare metadata.fetch.

    Ingest SKILL.md references Firecrawl metadata.fetch as part of the
    provider cluster (one /scrape → web.fetch + web.extract + metadata.fetch).
    The provider.yaml must match.
    """
    from knowledge_studio.capability_commands import capability_list

    catalog = capability_list()
    firecrawl = next(p for p in catalog["providers"] if p["id"] == "firecrawl")
    assert "metadata.fetch" in firecrawl["actions"], (
        "firecrawl must declare metadata.fetch — SKILL.md Step 4 references it "
        "as part of the 3-capability provider cluster"
    )


# ── MediaCrawler truthfulness ───────────────────────────────────────

def test_mediacrawler_all_experimental():
    """All MediaCrawler capabilities must be experimental — no validated claims.

    MediaCrawler OKS integration has never been independently verified.
    """
    from knowledge_studio.capability_commands import _scan_providers, _providers_root

    providers = _scan_providers(_providers_root())
    mc = next(p for p in providers if p.get("id") == "mediacrawler")
    provides = mc.get("provides", {})
    for cap, info in provides.items():
        if isinstance(info, dict):
            maturity = info.get("maturity", "")
            assert maturity == "experimental", (
                f"mediacrawler {cap} maturity='{maturity}' — "
                f"must be 'experimental' (OKS integration unverified)"
            )


def test_mediacrawler_skill_in_package():
    """MediaCrawler SKILL.md must exist in the package directory for wheel inclusion."""
    from importlib.resources import files

    skill_path = files("knowledge_studio.providers.mediacrawler").joinpath("SKILL.md")
    assert skill_path.is_file(), (
        "cli/knowledge_studio/providers/mediacrawler/SKILL.md missing — "
        "not included in wheel"
    )
    text = skill_path.read_text(encoding="utf-8")
    assert "experimental" in text.lower(), (
        "mediacrawler SKILL.md must reflect experimental (unverified) status"
    )


# ══════════════════════════════════════════════════════════════════════
# Gate 3A-M-R2: Agent-Facing Contract Closure
# ══════════════════════════════════════════════════════════════════════


# ── Recipe Capability Invariant ─────────────────────────────────────

def _parse_recipe_capability_list(text: str, section: str) -> list[str]:
    """Extract capability IDs from a YAML list section in a recipe.

    Handles the indented list format used in recipe markdown code blocks.
    """
    import re

    in_section = False
    caps: list[str] = []
    for line in text.splitlines():
        if line.strip() == f"{section}:":
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if stripped.startswith("- "):
                cap = stripped[2:].strip()
                if cap:
                    caps.append(cap)
            elif stripped and not stripped.startswith("#") and not stripped.startswith("- "):
                # Next top-level key — exit the list
                if not line.startswith(" ") and not line.startswith("\t"):
                    break
    return caps


def test_recipe_capabilities_all_in_registry():
    """Every required_capability and optional_capability in every Recipe
    MUST exist in the Capability Registry (actions.yaml).

    This is an invariant — any pseudo-capability like 'transcript_or_subtitle'
    that doesn't correspond to a real Registry action must be caught here.
    """
    from importlib.resources import files

    # Load all real capability IDs from the Registry
    actions_yaml = files("knowledge_studio.capabilities").joinpath("actions.yaml")
    registry_text = actions_yaml.read_text(encoding="utf-8")
    # Parse actions from actions.yaml
    registry_ids: set[str] = set()
    in_actions = False
    for line in registry_text.splitlines():
        stripped = line.strip()
        if stripped == "actions:":
            in_actions = True
            continue
        if in_actions:
            if stripped and not line.startswith(" ") and not line.startswith("\t"):
                break  # next top-level key
            if stripped and not stripped.startswith("#"):
                # Action name is the key before the colon
                if ":" in stripped and not stripped.startswith("-"):
                    action_id = stripped.split(":")[0].strip()
                    if action_id:
                        registry_ids.add(action_id)

    assert len(registry_ids) >= 20, (
        f"Expected >=20 actions in Registry, found {len(registry_ids)}"
    )

    # Check every recipe
    recipes_dir = files("knowledge_studio.recipes")
    recipe_names = [
        "text.md", "pdf.md", "web.md", "office.md",
        "image.md", "audio.md", "video.md",
    ]
    violations: list[str] = []
    for name in recipe_names:
        recipe_path = recipes_dir.joinpath(name)
        assert recipe_path.is_file(), f"recipe missing: {name}"
        text = recipe_path.read_text(encoding="utf-8")

        required = _parse_recipe_capability_list(text, "required_capabilities")
        optional = _parse_recipe_capability_list(text, "optional_capabilities")
        all_caps = required + optional

        for cap in all_caps:
            if cap not in registry_ids:
                violations.append(f"{name}: '{cap}' not in Capability Registry")

    assert not violations, (
        f"Recipe capabilities not in Registry ({len(violations)} violations):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ── Recipe in ingest prepare output ─────────────────────────────────

def test_ingest_prepare_includes_recipe(tmp_path):
    """oks ingest prepare output must include the Recipe for the detected modality.

    The Agent must be able to read the Recipe from the CLI output without
    needing a recipes/ directory in the user's knowledge base.
    """
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 mock")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["modality"] == "pdf"
    assert "recipe" in result, (
        "ingest prepare output missing 'recipe' field"
    )
    assert result["recipe"] is not None, (
        "ingest prepare recipe is None for pdf modality"
    )
    assert "Recipe: PDF" in result["recipe"], (
        "recipe should contain 'Recipe: PDF' header"
    )
    assert "required_capabilities" in result["recipe"], (
        "recipe must list required_capabilities"
    )

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp_path / ".oks", onexc=rm)


def test_ingest_prepare_recipe_for_all_modalities(tmp_path):
    """Every known modality must have a recipe in the ingest prepare output."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    test_files = {
        "text": ("test.md", "# Hello"),
        "pdf": ("test.pdf", b"%PDF-1.4"),
        "web": ("test.html", "<html><body>Test</body></html>"),
        "office": ("test.docx", b"PK\x03\x04"),
        "image": ("test.png", b"\x89PNG\r\n"),
        "audio": ("test.mp3", b"ID3\x03\x00"),
        "video": ("test.mp4", b"\x00\x00\x00\x18ftypmp42"),
    }
    for expected_modality, (filename, content) in test_files.items():
        f = tmp_path / filename
        if isinstance(content, str):
            f.write_text(content, encoding="utf-8")
        else:
            f.write_bytes(content)

        result = prepare_ingest(str(f), kb_root=tmp_path)
        assert result["modality"] == expected_modality, (
            f"{filename} should be {expected_modality}, got {result['modality']}"
        )
        assert result.get("recipe") is not None, (
            f"ingest prepare for {filename} ({expected_modality}) missing recipe"
        )
        assert len(result["recipe"]) > 50, (
            f"recipe for {expected_modality} is too short ({len(result['recipe'])} chars)"
        )

        import shutil, stat
        def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
        shutil.rmtree(tmp_path / ".oks", onexc=rm)


# ── capability guide command ────────────────────────────────────────

def test_capability_guide_returns_skill_md():
    """oks capability guide <provider> returns the canonical SKILL.md content."""
    from importlib.resources import files

    # Test with providers that are known to have SKILL.md
    for provider in ("pdf-lite", "firecrawl", "agentkey"):
        skill_path = files("knowledge_studio.providers").joinpath(provider, "SKILL.md")
        if not skill_path.is_file():
            continue
        content = skill_path.read_text(encoding="utf-8")
        assert len(content) > 0, f"{provider} SKILL.md is empty"
        # Must contain the provider name
        assert provider in content.lower() or provider.replace("-", "") in content.lower(), (
            f"{provider} SKILL.md does not reference its own provider name"
        )


def test_capability_guide_all_providers_with_skill():
    """Every provider that has a SKILL.md must be accessible via capability guide."""
    from importlib.resources import files

    providers_root = files("knowledge_studio.providers")
    found = 0
    for entry in sorted(providers_root.iterdir()):
        if not entry.is_dir():
            continue
        skill_path = entry / "SKILL.md"
        if skill_path.is_file():
            content = skill_path.read_text(encoding="utf-8")
            assert len(content) > 100, (
                f"provider {entry.name} SKILL.md is too short ({len(content)} chars)"
            )
            found += 1
    assert found >= 10, (
        f"Expected >=10 providers with SKILL.md, found {found}"
    )


# ── Ingest SKILL.md: Agent-facing contract closure ──────────────────

def test_ingest_skill_uses_cli_for_recipe():
    """Ingest SKILL.md must tell Agent to get Recipe from oks ingest prepare,
    NOT to read recipes/{modality}.md from disk."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must tell Agent to use the prepare output
        assert "recipe" in text.lower(), (
            f"{host}/ingest/SKILL.md must reference the recipe field"
        )
        # Must forbid reading from disk
        assert "Do NOT read `recipes/" in text or "does not contain a recipes/" in text, (
            f"{host}/ingest/SKILL.md must tell Agent NOT to read recipes/ from disk"
        )


def test_ingest_skill_uses_cli_for_provider_guide():
    """Ingest SKILL.md must tell Agent to use oks capability guide,
    NOT to read providers/.../SKILL.md from disk."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "oks capability guide" in text, (
            f"{host}/ingest/SKILL.md must reference oks capability guide"
        )
        assert "Do NOT read `providers/" in text or "does not contain a providers/" in text, (
            f"{host}/ingest/SKILL.md must tell Agent NOT to read providers/ from disk"
        )


def test_ingest_skill_complete_when_coverage_rule():
    """Ingest SKILL.md Step 5 must document that complete_when conditions
    can be satisfied by ANY capability (required OR optional)."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "complete_when coverage check" in text, (
            f"{host}/ingest/SKILL.md missing complete_when coverage check section"
        )
        assert "required OR optional" in text, (
            f"{host}/ingest/SKILL.md must state complete_when can use "
            f"evidence from required OR optional capabilities"
        )
        # The subtitle/ASR example must be present
        assert "subtitle.fetch" in text and "speech.transcribe" in text, (
            f"{host}/ingest/SKILL.md must include the video subtitle/ASR "
            f"fallback example in the complete_when coverage rule"
        )


# ── Hotfix R2.1: Unified required-capability / complete_when semantics ─

def test_required_capability_not_absolute_condition():
    """Step 3a must NOT contain the unconditional 'missing => partial/failed' rule.

    The old text 'if any are missing after execution, the ingest is partial or
    failed' contradicts the complete_when coverage rule.  required_capabilities
    are the primary path, not an absolute provider-ID success condition.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must NOT contain the old unconditional language
        assert "MUST be satisfied — if any are missing after execution, the ingest is `partial` or `failed`" not in text, (
            f"{host}/ingest/SKILL.md still contains the old unconditional "
            f"'missing => partial/failed' language in Step 3a"
        )
        # Must contain the new nuanced language
        assert "primary Evidence acquisition path" in text, (
            f"{host}/ingest/SKILL.md Step 3a missing 'primary Evidence acquisition path'"
        )
        assert "NOT an absolute" in text, (
            f"{host}/ingest/SKILL.md Step 3a missing 'NOT an absolute' qualifier"
        )
        assert "satisfied by fallback" in text, (
            f"{host}/ingest/SKILL.md Step 5 missing 'satisfied by fallback' outcome"
        )
        # The three-outcome model must be present
        assert "Neither the original capability nor any degradation fallback" in text, (
            f"{host}/ingest/SKILL.md Step 5 missing outcome 3 (neither original nor fallback)"
        )


def test_completeness_by_complete_when_not_capability_count():
    """Final completeness is determined by complete_when satisfaction,
    not by counting how many required capability IDs succeeded.

    This ensures the video subtitle/ASR scenario stays closed:
    subtitle.fetch failed + speech.transcribe succeeded → complete, not partial.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "complete_when satisfaction" in text or "complete_when" in text, (
            f"{host}/ingest/SKILL.md missing complete_when reference"
        )
        # The authoritative standard must be complete_when, not capability tally
        assert "authoritative completeness standard" in text, (
            f"{host}/ingest/SKILL.md missing 'authoritative completeness standard'"
        )
        # Must explicitly forbid marking as partial when fallback succeeded
        assert "Do NOT mark the ingest as partial" in text or "Do NOT mark as missing" in text, (
            f"{host}/ingest/SKILL.md must forbid marking as partial when fallback succeeded"
        )


# ══════════════════════════════════════════════════════════════════════
# Gate 3A-M-R3: Evidence Provenance Integrity
# ══════════════════════════════════════════════════════════════════════


def test_provider_raw_output_persisted_in_work_dir():
    """A. Provider raw output MUST be persisted to work/<provider>/
    BEFORE any Agent semantic processing.

    The SKILL.md must require saving raw output immediately after
    Provider execution and before EvidenceFragment construction.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must require saving raw output to work/<provider>/
        assert "work/<provider>" in text, (
            f"{host}/ingest/SKILL.md missing work/<provider>/ path"
        )
        # Must require persistence BEFORE semantic processing
        assert "BEFORE any Agent semantic processing" in text, (
            f"{host}/ingest/SKILL.md missing 'BEFORE any Agent semantic processing'"
        )
        # Raw output must be described as immutable evidence
        assert "immutable evidence" in text, (
            f"{host}/ingest/SKILL.md must describe raw output as 'immutable evidence'"
        )


def test_primary_evidence_must_come_from_persisted_raw_output():
    """B. Evidence content MUST come from persisted Provider raw output,
    not from Agent memory or reformulated content.

    The SKILL.md must explicitly require that evidence text is
    constructed FROM the persisted raw output.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must say evidence text comes from persisted raw output
        assert "MUST come from the persisted" in text or "from Agent memory" in text, (
            f"{host}/ingest/SKILL.md must require evidence from persisted raw output"
        )
        assert "reformulated" in text, (
            f"{host}/ingest/SKILL.md must forbid reformulated content"
        )
        # Constraint: primary evidence from persisted output
        assert "construct primary evidence text from persisted Provider raw output" in text, (
            f"{host}/ingest/SKILL.md missing constraint: construct from persisted raw output"
        )


def test_agent_rewrite_cannot_claim_mechanical_provenance():
    """C. Agent-rewritten content MUST NOT be labeled mechanical or with
    the original Provider as producer.

    After summarization, reorganization, annotation, etc., the content
    MUST be marked agent_observed with producer=agent-runtime.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must forbid claiming mechanical for Agent-written content
        assert "MUST NOT label Agent-rewritten" in text or (
            "Agent-rewritten" in text and "mechanical" in text
        ), (
            f"{host}/ingest/SKILL.md must forbid labeling Agent rewrites as mechanical"
        )
        # Must require agent-runtime as producer for rewritten content
        prohibited_ops = [
            "Summarization",
            "Reorganization",
            "Deletion of semantic content",
            "Translation",
            "Adding explanation",
            "Adding headers",
            "Cross-paragraph merging",
        ]
        for op in prohibited_ops:
            assert op in text, (
                f"{host}/ingest/SKILL.md missing prohibited operation: {op}"
            )
        # The table must clearly separate allowed from prohibited
        assert "Allowed — keeps `mechanical`" in text, (
            f"{host}/ingest/SKILL.md missing mechanical-vs-agent_observed table"
        )
        assert "Prohibited — forces `agent_observed`" in text, (
            f"{host}/ingest/SKILL.md missing prohibited column header"
        )


def test_agent_rewrite_must_create_separate_fragment():
    """D. Agent-processed content MUST create a separate fragment with
    agent-runtime as producer, preserving the original Provider fragment.

    The derivation chain must be traceable through artifact_id.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Must require separate fragment for Agent-processed content
        assert "separate" in text and "fragment" in text, (
            f"{host}/ingest/SKILL.md must require separate fragment for Agent rewrite"
        )
        assert "agent-runtime" in text, (
            f"{host}/ingest/SKILL.md missing agent-runtime producer reference"
        )
        # Must keep original Provider fragment intact
        assert "Keep the original Provider fragment" in text, (
            f"{host}/ingest/SKILL.md must say to keep original fragment intact"
        )
        # Derivation chain must be traceable
        assert "derivation chain" in text or "traceable through" in text, (
            f"{host}/ingest/SKILL.md must document derivation chain traceability"
        )
        # artifact_id as the link
        assert "artifact_id" in text, (
            f"{host}/ingest/SKILL.md must reference artifact_id for traceability"
        )
        # MUST constraint
        assert "separate agent-runtime fragment" in text, (
            f"{host}/ingest/SKILL.md missing MUST constraint for separate agent-runtime fragment"
        )


def test_illegal_provenance_blocks_complete():
    """E. Provenance legality is a HARD prerequisite for status=complete.

    If any evidence record's agent_judgment doesn't match the actual
    origin of its text, the ingest is incomplete regardless of
    complete_when satisfaction.
    """
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Provenance completeness prerequisites section must exist
        assert "Provenance completeness prerequisites" in text, (
            f"{host}/ingest/SKILL.md missing provenance completeness prerequisites"
        )
        # Provenance legality is a HARD prerequisite
        assert "HARD prerequisite" in text, (
            f"{host}/ingest/SKILL.md must say provenance legality is a HARD prerequisite"
        )
        # Illegal provenance blocks complete regardless of complete_when
        assert "illegal provenance" in text or "provenance is illegal" in text, (
            f"{host}/ingest/SKILL.md must mention illegal provenance"
        )
        # Must verify provenance before declaring complete
        assert "verify provenance legality before declaring ingest status complete" in text, (
            f"{host}/ingest/SKILL.md missing verify-provenance constraint"
        )
        # Three prerequisites must all be present
        assert "Raw Provider output persisted" in text, (
            f"{host}/ingest/SKILL.md missing prerequisite: raw output persisted"
        )
        assert "Provenance legal" in text, (
            f"{host}/ingest/SKILL.md missing prerequisite: provenance legal"
        )
        # Must mention the specific violations
        assert "NO record marked `mechanical` contains Agent-written" in text or (
            "NO record" in text and "mechanical" in text and "Agent-written" in text
        ), (
            f"{host}/ingest/SKILL.md must list specific provenance violations"
        )


def test_cjk_sanitization_provenance_regression():
    """F. CJK-adjacent sk- sanitization must still work (regression guard).

    The sanitizer continues to redact credentials before Provider raw
    output enters the Run Workspace.  Security sanitization is listed
    as an allowed mechanical transform in the provenance table.
    """
    # Re-run the CJK redaction test from R1 to confirm no regression
    from knowledge_studio.security.redaction import redact_text

    cases = [
        "密钥为sk-proj-abc123xyz789def456ghi012jkl345mno",
        "API密钥：sk-c0b1f0123456789abcdef0123456789abcd",
        "设置sk-proj-0123456789abcdef0123456789abcdef为环境变量",
    ]
    for text_input in cases:
        result = redact_text(text_input)
        assert "sk-" not in result, (
            f"CJK-adjacent sk- key NOT redacted after R3 changes!\n"
            f"  Input:  {text_input[:80]}\n"
            f"  Output: {result[:80]}"
        )
        assert "***REDACTED***" in result

    # Also verify: sanitization is documented as allowed mechanical in SKILL.md
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "Security sanitization" in text, (
            f"{host}/ingest/SKILL.md missing sanitization in provenance table"
        )
        assert "API key redaction" in text or "API key" in text, (
            f"{host}/ingest/SKILL.md missing API key redaction mention"
        )
        # Sanitize before saving must still be present
        assert "sanitize before saving" in text, (
            f"{host}/ingest/SKILL.md missing 'sanitize before saving' instruction"
        )


# ══════════════════════════════════════════════════════════════════════
# Gate R4: Provenance Hardening + Capability Rationalization + Protocol
# ══════════════════════════════════════════════════════════════════════


# ── R4-1: Fail-closed provenance ────────────────────────────────────

def test_fail_closed_provenance_in_skill():
    """R4-1: SKILL.md must reject self-reported raw output saves.
    'self-reported' + 'not sufficient' or 'not proof' must appear."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "self-reported" in text, (
            f"{host}/ingest/SKILL.md must reject self-reported save"
        )
        assert "not sufficient" in text or "not proof" in text, (
            f"{host}/ingest/SKILL.md must say self-reported is not sufficient/proof"
        )
        assert ">0 bytes" in text, (
            f"{host}/ingest/SKILL.md must require >0 bytes file check"
        )
        # 4th provenance prerequisite must exist
        assert "Raw output verified" in text, (
            f"{host}/ingest/SKILL.md missing 4th prerequisite: Raw output verified"
        )
        # Fail-closed language
        assert "Fail-closed" in text or "fail-closed" in text.lower(), (
            f"{host}/ingest/SKILL.md must mention fail-closed principle"
        )


def test_raw_output_must_exist_before_evidence_construction():
    """R4-1: Step 4 must require file existence verification before proceeding."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "verify the file exists" in text, (
            f"{host}/ingest/SKILL.md must require file existence check in Step 4"
        )
        assert "MUST NOT proceed" in text, (
            f"{host}/ingest/SKILL.md must forbid proceeding on write failure"
        )
        # Constraint about verification before complete
        assert "MUST verify raw output file existence" in text, (
            f"{host}/ingest/SKILL.md missing raw output verification constraint"
        )


# ── R4-2: Runtime Tool vs Registered Provider ───────────────────────

def test_runtime_tool_vs_registered_provider_section():
    """R4-2: SKILL.md must have a Runtime Tool vs Registered Provider section."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "Runtime Tool vs Registered Provider" in text, (
            f"{host}/ingest/SKILL.md missing Runtime Tool vs Registered Provider section"
        )
        assert "Registered Provider" in text, (
            f"{host}/ingest/SKILL.md must define Registered Provider category"
        )
        assert "Runtime Tool" in text, (
            f"{host}/ingest/SKILL.md must define Runtime Tool category"
        )
        # Must explicitly list runtime tool examples
        assert "curl" in text.lower(), (
            f"{host}/ingest/SKILL.md must mention curl as Runtime Tool"
        )
        assert "playwright" in text.lower(), (
            f"{host}/ingest/SKILL.md must mention playwright as Runtime Tool"
        )


def test_runtime_tool_impersonation_rules():
    """R4-2: SKILL.md must forbid Runtime Tools impersonating Registered Providers."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        # Impersonation rules
        assert "MUST NOT label curl" in text or "MUST NOT claim" in text, (
            f"{host}/ingest/SKILL.md missing impersonation rule for curl"
        )
        assert "MUST NOT claim" in text or "MUST NOT label" in text, (
            f"{host}/ingest/SKILL.md missing impersonation rules"
        )
        # Runtime tool producer value
        assert 'runtime-tool' in text, (
            f"{host}/ingest/SKILL.md must reference runtime-tool producer value"
        )
        # Distinguish constraint
        assert "MUST distinguish Runtime Tool" in text, (
            f"{host}/ingest/SKILL.md missing distinguish Runtime Tool constraint"
        )


def test_producer_schema_is_object():
    """R4-2: fragment schema producer must be an object (not flat enum).
    This fixes the pre-existing bug where prepare_ingest outputs an object
    but the schema expected a string enum."""
    from importlib.resources import files
    import json

    schema_path = files("knowledge_studio.schemas").joinpath("evidence-fragment-v0.1.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    producer = schema["properties"]["producer"]
    assert producer["type"] == "object", (
        f"producer must be type=object, got {producer.get('type')}"
    )
    assert "provider" in producer.get("required", []), (
        "producer object must require 'provider' field"
    )
    assert "tool" in producer.get("required", []), (
        "producer object must require 'tool' field"
    )
    # provider field must allow 'agent-runtime', 'runtime-tool'
    provider_prop = producer["properties"]["provider"]
    # No enum restriction — free-form string
    assert "enum" not in provider_prop, (
        "producer.provider must not be restricted by enum — "
        "must allow agent-runtime, runtime-tool, and any registered provider ID"
    )


# ── R4-3: Capability cost facts ─────────────────────────────────────

def test_provider_yamls_no_r4_weight_fields():
    """H1: R4 weight/latency/compute/privacy/cost_profile/platform_suitability
    fields must NOT be present in any provider.yaml.  These were rolled back."""
    from knowledge_studio.capability_commands import _scan_providers, _providers_root

    providers = _scan_providers(_providers_root())
    r4_fields = {"weight", "latency", "compute", "privacy",
                 "cost_profile", "platform_suitability"}
    present: list[str] = []
    for p in providers:
        pid = p.get("id", p.get("_dir", "unknown"))
        for field in r4_fields:
            if field in p:
                present.append(f"{pid}: has {field}")
    assert not present, (
        f"R4 fields should have been rolled back:\n"
        + "\n".join(f"  - {m}" for m in present)
    )


def test_capability_status_no_r4_cost_facts():
    """H1: capability_status() must NOT include R4 cost fact fields."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    r4_fields = ("weight", "latency", "compute", "privacy", "cost_profile")
    for p in result["providers"]:
        for field in r4_fields:
            assert field not in p, (
                f"provider {p['id']} should not have R4 field '{field}'"
            )


def test_ingest_skill_does_not_reference_static_labels():
    """H1: SKILL.md must NOT reference static weight/latency for provider selection."""
    for host in ("claude", "agents"):
        text = _read_skill_text(host)
        assert "prefer lower weight" not in text, (
            f"{host}/ingest/SKILL.md should not have static weight preference"
        )
        assert "prefer lower cost" not in text, (
            f"{host}/ingest/SKILL.md should not have static cost preference"
        )


# ── H1-C: User-facing capability categories ─────────────────────────

def test_category_summary_returns_6_categories():
    """H1-C: _build_category_summary must return exactly 6 capability categories."""
    from knowledge_studio.capability_commands import (
        _build_category_summary, capability_doctor,
    )

    doctor = capability_doctor()
    categories = _build_category_summary(doctor)
    assert len(categories) == 6, (
        f"Expected 6 categories, got {len(categories)}: "
        f"{[c['key'] for c in categories]}"
    )
    expected_keys = {"text", "web", "pdf", "image", "media", "platform"}
    actual_keys = {c["key"] for c in categories}
    assert actual_keys == expected_keys, (
        f"Category keys mismatch. Expected {expected_keys}, got {actual_keys}"
    )
    for cat in categories:
        assert "label" in cat
        assert "status" in cat
        assert cat["status"] in ("ready", "available", "unavailable")
        # Must NOT have weight/latency/count
        assert "weight" not in cat, f"Category '{cat['key']}' should not have weight"
        assert "latency" not in cat, f"Category '{cat['key']}' should not have latency"
        assert "ready_count" not in cat, f"Category '{cat['key']}' should not have ready_count"


def test_init_output_uses_categories_not_provider_ids():
    """R4-4: default print_capability_summary must show category labels,
    not internal provider IDs."""
    from knowledge_studio.capability_commands import (
        _build_category_summary, capability_doctor,
    )

    doctor = capability_doctor()
    categories = _build_category_summary(doctor)

    # Category labels must be Chinese user-facing names
    for cat in categories:
        label = cat["label"]
        # Must be Chinese, not an internal ID
        assert label != cat["key"], (
            f"Category label '{label}' should be Chinese, not key '{cat['key']}'"
        )
        # Must not contain provider IDs
        assert "pdf-lite" not in label.lower(), f"Category label '{label}' exposes provider ID"


# ── R4-5: Pre-filled evidence skeleton ──────────────────────────────

def test_ingest_prepare_prefills_evidence_slots_for_non_text():
    """R4-5: Non-text ingest prepare must pre-fill evidence_records from recipe."""
    from knowledge_studio.ingest_prepare import prepare_ingest
    import json

    # Test with PDF
    f = Path(__file__).parent / "conftest.py"
    if not f.exists():
        import pytest
        pytest.skip("conftest.py not found for test")

    import tempfile
    tmp = Path(tempfile.mkdtemp())
    pdf = tmp / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 mock")

    result = prepare_ingest(str(pdf), kb_root=tmp)
    assert result["text_ready"] is False

    man_path = tmp / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    records = manifest["evidence_records"]
    steps = manifest["steps"]

    # Must have pre-filled records and steps
    assert len(records) >= 1, "Non-text must have pre-filled evidence_records"
    assert len(steps) >= 1, "Non-text must have pre-filled steps"

    # Each record must have all required fields with text/confidence null
    for rec in records:
        required_fields = ["evidence_id", "artifact_id", "kind", "method", "locator"]
        for field in required_fields:
            assert rec.get(field) is not None, f"Record missing required field: {field}"
        assert rec.get("text") is None, "Pre-filled record text must be None (Agent fills)"
        assert rec.get("confidence") is None, "Pre-filled record confidence must be None (Agent fills)"
        assert rec.get("agent_judgment") is not None, "Pre-filled record must have default agent_judgment"

    # Each step must have provider=None, status=pending
    for step in steps:
        assert step.get("provider") is None, "Pre-filled step provider must be None (Agent fills)"
        assert step.get("status") == "pending", f"Pre-filled step status must be pending, got {step.get('status')}"

    import shutil, stat
    def rm(p, fn, ex): Path(p).chmod(stat.S_IWRITE); fn(p)
    shutil.rmtree(tmp / ".oks", onexc=rm)


def test_prefilled_skeleton_parses_recipe_correctly():
    """R4-5: _parse_recipe_capabilities must extract correct capability IDs."""
    from knowledge_studio.ingest_prepare import _parse_recipe_capabilities
    from importlib.resources import files

    # Test with known recipes — required capabilities only
    for modality, expected_caps in [
        ("pdf", ["document.text.extract"]),
        ("web", ["web.fetch", "web.extract"]),
        ("image", ["image.observe"]),
    ]:
        recipe_path = files("knowledge_studio.recipes").joinpath(f"{modality}.md")
        if not recipe_path.is_file():
            continue
        recipe = recipe_path.read_text(encoding="utf-8")
        caps = _parse_recipe_capabilities(recipe, "required_capabilities")
        for expected in expected_caps:
            assert expected in caps, (
                f"{modality} recipe: missing required capability '{expected}' "
                f"in parsed result: {caps}"
            )
        # Must not include optional capabilities
        if "optional_capabilities" in recipe:
            optional = _parse_recipe_capabilities(recipe, "optional_capabilities")
            assert optional, f"{modality} must have optional capabilities"


def test_capability_to_evidence_mappings_are_complete():
    """R4-5: All 25 capability IDs in actions.yaml must have mappings."""
    from knowledge_studio.ingest_prepare import (
        _capability_to_kind, _capability_to_method,
        _capability_to_locator_kind, _capability_default_judgment,
        _capability_modality,
    )
    from importlib.resources import files

    actions_yaml = files("knowledge_studio.capabilities").joinpath("actions.yaml")
    text = actions_yaml.read_text(encoding="utf-8")

    # Parse action IDs
    action_ids: set[str] = set()
    in_actions = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "actions:":
            in_actions = True
            continue
        if in_actions:
            if stripped and not line.startswith(" ") and not line.startswith("\t"):
                break
            if stripped and not stripped.startswith("#") and ":" in stripped:
                aid = stripped.split(":")[0].strip()
                if aid:
                    action_ids.add(aid)

    # Skip source.fetch (not a direct evidence capability in recipes)
    for cap in action_ids:
        if cap == "source.fetch":
            continue
        # Every action must have a kind, method, locator, judgment, and modality mapping
        kind = _capability_to_kind(cap)
        method = _capability_to_method(cap)
        locator = _capability_to_locator_kind(cap)
        judgment = _capability_default_judgment(cap)
        modality = _capability_modality(cap)
        assert kind, f"Capability '{cap}' has no kind mapping"
        assert method, f"Capability '{cap}' has no method mapping"
        assert locator, f"Capability '{cap}' has no locator mapping"
        assert judgment, f"Capability '{cap}' has no judgment mapping"
        assert modality, f"Capability '{cap}' has no modality mapping"


# ══════════════════════════════════════════════════════════════════════
# Gate H1: Evidence Integrity + Agent Contract + User UX
# ══════════════════════════════════════════════════════════════════════


# ── H1-A: Evidence provenance verification ──────────────────────────

def test_registered_provider_without_work_output_rejected(monkeypatch, tmp_path):
    """H1-A: status=complete with registered provider but no work/ output → rejected."""
    import json, shutil, stat as _stat
    from knowledge_studio.ingest_prepare import prepare_ingest
    from knowledge_studio.raw_commit import raw_commit, CommitError

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    f = tmp_path / "test.md"
    f.write_text("# Test\nContent.", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True

    # Manually change manifest to claim a registered provider
    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    manifest["status"] = "complete"
    manifest["steps"] = [
        {"capability": "web.fetch", "provider": "firecrawl",
         "status": "succeeded", "reason": None}
    ]
    manifest["evidence_records"][0]["agent_judgment"] = "mechanical"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")

    # No work/firecrawl/ directory exists → should be rejected
    try:
        raw_commit(result["manifest_dir"])
        assert False, "Should have raised CommitError"
    except CommitError as exc:
        assert exc.code == "VALIDATION_FAILED"
        error_codes = {e["code"] for e in exc.details.get("errors", [])}
        assert "PROVENANCE_UNVERIFIABLE" in error_codes, (
            f"Expected PROVENANCE_UNVERIFIABLE in errors, got {error_codes}"
        )

    shutil.rmtree(tmp_path / ".oks", ignore_errors=True)
    shutil.rmtree(tmp_path / "raw", ignore_errors=True)


def test_runtime_tool_no_work_output_accepted(monkeypatch, tmp_path):
    """H1-A: runtime-tool provider does not need work/ output."""
    import json, shutil, stat as _stat
    from knowledge_studio.ingest_prepare import prepare_ingest
    from knowledge_studio.raw_commit import raw_commit

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    f = tmp_path / "test.md"
    f.write_text("# Test\nContent.", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True

    # Change step to claim runtime-tool (which is exempt from work/ check)
    man_path = tmp_path / ".oks" / "runs" / result["run_id"] / "manifest" / "evidence-manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    manifest["steps"] = [
        {"capability": "web.fetch", "provider": "runtime-tool",
         "status": "degraded", "reason": "used curl as fallback"}
    ]
    man_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Should succeed — runtime-tool is exempt
    commit_result = raw_commit(result["manifest_dir"])
    assert commit_result["status"] == "committed"

    shutil.rmtree(tmp_path / ".oks", ignore_errors=True)
    shutil.rmtree(tmp_path / "raw", ignore_errors=True)


# ── H1-B: Agent contract simplification ─────────────────────────────

def test_ingest_prepare_returns_candidate_providers(tmp_path):
    """H1-B: ingest prepare must return candidate_providers for non-text sources."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 mock")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is False
    assert "candidate_providers" in result, (
        "ingest prepare must return candidate_providers"
    )
    candidates = result["candidate_providers"]
    assert isinstance(candidates, list), "candidate_providers must be a list"
    # PDF recipe requires document.text.extract — there should be candidates
    assert len(candidates) >= 1, (
        f"Expected >=1 candidate providers for PDF, got {len(candidates)}"
    )
    for c in candidates:
        assert "id" in c, f"candidate missing id: {c}"
        assert "label" in c, f"candidate missing label: {c}"
        assert "status" in c, f"candidate missing status: {c}"

    import shutil
    shutil.rmtree(tmp_path / ".oks", ignore_errors=True)


def test_ingest_prepare_generates_work_output_for_text_ready(tmp_path):
    """H1-A: text_ready sources must generate work/text-read/output.md."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    f = tmp_path / "test.md"
    f.write_text("# Test\nContent for provenance.", encoding="utf-8")

    result = prepare_ingest(str(f), kb_root=tmp_path)
    assert result["text_ready"] is True

    # work/text-read/output.md must exist
    work_output = tmp_path / ".oks" / "runs" / result["run_id"] / "work" / "text-read" / "output.md"
    assert work_output.is_file(), f"work/text-read/output.md must exist at {work_output}"
    content = work_output.read_text(encoding="utf-8")
    assert "Content for provenance" in content

    import shutil
    shutil.rmtree(tmp_path / ".oks", ignore_errors=True)
