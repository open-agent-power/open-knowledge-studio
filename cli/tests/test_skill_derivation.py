"""Synthetic approval fixtures: package derivation never implies real user approval."""
import shutil
from pathlib import Path

import pytest
import yaml

from knowledge_studio import skill_derivation as derivation, skills, store


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """Every approval below is synthetic test setup in an isolated KB."""
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_ROOT", str(root))
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: standard\ndescription: Synthetic test Skill\n---\n\nUse checked sources.\n", encoding="utf-8", newline="\n")
    (source / "guide.txt").write_bytes(b"first\ncontext 1\ncontext 2\ncontext 3\nlast\n")
    (source / "delete.txt").write_text("base\n", encoding="utf-8")
    (source / "image.bin").write_bytes(b"\0base")
    original = synthetic_approve(skills.import_skill(source))
    return root, source, original


def synthetic_approve(imported):
    """Exercise the real promotion path with explicitly synthetic fixture data."""
    slug = store.promote_draft(imported["entry"]["slug"])
    page = store.get_wiki_page(slug)
    return {"id": page["skill_id"], "version": page["skill_version"]}


def derive_approved(root, base, changes):
    return synthetic_approve(derivation.derive(root, {"base": base,
        "variant_id": "personal", "changes": changes}))


def files_at(root, reference):
    meta, files = skills._version_snapshot(root, reference["id"], reference["version"])
    return files


def bytes_under(root, directory):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in (root / directory).rglob("*") if p.is_file()}


def test_derivation_is_distinct_pending_and_preserves_reviewed_base_and_host(fixture):
    root, source, base = fixture
    host = Path(skills.load("standard", host="agents")["host_path"])
    (host / "local-note.txt").write_text("host user edit", encoding="utf-8")
    before = {directory: bytes_under(root, directory) for directory in ("wiki", ".agents")}
    receipt = (root / ".oks/skill-loads.json").read_bytes()
    full = derivation.detail(root, base)
    assert full["instructions"].startswith("---\nname: standard")
    result = derivation.derive(root, {"base": base, "variant_id": "personal",
        "changes": {"SKILL.md": full["instructions"] + "\nPrefer concise summaries.\n"}})
    assert result["review_state"] == "pending_review" and result["ref"]["id"] == "personal"
    assert result["lineage"]["upstream_base"] == full["ref"]
    captured = files_at(root, result["ref"])
    assert yaml.safe_load(captured["SKILL.md"].decode().split("---")[1])["name"] == "personal"
    assert captured["image.bin"] == b"\0base"
    assert {directory: bytes_under(root, directory) for directory in before} == before
    assert (root / ".oks/skill-loads.json").read_bytes() == receipt
    with pytest.raises(ValueError, match="human-reviewed"):
        derivation.detail(root, result["ref"])
    with pytest.raises(ValueError, match="already exists"):
        derivation.derive(root, {"base": base, "variant_id": "personal", "changes": {}})


def test_identity_claim_between_inspection_and_import_is_not_reused(fixture, monkeypatch):
    root, source, base = fixture
    original_import = skills.import_skill

    def concurrent_claim(source, **kwargs):
        # Simulate another importer claiming even the same bytes after derive's
        # initial inspection. The lock-time new-ID assertion must still reject.
        original_import(source, **{**kwargs, "require_new_id": False})
        return original_import(source, **kwargs)

    monkeypatch.setattr(skills, "import_skill", concurrent_claim)
    with pytest.raises(ValueError, match="already exists"):
        derivation.derive(root, {"base": base, "variant_id": "personal", "changes": {}})
    personal = [entry for entry in skills.entries(root=root) if entry["skill_id"] == "personal"]
    assert len(personal) == 1 and personal[0]["status"] == "draft"


def test_reviewed_instruction_edits_cannot_authorize_a_different_package(fixture):
    root, source, base = fixture
    assert "Use checked sources." in derivation.detail(root, base)["instructions"]
    skills.load("standard", host="agents")
    page = next(item for item in skills.entries(root=root, include_drafts=False)
                if item["skill_id"] == base["id"])
    card = Path(page["file_path"])
    original = card.read_bytes()
    edited = original.replace(b"Use checked sources.", b"Use a different, unreviewed instruction.")
    assert edited != original
    card.write_bytes(edited)  # Synthetic post-approval external edit.
    before = {folder: bytes_under(root, folder) for folder in ("wiki", "raw", "drafts", ".agents")}
    receipt = (root / ".oks/skill-loads.json").read_bytes()
    with pytest.raises(ValueError, match="instructions differ from immutable package"):
        derivation.detail(root, base)
    with pytest.raises(ValueError, match="instructions differ from immutable package"):
        derivation.derive(root, {"base": base, "variant_id": "personal", "changes": {}})
    assert {folder: bytes_under(root, folder) for folder in before} == before
    assert (root / ".oks/skill-loads.json").read_bytes() == receipt


def test_nonoverlap_merge_uses_recorded_base_and_creates_only_pending_version(fixture):
    root, source, base = fixture
    ours = derive_approved(root, base, {"guide.txt": "personal first\ncontext 1\ncontext 2\ncontext 3\nlast\n"})
    (source / "guide.txt").write_bytes(b"first\ncontext 1\ncontext 2\ncontext 3\nupstream last\n")
    theirs = synthetic_approve(skills.import_skill(source))
    request = {"ours": ours, "theirs": theirs}
    wiki_before = bytes_under(root, "wiki")
    raw_before = bytes_under(root, "raw")
    plan = derivation.preview_merge(root, request)
    assert not plan["conflicts"] and plan["base"]["version"] == base["version"]
    assert bytes_under(root, "raw") == raw_before
    merged = derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"]})
    assert bytes_under(root, "wiki") == wiki_before
    assert merged["review_state"] == "pending_review"
    assert merged["lineage"]["upstream_base"]["version"] == theirs["version"]
    assert files_at(root, merged["ref"])["guide.txt"] == b"personal first\ncontext 1\ncontext 2\ncontext 3\nupstream last\n"
    assert derivation.detail(root, ours)["lineage"]["upstream_base"]["version"] == base["version"]


def test_same_line_conflict_requires_explicit_resolution_and_rejects_stale_plan(fixture):
    root, source, base = fixture
    ours = derive_approved(root, base, {"guide.txt": "personal\n"})
    (source / "guide.txt").write_text("upstream\n", encoding="utf-8")
    theirs = synthetic_approve(skills.import_skill(source))
    request = {"ours": ours, "theirs": theirs}
    plan = derivation.preview_merge(root, request)
    assert plan["conflicts"] == ["guide.txt"]
    row = next(row for row in plan["files"] if row["path"] == "guide.txt")
    assert row["reason"] == "text_conflict" and "<<<<<<< ours" in row["merged"]["text"]
    drafts_before = bytes_under(root, "drafts")
    with pytest.raises(ValueError, match="Every conflict"):
        derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"]})
    with pytest.raises(ValueError, match="plan changed"):
        derivation.prepare_merge(root, {**request, "expected_plan_digest": "0" * 64,
            "resolutions": {"guide.txt": {"choice": "theirs"}}})
    with pytest.raises(ValueError, match="conflict markers"):
        derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"],
            "resolutions": {"guide.txt": {"choice": "text", "text": row["merged"]["text"]}}})
    assert bytes_under(root, "drafts") == drafts_before
    prepared = derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"],
        "resolutions": {"guide.txt": {"choice": "text", "text": "explicitly reconciled\n"}}})
    assert files_at(root, prepared["ref"])["guide.txt"] == b"explicitly reconciled\n"


def test_delete_binary_and_add_add_conflicts_preserve_bytes_until_choice(fixture):
    root, source, base = fixture
    ours = derive_approved(root, base, {"delete.txt": None, "image.bin": "personal text",
                                     "new.txt": "personal addition"})
    (source / "delete.txt").write_text("upstream changed", encoding="utf-8")
    (source / "image.bin").write_bytes(b"\0upstream")
    (source / "new.txt").write_text("upstream addition", encoding="utf-8")
    theirs = synthetic_approve(skills.import_skill(source))
    request = {"ours": ours, "theirs": theirs}
    plan = derivation.preview_merge(root, request)
    assert {row["path"]: row["reason"] for row in plan["files"] if row["status"] == "conflict"} == {
        "delete.txt": "delete_modify", "image.bin": "binary", "new.txt": "add_add"}
    prepared = derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"],
        "resolutions": {"delete.txt": {"choice": "delete"}, "image.bin": {"choice": "theirs"},
                        "new.txt": {"choice": "ours"}}})
    files = files_at(root, prepared["ref"])
    assert "delete.txt" not in files and files["image.bin"] == b"\0upstream"
    assert files["new.txt"] == b"personal addition"


def test_references_paths_root_and_git_are_explicit_guards(fixture, tmp_path, monkeypatch):
    root, source, base = fixture
    fixed = derivation.detail(root, base)["ref"]
    with pytest.raises(ValueError, match="hashes changed"):
        derivation.detail(root, {**fixed, "manifest_sha256": "0" * 64})
    for changes in ({"../escape": "bad"}, {"Guide.txt": "collision"}, {"SKILL.md": None},
                    {"SKILL.md": "---\nname: [broken\n---\nInstructions\n"}):
        with pytest.raises(ValueError):
            derivation.derive(root, {"base": base, "changes": changes})
    second = tmp_path / "other-kb"
    (second / "wiki").mkdir(parents=True)
    with pytest.raises(ValueError, match="root does not match"):
        derivation.derive(second, {"base": base, "changes": {}})
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="Git is unavailable"):
        derivation.preview_merge(root, {"ours": base, "theirs": base})


@pytest.mark.parametrize("side", ["ours", "theirs"])
def test_approval_after_preview_invalidates_previous_active_versions(fixture, tmp_path, side):
    root, source, base = fixture
    ours = derive_approved(root, base, {"guide.txt": "personal first\ncontext 1\ncontext 2\ncontext 3\nlast\n"})
    (source / "guide.txt").write_bytes(b"first\ncontext 1\ncontext 2\ncontext 3\nupstream last\n")
    theirs = synthetic_approve(skills.import_skill(source))
    request = {"ours": ours, "theirs": theirs}
    plan = derivation.preview_merge(root, request)
    if side == "theirs":
        (source / "extra.txt").write_bytes(b"newer upstream")
        synthetic_approve(skills.import_skill(source))
    else:
        personal_source = tmp_path / "newer-personal"
        personal_source.mkdir()
        for name, content in files_at(root, ours).items():
            target = personal_source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (personal_source / "extra.txt").write_bytes(b"newer personal edit")
        synthetic_approve(skills.import_skill(personal_source, skill_id="personal",
            lineage=derivation.detail(root, ours)["lineage"]))
    before = bytes_under(root, "drafts")
    with pytest.raises(ValueError, match="no longer active"):
        derivation.prepare_merge(root, {**request, "expected_plan_digest": plan["plan_digest"]})
    assert bytes_under(root, "drafts") == before
