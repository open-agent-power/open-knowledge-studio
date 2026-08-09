"""Formal pytest for Gate RC-PROTOCOL-01 — Raw Bundle v0.2 strict schema compliance.

Covers:
    - derived field: [] when no supplementary, proper entries when present
    - Supplementary artifact semantics (derived/ vs source/)
    - All declared paths exist on disk
    - Bundle JSON validation against formal raw-bundle-v0.2 schema
    - Locator positive (6 kinds) and negative (6 cases) validation
    - Artifact kind -> derived kind mapping (8 mappings)
    - Legacy locator rejection (no longer silently accepted)

These tests call ``oks raw-commit`` as a subprocess so they exercise the
exact same code path a real Agent would hit.
"""

import json
import hashlib
import subprocess
import tempfile
from pathlib import Path

import pytest


# ── helpers ──────────────────────────────────────────────────────────

def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_MEDIA_TYPE_UNSET = object()


def _make_manifest(
    art_dir: Path,
    primary_name: str,
    primary_content: str,
    evidence_records: list[dict],
    supp: tuple[tuple[str, str, str], ...] = (),
    fragment_evidence: list[dict] | None = None,
    create_fragment: bool = True,
    media_type: str | None | object = _MEDIA_TYPE_UNSET,
) -> tuple[Path, str]:
    """Build a minimal Agent-submitted manifest directory.

    Returns ``(manifest_dir, primary_hash)``.

    When *create_fragment* is True (default), a matching fragment file
    ``fragments/f1.json`` is written with *fragment_evidence* (defaults to
    *evidence_records* when None).  Pass ``create_fragment=False`` to test
    the missing-fragment error path.
    """
    m = art_dir.parent
    p = art_dir / primary_name
    p.write_text(primary_content, encoding="utf-8")
    ph = _sha_file(p)

    supp_list: list[dict] = []
    for sname, scontent, skind in supp:
        sp = art_dir / sname
        sp.write_text(scontent, encoding="utf-8")
        sh = _sha_file(sp)
        supp_list.append(
            {"artifact_id": sname, "kind": skind, "path": sname, "sha256": sh}
        )

    sid = f"src-{ph[:8]}"
    (m / "source-envelope.json").write_text(
        json.dumps(
            {
                "schema_version": "oks-source-envelope/v0.1",
                "source_id": sid,
                "source_uri": "file:///x",
                "source_modality": "text",
                "access_mode": "local_file",
                "captured_at": "2026-08-06T12:00:00Z",
                "captured_by": {"runtime": "claude-code"},
                "content_hash": ph,
                "evidence_manifest_ref": "m",
            }
        )
    )
    primary_artifact = {
        "artifact_id": primary_name,
        "kind": "primary_text",
        "path": primary_name,
        "sha256": ph,
    }
    if media_type is not _MEDIA_TYPE_UNSET:
        primary_artifact["media_type"] = media_type

    (m / "evidence-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "oks-evidence-manifest/v0.1",
                "manifest_id": "m",
                "source_id": sid,
                "status": "complete",
                "fragment_refs": ["f1"],
                "primary_artifact": primary_artifact,
                "supplementary_artifacts": supp_list,
                "evidence_records": evidence_records,
                "modalities": {
                    "text": {
                        "modality": "text",
                        "status": "succeeded",
                        "evidence_count": len(evidence_records),
                    }
                },
                "provenance": {"agent": {"runtime": "test"}},
                "failure_disposition": "none",
            }
        )
    )

    # ── Fragment file (matching by default) ──
    if create_fragment:
        fev = fragment_evidence if fragment_evidence is not None else evidence_records
        frag_dir = m / "fragments"
        frag_dir.mkdir(exist_ok=True)
        (frag_dir / "f1.json").write_text(
            json.dumps(
                {
                    "schema_version": "oks-evidence-fragment/v0.1",
                    "fragment_id": "f1",
                    "source_id": sid,
                    "producer": {
                        "runtime": "claude-code",
                        "provider": "test-provider",
                        "tool": "test-tool",
                    },
                    "status": "succeeded",
                    "artifacts": [
                        {
                            "artifact_id": primary_name,
                            "kind": "primary_text",
                            "path": primary_name,
                            "sha256": ph,
                        }
                    ],
                    "evidence": fev,
                    "modalities": {
                        "text": {
                            "modality": "text",
                            "status": "succeeded",
                            "evidence_count": len(fev),
                        }
                    },
                }
            )
        )

    return m, ph


def _run_commit(manifest_dir: Path, output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["oks", "raw-commit", str(manifest_dir), "-o", str(output)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ── 1. derived field ─────────────────────────────────────────────────

def test_derived_is_empty_array_without_supplementary():
    """bundle.json ``derived`` is ``[]`` not ``None`` when no supplementary."""
    base = Path(tempfile.mkdtemp(prefix="t1-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "data.txt",
        "content",
        [{"evidence_id": "e1", "artifact_id": "data.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"commit failed: {r.stdout[:200]}"
    bundle = json.loads((base / "out" / "bundle.json").read_text())
    assert isinstance(bundle["derived"], list)
    assert bundle["derived"] == []
    assert len(bundle["sources"]) == 1


def test_derived_has_entries_with_supplementary():
    """bundle.json ``derived`` contains correct entries for supplementary artifacts."""
    base = Path(tempfile.mkdtemp(prefix="t2-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "primary.txt",
        "main",
        [{"evidence_id": "e1", "artifact_id": "primary.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
        supp=(("ocr-out.txt", "OCR text", "ocr_result"),),
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"commit failed: {r.stdout[:200]}"
    bundle = json.loads((base / "out" / "bundle.json").read_text())
    assert len(bundle["derived"]) == 1
    d = bundle["derived"][0]
    assert d["kind"] == "ocr"
    assert d["path"] == "derived/ocr-out.txt"
    assert "primary.txt" in d["derived_from"]


# ── 2. Supplementary artifact source / derived semantics ─────────────

def test_supplementary_not_in_sources():
    """Supplementary artifacts belong in derived/, not sources/."""
    base = Path(tempfile.mkdtemp(prefix="t3-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "primary.txt",
        "main",
        [{"evidence_id": "e1", "artifact_id": "primary.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
        supp=(("screenshot.png", "png-data", "screenshot"),),
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0
    bundle = json.loads((base / "out" / "bundle.json").read_text())
    source_entities = [s["entity_id"] for s in bundle["sources"]]
    assert "screenshot.png" not in source_entities, (
        f"Supplementary artifact must not appear in sources[]: {source_entities}"
    )
    assert len(bundle["sources"]) == 1
    assert bundle["sources"][0]["primary_source"] is True


# ── 3. All declared paths exist on disk ──────────────────────────────

def test_all_declared_paths_exist_on_disk():
    """Every path declared in sources[] and derived[] refers to a real file."""
    base = Path(tempfile.mkdtemp(prefix="t4-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "primary.txt",
        "main content",
        [{"evidence_id": "e1", "artifact_id": "primary.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
        supp=(("ocr.txt", "ocr", "ocr_result"),),
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0
    out = base / "out"
    bundle = json.loads((out / "bundle.json").read_text())
    for s in bundle["sources"]:
        assert (out / s["path"]).is_file(), f"Missing source file: {s['path']}"
    for d in bundle["derived"]:
        assert (out / d["path"]).is_file(), f"Missing derived file: {d['path']}"


# ── 4. Bundle schema validation ──────────────────────────────────────

def test_bundle_json_passes_schema_validation():
    """Assembled bundle.json passes strict jsonschema validation."""
    from jsonschema import validate

    base = Path(tempfile.mkdtemp(prefix="t5-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "data.txt",
        "content",
        [{"evidence_id": "e1", "artifact_id": "data.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
        supp=(("screen.png", "img", "screenshot"),),
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0
    bundle = json.loads((base / "out" / "bundle.json").read_text())
    from importlib.resources import files as _res_files
    raw_schema = (
        _res_files("knowledge_studio.schemas")
        .joinpath("raw-bundle-v0.2.schema.json")
        .read_text(encoding="utf-8")
    )
    schema = json.loads(raw_schema)
    # This must not raise
    validate(bundle, schema)


# ── 5. Locator positive — all 6 kinds accepted ───────────────────────

@pytest.mark.parametrize("kind,loc", [
    ("page", {"kind": "page", "page": 1}),
    ("bbox", {"kind": "bbox", "bbox": [0, 0, 100, 100]}),
    ("timestamp", {"kind": "timestamp", "start_ms": 0, "end_ms": 1000}),
    ("dom", {"kind": "dom", "xpath_fragment": "//div"}),
    ("document", {"kind": "document"}),
    ("custom", {"kind": "custom", "custom_label": "label"}),
])
def test_locator_valid_kinds_accepted(kind, loc):
    """Every valid locator kind must be accepted by raw-commit."""
    base = Path(tempfile.mkdtemp(prefix=f"t-loc-ok-{kind}-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "t.txt",
        "data",
        [{"evidence_id": f"e-{kind}", "artifact_id": "t.txt", "kind": "text",
          "method": "read", "locator": loc}],
    )
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"Locator {loc} was rejected: {r.stdout[:200]}"


# ── 6. Locator negative — 6 failure cases ────────────────────────────

@pytest.mark.parametrize("desc,loc", [
    ("page without page field", {"kind": "page"}),
    ("bbox without bbox field", {"kind": "bbox"}),
    ("timestamp without start_ms", {"kind": "timestamp", "end_ms": 1000}),
    ("dom without xpath_fragment", {"kind": "dom"}),
    ("custom without custom_label", {"kind": "custom"}),
    ("unknown kind", {"kind": "unknown"}),
])
def test_locator_invalid_kinds_rejected(desc, loc):
    """Invalid locators must be rejected with a clear error."""
    base = Path(tempfile.mkdtemp(prefix="t-loc-bad-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "t.txt",
        "data",
        [{"evidence_id": "e-bad", "artifact_id": "t.txt", "kind": "text",
          "method": "read", "locator": loc}],
    )
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, (
        f"Locator '{desc}' should have been rejected but was accepted"
    )


# ── 7. Legacy locator — no longer silently accepted ──────────────────

def test_legacy_locator_without_kind_rejected():
    """Locators without a ``kind`` field are no longer silently accepted."""
    base = Path(tempfile.mkdtemp(prefix="t-legacy-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "x.txt",
        "data",
        [{"evidence_id": "e-legacy", "artifact_id": "x.txt", "kind": "text",
          "method": "read", "locator": {"page": 1}}],
    )
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, (
        "Legacy locator (no 'kind') was silently accepted — should be rejected"
    )
    result = json.loads(r.stdout)
    assert "locator" in str(result).lower() or "kind" in str(result).lower(), (
        f"Error should mention locator/kind: {json.dumps(result)[:200]}"
    )


# ── 8. Artifact kind -> derived kind mapping ─────────────────────────

@pytest.mark.parametrize("art_kind,expected", [
    ("ocr_result", "ocr"),
    ("screenshot", "visual_observation"),
    ("dom_snapshot", "layout"),
    ("rendered_page", "visual_observation"),
    ("api_response", "other"),
    ("page_image", "visual_observation"),
    ("subtitle", "other"),
    ("primary_text", "other"),
    ("transcript", "other"),
])
def test_artifact_kind_maps_to_derived_kind(art_kind, expected):
    """Each artifact ``kind`` maps to the correct derived ``kind``."""
    base = Path(tempfile.mkdtemp(prefix=f"t-map-{art_kind}-"))
    art = base / "artifacts"
    art.mkdir()
    ap = art / "out.dat"
    ap.write_text("derived", encoding="utf-8")
    ah = _sha_file(ap)
    pp = art / "primary.dat"
    pp.write_text("primary", encoding="utf-8")
    ph = _sha_file(pp)

    sid = f"s-{ph[:8]}"
    (base / "source-envelope.json").write_text(
        json.dumps({
            "schema_version": "oks-source-envelope/v0.1", "source_id": sid,
            "source_uri": "file:///x", "source_modality": "text",
            "access_mode": "local_file", "captured_at": "2026-08-06T12:00:00Z",
            "captured_by": {"runtime": "test"}, "content_hash": ph,
            "evidence_manifest_ref": "m",
        })
    )
    (base / "evidence-manifest.json").write_text(
        json.dumps({
            "schema_version": "oks-evidence-manifest/v0.1", "manifest_id": "m",
            "source_id": sid, "status": "complete", "fragment_refs": ["f1"],
            "primary_artifact": {"artifact_id": "primary.dat", "kind": "primary_text",
                                 "path": "primary.dat", "sha256": ph},
            "supplementary_artifacts": [{"artifact_id": "out.dat", "kind": art_kind,
                                         "path": "out.dat", "sha256": ah}],
            "evidence_records": [{"evidence_id": "e1", "artifact_id": "primary.dat",
                "kind": "text", "method": "read", "locator": {"kind": "document"}}],
            "modalities": {"text": {"modality": "text", "status": "succeeded",
                                    "evidence_count": 1}},
            "provenance": {"agent": {"runtime": "test"}},
            "failure_disposition": "none",
        })
    )
    r = _run_commit(base, base / "out")
    assert r.returncode == 0, f"Commit failed: {r.stdout[:200]}"
    bundle = json.loads((base / "out" / "bundle.json").read_text())
    assert len(bundle["derived"]) == 1
    actual = bundle["derived"][0]["kind"]
    assert actual == expected, (
        f"Artifact kind '{art_kind}' mapped to derived '{actual}', expected '{expected}'"
    )


# ── 9. Gate RC-PROTOCOL-01A regression tests ─────────────────────────

def test_locator_missing_kind_reports_kind():
    """Legacy locator ``{"page": 1}`` must ONLY report missing 'kind',
    not spurious secondary required fields (bbox, start_ms, etc.).

    This guards against the Locator Schema ``if`` condition bug where
    ``allOf/if`` blocks without ``required: ["kind"]`` would all
    trigger simultaneously when ``kind`` was absent.
    """
    base = Path(tempfile.mkdtemp(prefix="t-loc-kind-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "x.txt",
        "data",
        [{"evidence_id": "e-legacy", "artifact_id": "x.txt", "kind": "text",
          "method": "read", "locator": {"page": 1}}],
    )
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "Legacy locator must be rejected"
    result = json.loads(r.stdout)
    # The error must mention 'kind' as the root cause
    msg = json.dumps(result).lower()
    assert "kind" in msg, (
        f"Error must report missing 'kind': {json.dumps(result)[:300]}"
    )
    # Spurious fields that must NOT appear when kind is simply missing
    spurious = ["bbox", "start_ms", "end_ms", "xpath_fragment", "custom_label"]
    for field in spurious:
        assert field not in msg, (
            f"Spurious field '{field}' in error for locator missing kind: "
            f"{json.dumps(result)[:300]}"
        )


def test_schema_validator_unavailable_rejected(monkeypatch):
    """When ``jsonschema`` cannot be imported, the commit must fail
    with ``SCHEMA_VALIDATOR_UNAVAILABLE`` — fail-closed, not silently
    skipping schema enforcement."""
    import knowledge_studio.raw_commit as rc

    # Reset the cached validator check
    rc._VALIDATOR_AVAILABLE = None

    # Make jsonschema unimportable
    import builtins
    _orig_import = builtins.__import__

    def _block_jsonschema(name, *args, **kwargs):
        if name == "jsonschema" or name.startswith("jsonschema."):
            raise ImportError(f"No module named '{name}' (blocked for test)")
        return _orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_jsonschema)

    try:
        rc._require_validator()
        pytest.fail("_require_validator() should have raised CommitError")
    except rc.CommitError as e:
        assert e.code == "SCHEMA_VALIDATOR_UNAVAILABLE", (
            f"Expected SCHEMA_VALIDATOR_UNAVAILABLE, got {e.code}: {e.message}"
        )
        assert "jsonschema" in e.message.lower(), (
            f"Error should mention jsonschema: {e.message}"
        )


def test_failed_bundle_validation_leaves_no_output():
    """When bundle assembly fails (e.g. invalid locator), the output
    directory must NOT exist — staging is cleaned up atomically."""
    base = Path(tempfile.mkdtemp(prefix="t-atomic-"))
    art = base / "artifacts"
    art.mkdir()
    # Use an invalid locator that will trigger schema rejection
    m, _ = _make_manifest(
        art,
        "data.txt",
        "content",
        [{"evidence_id": "e1", "artifact_id": "data.txt", "kind": "text",
          "method": "read", "locator": {"kind": "bbox"}}],
        # ^ kind=bbox without required 'bbox' field → INVALID_MANIFEST
    )
    output_dir = base / "out"
    r = _run_commit(m, output_dir)
    assert r.returncode != 0, "Commit with invalid locator must fail"
    # The output directory must not exist
    assert not output_dir.exists(), (
        f"Output directory {output_dir} must not exist after failed commit. "
        f"Contents: {list(output_dir.rglob('*')) if output_dir.exists() else 'N/A'}"
    )
    # Also verify no staging directories leaked
    staging_dirs = list(base.glob(".out.*"))
    assert len(staging_dirs) == 0, (
        f"Staging directories leaked: {[str(d) for d in staging_dirs]}"
    )


def test_primary_text_without_media_type_preserves_content():
    """``primary_text`` artifact without ``media_type`` must still render
    text content into ``content.md`` — not produce a 'Binary artifact'
    placeholder when the file has a known text extension (.md, .txt, etc.)."""
    base = Path(tempfile.mkdtemp(prefix="t-text-"))
    art = base / "artifacts"
    art.mkdir()
    markdown_body = "# Test Document\n\nReal content here.\n"
    m, _ = _make_manifest(
        art,
        "page.md",
        markdown_body,
        [{"evidence_id": "e1", "artifact_id": "page.md", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
    )
    # NOTE: _make_manifest does NOT set media_type on primary_artifact,
    # which reproduces the exact bug scenario.
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"Commit failed: {r.stdout[:200]}"
    content_md = (base / "out" / "content.md").read_text(encoding="utf-8")
    assert "Test Document" in content_md, (
        f"content.md must contain the actual Markdown body. "
        f"Got: {content_md[:200]}"
    )
    assert "Binary artifact" not in content_md, (
        f"content.md must NOT contain 'Binary artifact' placeholder. "
        f"Got: {content_md[:200]}"
    )


@pytest.mark.parametrize("media_type", [None, "text/plain", "application/pdf"])
def test_primary_media_type_values_are_safe(media_type):
    """Null and explicit media types must never crash raw-commit."""
    base = Path(tempfile.mkdtemp(prefix="t-media-type-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "source.txt",
        "Source content\n",
        [{"evidence_id": "e1", "artifact_id": "source.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
        media_type=media_type,
    )

    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"media_type={media_type!r}: {r.stdout[:300]}"


def test_primary_media_type_key_missing_is_safe():
    """The legacy manifest shape without a media_type key must still commit."""
    base = Path(tempfile.mkdtemp(prefix="t-media-type-missing-"))
    art = base / "artifacts"
    art.mkdir()
    m, _ = _make_manifest(
        art,
        "source.txt",
        "Source content\n",
        [{"evidence_id": "e1", "artifact_id": "source.txt", "kind": "text",
          "method": "read", "locator": {"kind": "document"}}],
    )

    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"missing media_type: {r.stdout[:300]}"


def test_schema_mirrors_identical():
    """Every schema in ``schemas/`` must have a SHA256-identical copy in
    ``cli/knowledge_studio/schemas/`` — no double fact-source drift."""
    import hashlib
    repo_schemas = Path(__file__).parent.parent.parent / "schemas"
    pkg_schemas = (
        Path(__file__).parent.parent / "knowledge_studio" / "schemas"
    )

    repo_files = sorted(
        f.name for f in repo_schemas.iterdir() if f.suffix == ".json"
    )
    pkg_files = sorted(
        f.name for f in pkg_schemas.iterdir() if f.suffix == ".json"
    )

    # Same set of files
    assert repo_files == pkg_files, (
        f"Schema file sets differ:\n"
        f"  repo only: {set(repo_files) - set(pkg_files)}\n"
        f"  pkg only: {set(pkg_files) - set(repo_files)}"
    )

    mismatches = []
    for name in repo_files:
        repo_hash = hashlib.sha256(
            (repo_schemas / name).read_bytes()
        ).hexdigest()
        pkg_hash = hashlib.sha256(
            (pkg_schemas / name).read_bytes()
        ).hexdigest()
        if repo_hash != pkg_hash:
            mismatches.append((name, repo_hash[:16], pkg_hash[:16]))

    assert len(mismatches) == 0, (
        f"Schema mirror mismatch — {len(mismatches)} file(s) differ:\n"
        + "\n".join(f"  {n}: repo={r}... pkg={p}..." for n, r, p in mismatches)
    )


# ── A1: Fragment ↔ Manifest evidence consistency ────────────────────

def test_fragment_manifest_consistent_passes():
    """Consistent fragment + manifest → commit succeeds."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    ev = [{"evidence_id": "e1", "artifact_id": "page.md", "kind": "text",
           "method": "read", "locator": {"kind": "document"},
           "agent_judgment": "mechanical"}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", ev)
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, f"Commit failed: {r.stderr[:300]}"


def test_fragment_missing_file_rejected():
    """fragment_refs points to a file that doesn't exist → MISSING_FRAGMENT."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    ev = [{"evidence_id": "e1", "artifact_id": "page.md", "kind": "text",
           "method": "read", "locator": {"kind": "document"}}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", ev)
    # Create fragments/ dir but delete the fragment file — triggers MISSING_FRAGMENT
    frag_file = m / "fragments" / "f1.json"
    frag_file.unlink()
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "Missing fragment file must be rejected"
    assert "MISSING_FRAGMENT" in r.stderr + r.stdout, (
        f"Must mention MISSING_FRAGMENT. Got: {r.stderr[:300]} {r.stdout[:300]}"
    )


def test_fragment_evidence_not_in_manifest_rejected():
    """Fragment evidence_id not in manifest → FRAGMENT_EVIDENCE_NOT_IN_MANIFEST."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"}}]
    fragment_ev = [{"evidence_id": "e2", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"}}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "Fragment evidence not in manifest must be rejected"
    assert "FRAGMENT_EVIDENCE_NOT_IN_MANIFEST" in r.stderr + r.stdout, (
        f"Must mention FRAGMENT_EVIDENCE_NOT_IN_MANIFEST. "
        f"Got: {r.stderr[:300]} {r.stdout[:300]}"
    )


def test_fragment_manifest_artifact_id_mismatch():
    """artifact_id differs between Fragment and Manifest → BLOCK."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"}}]
    fragment_ev = [{"evidence_id": "e1", "artifact_id": "different.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"}}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "artifact_id mismatch must be rejected"
    assert "FRAGMENT_MANIFEST_MISMATCH" in r.stderr + r.stdout, (
        f"Must mention FRAGMENT_MANIFEST_MISMATCH. "
        f"Got: {r.stderr[:300]} {r.stdout[:300]}"
    )


def test_fragment_manifest_kind_mismatch():
    """kind differs between Fragment and Manifest → BLOCK."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "subtitle", "method": "subtitle_extraction",
                    "locator": {"kind": "timestamp", "start_ms": 0, "end_ms": 1000}}]
    fragment_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "transcript", "method": "subtitle_extraction",
                    "locator": {"kind": "timestamp", "start_ms": 0, "end_ms": 1000}}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "kind mismatch must be rejected"
    assert "FRAGMENT_MANIFEST_MISMATCH" in r.stderr + r.stdout


def test_fragment_manifest_method_mismatch():
    """method differs between Fragment and Manifest → BLOCK."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "transcript", "method": "subtitle_extraction",
                    "locator": {"kind": "timestamp", "start_ms": 0, "end_ms": 1000}}]
    fragment_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "transcript", "method": "asr_transcription",
                    "locator": {"kind": "timestamp", "start_ms": 0, "end_ms": 1000}}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "method mismatch must be rejected"
    assert "FRAGMENT_MANIFEST_MISMATCH" in r.stderr + r.stdout


def test_fragment_manifest_agent_judgment_mismatch():
    """agent_judgment differs between Fragment and Manifest → BLOCK."""
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"},
                    "agent_judgment": "mechanical"}]
    fragment_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"},
                    "agent_judgment": "agent_observed"}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode != 0, "agent_judgment mismatch must be rejected"
    assert "FRAGMENT_MANIFEST_MISMATCH" in r.stderr + r.stdout


def test_fragment_null_field_not_compared():
    """Fragment has null for a field → skip comparison, commit succeeds.

    Only fields where BOTH sides declare a non-null value are compared.
    A null fragment field is treated as "not declared" — no false positive.
    """
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"},
                    "agent_judgment": "mechanical"}]
    fragment_ev = [{"evidence_id": "e1", "artifact_id": "page.md",
                    "kind": "text", "method": "read",
                    "locator": {"kind": "document"},
                    "agent_judgment": None}]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, (
        f"Null fragment fields should not cause mismatch. "
        f"Got: {r.stderr[:300]}"
    )


def test_manifest_extra_evidence_not_in_fragment_ok():
    """Manifest has extra evidence not in Fragment → commit succeeds.

    This is NOT a bidirectional check — Manifest MAY have additional
    evidence records that aren't in any fragment.
    """
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    manifest_ev = [
        {"evidence_id": "e1", "artifact_id": "page.md",
         "kind": "text", "method": "read", "locator": {"kind": "document"}},
        {"evidence_id": "e2", "artifact_id": "page.md",
         "kind": "metadata", "method": "metadata_extraction",
         "locator": {"kind": "document"}},
    ]
    fragment_ev = [
        {"evidence_id": "e1", "artifact_id": "page.md",
         "kind": "text", "method": "read", "locator": {"kind": "document"}},
    ]
    m, _ = _make_manifest(art, "page.md", "# Test\n", manifest_ev,
                          fragment_evidence=fragment_ev)
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, (
        f"Manifest may have extra evidence. Got: {r.stderr[:300]}"
    )


# ── A2: ASR transcript semantics ─────────────────────────────────────

def test_asr_transcript_kind_accepted():
    """ASR transcript (kind=transcript, method=asr_transcription) passes raw_commit.

    Transcript must NOT be renamed to subtitle to pass schema validation.
    The schema accepts 'transcript' artifact kind and the evidence
    records keep their original semantics.
    """
    base = Path(tempfile.mkdtemp())
    art = base / "manifest" / "artifacts"
    art.mkdir(parents=True)
    ev = [{"evidence_id": "e1", "artifact_id": "page.md",
           "kind": "transcript", "method": "asr_transcription",
           "locator": {"kind": "timestamp", "start_ms": 0, "end_ms": 12000},
           "agent_judgment": "mechanical"}]
    m, _ = _make_manifest(art, "page.md", "# ASR test\n", ev)
    r = _run_commit(m, base / "out")
    assert r.returncode == 0, (
        f"ASR transcript must be accepted as valid evidence. "
        f"Got: {r.stderr[:300]}"
    )
    # Verify the evidence in the bundle preserves transcript semantics
    evidence_lines = (base / "out" / "evidence.jsonl").read_text(encoding="utf-8")
    assert "transcript" in evidence_lines, (
        f"evidence.jsonl must contain 'transcript' kind. Got: {evidence_lines[:200]}"
    )
    assert "asr_transcription" in evidence_lines, (
        f"evidence.jsonl must contain 'asr_transcription' method. "
        f"Got: {evidence_lines[:200]}"
    )
    assert "subtitle_extraction" not in evidence_lines, (
        "ASR transcript must NOT be renamed to subtitle_extraction"
    )
