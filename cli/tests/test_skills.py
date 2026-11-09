"""Review boundaries, complete assets, portable paths and owned host lifecycle."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
import yaml
from typer.testing import CliRunner

from knowledge_studio import skills, store
from knowledge_studio.cli import app


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_ROOT", str(root))
    return root


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "skill-source"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: sample\ndescription: Retrieve nebula knowledge\nrequires: [python]\n---\n\nSearch nebula notes, cite the source.\n" + "Detailed instructions.\n" * 80, encoding="utf-8")
    (folder / "scripts/run.py").write_bytes(b"print('never auto-execute')\n")
    (folder / "image.png").write_bytes(b"\x89PNG\x00\xff")
    return folder


def promote(result):
    slug = store.promote_draft(result["entry"]["slug"])
    return store.get_wiki_page(slug)


def write_meta(path, meta):
    body = meta.pop("body")
    for key in ("file_path", "slug"):
        meta.pop(key, None)
    path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True) + "---\n\n" + body, encoding="utf-8")


def test_import_preserves_full_assets_raw_evidence_and_is_idempotent(kb, source):
    result = skills.import_skill(source, category="knowledge/retrieval")
    assert result["entry"]["type"] == "strategy"
    assert result["entry"]["status"] == "draft"
    assert not list((kb / "wiki").rglob("*.md"))
    meta = store.parse_wiki_file(Path(result["entry"]["file_path"]))
    assert not meta.get("human_reviewed_at")
    captured = skills._unpack(meta)
    assert captured == {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert (kb / meta["raw_bundle"] / "bundle.json").exists()
    assert skills.import_skill(source, category="knowledge/retrieval")["duplicate"]
    assert len(skills.entries()) == 1
    assert skills.search("nebula") == []
    with pytest.raises(ValueError, match="human-reviewed"):
        skills.load("sample")


@pytest.mark.parametrize("kind", skills.TYPE_DIRS)
def test_promotion_keeps_identity_assets_and_independent_hierarchy(kb, source, kind):
    result = skills.import_skill(source, kind=kind, category="development/java")
    original = Path(result['entry']['file_path']).read_bytes()
    page = promote(result)
    assert Path(page["file_path"]).parent == kb / "wiki/skills" / skills.TYPE_DIRS[kind] / "development/java"
    assert page["type"] == kind and page["area"] == "skills"
    assert page["artifact_kind"] == "skill" and page["human_reviewed_at"]
    assert page["skill_dependencies"] == ["python"]
    assert skills._unpack(page)["image.png"] == (source / "image.png").read_bytes()
    assert Path(result['entry']['file_path']).read_bytes() == original
    assert not any(item['slug'] == result['entry']['slug'] for item in store.list_drafts())
    assert not any(item.get('status') == 'draft' for item in skills.entries())
    assert skills.import_skill(source, kind=kind, category="development/java")["duplicate"]


def test_three_types_have_unique_slugs_and_recall_is_separate(kb, source):
    pages = [promote(skills.import_skill(source, kind=kind, category="knowledge/retrieval")) for kind in skills.TYPE_DIRS]
    assert len({p["slug"] for p in pages}) == 3
    ordinary = store.write_wiki_page("nebula ordinary knowledge", "nebula normal notes", human_reviewed=True)
    hits = skills.search("nebula", category="knowledge", limit=10)
    assert len(hits) == 3
    assert {h["type"] for h in hits} == set(skills.TYPE_DIRS)
    assert all(h["skill_id"] == "sample" and h["score"] > 0 for h in hits)
    assert all(len(h["body_preview"]) < len(pages[0]["body"]) for h in hits)
    assert ordinary.stem not in {h["slug"] for h in hits}
    assert len(skills.search("nebula", kind="concept")) == 1
    assert not skills.search("nebula", category="documents")


def test_new_version_needs_review_and_supersedes_only_after_promotion(kb, source):
    old = promote(skills.import_skill(source))
    (source / "scripts/run.py").write_bytes(b"print('v2')\n")
    pending = skills.import_skill(source)
    assert pending["entry"]["skill_version"] != old["skill_version"]
    assert not pending["entry"]["human_reviewed_at"]
    assert skills.load("sample")["entry"]["skill_version"] == old["skill_version"]
    with pytest.raises(ValueError, match="human-reviewed"):
        skills.load("sample", version=pending["entry"]["skill_version"])
    latest = promote(pending)
    previous = store.get_wiki_page(old["slug"])
    assert previous["status"] == "superseded"
    assert previous["superseded_by"] == latest["slug"]
    assert skills.load("sample")["entry"]["skill_version"] == latest["skill_version"]


def test_multiple_pending_updates_rebase_on_current_reviewed_version(kb, source):
    original = promote(skills.import_skill(source))
    (source / "scripts/run.py").write_bytes(b"v2")
    second = skills.import_skill(source)
    (source / "scripts/run.py").write_bytes(b"v3")
    third = skills.import_skill(source)
    middle = promote(second)
    latest = promote(third)
    assert store.get_wiki_page(original["slug"])["status"] == "superseded"
    assert store.get_wiki_page(middle["slug"])["status"] == "superseded"
    assert latest["relates_to"] == middle["slug"]
    assert [e["skill_version"] for e in skills.entries(include_drafts=False) if e["status"] == "active"] == [latest["skill_version"]]


def test_search_load_command_pins_selected_category_version(kb, source):
    alpha = promote(skills.import_skill(source, category="alpha"))
    (source / "scripts/run.py").write_bytes(b"beta version")
    beta = promote(skills.import_skill(source, category="beta"))
    hit = skills.search("nebula", category="alpha")[0]
    assert hit["skill_version"] == alpha["skill_version"] != beta["skill_version"]
    result = CliRunner().invoke(app, hit["load_command"].split()[1:])
    assert result.exit_code == 0
    loaded = json.loads(result.output)
    assert loaded["entry"]["skill_version"] == alpha["skill_version"]


def test_review_reclassification_does_not_supersede_other_type(kb, source):
    original = promote(skills.import_skill(source))
    (source / "scripts/run.py").write_bytes(b"concept v2")
    pending = skills.import_skill(source)
    slug = store.promote_draft(pending["entry"]["slug"], wiki_type="concept")
    changed = store.get_wiki_page(slug)
    assert changed["type"] == "concept" and not changed.get("relates_to")
    assert store.get_wiki_page(original["slug"])["status"] == "active"


def test_failed_replacement_write_keeps_last_reviewed_version_active(kb, source, monkeypatch):
    original = promote(skills.import_skill(source))
    (source / "scripts/run.py").write_bytes(b"updated")
    pending = skills.import_skill(source)
    write = store._atomic_write
    def fail_new_page(path, content):
        if path.suffix == ".md" and path.is_relative_to(kb / "wiki"):
            raise OSError("simulated write failure")
        write(path, content)
    monkeypatch.setattr(store, "_atomic_write", fail_new_page)
    with pytest.raises(OSError, match="write failure"):
        store.promote_draft(pending["entry"]["slug"])
    assert store.get_wiki_page(original["slug"])["status"] == "active"
    assert Path(pending["entry"]["file_path"]).exists()


def test_promotion_cannot_move_skill_into_ordinary_domain(kb, source):
    pending = skills.import_skill(source)
    with pytest.raises(ValueError, match="independent skills area"):
        store.promote_draft(pending["entry"]["slug"], area="computing")
    assert Path(pending["entry"]["file_path"]).exists()


def test_promotion_cannot_deduplicate_onto_an_ordinary_page(kb, source):
    pending = skills.import_skill(source)
    body = store.parse_wiki_file(Path(pending["entry"]["file_path"]))["body"]
    ordinary = store.write_wiki_page("Ordinary", body, area="computing", human_reviewed=True)
    with pytest.raises(ValueError, match="another Wiki identity"):
        store.promote_draft(pending["entry"]["slug"])
    assert not store.parse_wiki_file(ordinary).get("artifact_kind")
    assert Path(pending["entry"]["file_path"]).exists()


@pytest.mark.parametrize("field", ["skill_package", "skill_manifest"])
def test_modified_snapshot_blocks_promotion_and_leaves_draft(kb, source, field):
    pending = skills.import_skill(source)
    meta = store.parse_wiki_file(Path(pending["entry"]["file_path"]))
    path = kb / meta[field]
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="modified after import"):
        store.promote_draft(pending["entry"]["slug"])
    assert Path(pending["entry"]["file_path"]).exists()


@pytest.mark.parametrize("bad", ["../outside", "a/../outside", "C:/outside", "a\\b", "con", "UPPER", "a//b"])
def test_unsafe_categories_do_not_write(kb, source, bad):
    with pytest.raises(ValueError):
        skills.import_skill(source, category=bad)
    assert not list((kb / "drafts").iterdir())


@pytest.mark.parametrize("paths", [["Foo/a", "foo/b"], ["a", "a/b"], ["SKILL.md", "skill.md"]])
def test_case_and_file_directory_collisions_are_rejected(paths):
    with pytest.raises(ValueError):
        skills._portable_names(paths)


@pytest.mark.parametrize("name", ["../escaped.txt", "/absolute.txt", "a\\b.txt", "NUL.txt"])
def test_archive_traversal_rejected_before_materialization(kb, source, name):
    pending = skills.import_skill(source)
    meta = store.parse_wiki_file(Path(pending["entry"]["file_path"]))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, b"escape")
    data = stream.getvalue()
    (kb / meta["skill_package"]).write_bytes(data)
    meta["skill_package_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        skills._unpack(meta)
    assert not (kb.parent / "escaped.txt").exists()


def test_project_host_load_and_unload_are_bounded_and_owned(kb, source):
    promote(skills.import_skill(source))
    cache = skills.load("sample")
    assert cache["executed"] is False
    assert Path(cache["assets_root"], "scripts/run.py").read_bytes() == (source / "scripts/run.py").read_bytes()
    loaded = skills.load("sample", host="agents")
    target = Path(loaded["host_path"])
    assert loaded["assets_root"] == str(target)
    assert target == kb / ".agents/skills/sample"
    assert skills.load("sample", host="agents")["already_loaded"]
    unrelated = target.parent / "my-custom/SKILL.md"
    unrelated.parent.mkdir()
    unrelated.write_text("keep", encoding="utf-8")
    assert skills.unload("sample", host="agents")["unloaded"]
    assert not target.exists() and unrelated.read_text() == "keep"
    with pytest.raises(ValueError, match="not an owned"):
        skills.unload("my-custom", host="agents")


@pytest.mark.parametrize("change", ["edited", "added-file", "added-directory"])
def test_unload_refuses_user_changes(kb, source, change):
    promote(skills.import_skill(source))
    target = Path(skills.load("sample", host="claude")["host_path"])
    if change == "edited":
        (target / "SKILL.md").write_text("user edits", encoding="utf-8")
    elif change == "added-file":
        (target / "custom.txt").write_text("user addition", encoding="utf-8")
    else:
        (target / "empty-custom-dir").mkdir()
    with pytest.raises(ValueError, match="modified|added directories"):
        skills.unload("sample", host="claude")
    assert (target / "scripts/run.py").exists()


def test_load_refuses_unmanaged_existing_host_folder(kb, source):
    promote(skills.import_skill(source))
    target = kb / ".agents/skills/sample"
    shutil.copytree(source, target)
    with pytest.raises(ValueError, match="already exists"):
        skills.load("sample", host="agents")
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()


def test_symlink_source_and_wiki_category_are_rejected(kb, source, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = source / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(ValueError, match="Symlink"):
        skills.import_skill(source)
    link.unlink()
    pending = skills.import_skill(source, category="linked")
    parent = kb / "wiki/skills/strategies"
    parent.mkdir(parents=True)
    (parent / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        store.promote_draft(pending["entry"]["slug"])
    assert not list(outside.iterdir())


def test_compact_router_backs_up_only_unchanged_bundled_skills_and_restores(kb, tmp_path):
    assets = tmp_path / "assets"
    for name in ("oks", "same", "modified", "empty-added"):
        path = assets / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(f"{name} instructions", encoding="utf-8")
    host = kb / ".agents/skills"
    for name in ("same", "modified", "empty-added"):
        shutil.copytree(assets / "skills" / name, host / name)
    (host / "modified/SKILL.md").write_text("user modified", encoding="utf-8")
    (host / "empty-added/custom").mkdir()
    (host / "custom").mkdir()
    result = skills.install_router(assets, compact=True)
    assert result["backed_up"] == ["same"]
    assert set(result["preserved"]) == {"modified", "empty-added"}
    assert (host / "oks/SKILL.md").exists() and (host / "custom").exists()
    backup = Path(result["backup_path"])
    assert (backup / "same/SKILL.md").exists()
    assert skills.restore_router_backup(backup)["restored"] == ["same"]
    assert (host / "same/SKILL.md").exists()
    assert skills.restore_router_backup(backup)["restored"] == []


def test_router_restore_does_not_overwrite_existing_copy(kb, tmp_path):
    assets = tmp_path / "assets"
    for name in ("oks", "same"):
        path = assets / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(name, encoding="utf-8")
    target = kb / ".agents/skills/same"
    shutil.copytree(assets / "skills/same", target)
    backup = Path(skills.install_router(assets, compact=True)["backup_path"])
    target.mkdir()
    (target / "SKILL.md").write_text("new user content", encoding="utf-8")
    with pytest.raises(ValueError, match="host Skill exists"):
        skills.restore_router_backup(backup)
    assert (target / "SKILL.md").read_text() == "new user content"


def test_cli_import_list_search_load_review_lifecycle(kb, source):
    runner = CliRunner()
    result = runner.invoke(app, ["skills", "import", str(source), "--category", "knowledge/retrieval"])
    assert result.exit_code == 0, result.output
    pending = json.loads(result.output)
    assert runner.invoke(app, ["skills", "load", "sample"]).exit_code == 2
    assert runner.invoke(app, ["drafts", "promote", pending["entry"]["slug"]]).exit_code == 0
    listing = runner.invoke(app, ["skills", "list", "--status", "active"])
    assert len(json.loads(listing.output)["entries"]) == 1
    found = runner.invoke(app, ["skills", "search", "nebula"])
    assert json.loads(found.output)["hits"][0]["skill_id"] == "sample"
    assert runner.invoke(app, ["skills", "load", "sample", "--target", "agents"]).exit_code == 0
    assert runner.invoke(app, ["skills", "unload", "sample", "--target", "agents"]).exit_code == 0


@pytest.mark.parametrize("query,expected", [
    ("协作 通信", "team-mail"), ("知识提取", "capture"),
    ("知识查询", "lookup"), ("Word 文档", "office-doc"),
])
def test_chinese_task_search_uses_capability_descriptions(kb, tmp_path, query, expected):
    descriptions = {
        "team-mail": "Durable collaboration mail and coordination",
        "capture": "Source ingestion and extraction to drafts",
        "lookup": "Recall and retrieve reviewed knowledge",
        "office-doc": "Create Word DOCX documents",
        "setup": "Assess profile and configure goals",
    }
    for identity, description in descriptions.items():
        folder = tmp_path / identity
        folder.mkdir()
        # Incidental mentions in long instructions must not become task identity.
        (folder / "SKILL.md").write_text(
            f"---\nname: {identity}\ndescription: {description}\n---\n"
            + "协作 通信 知识提取 知识查询 Word 文档\n" * (40 if identity == "setup" else 1),
            encoding="utf-8",
        )
        promote(skills.import_skill(folder))
    hits = skills.search(query, limit=3)
    assert hits and hits[0]["skill_id"] == expected
    assert skills.search("火星地质标本") == []


def test_instruction_only_term_does_not_route_a_task(kb, source):
    with (source / "SKILL.md").open("a", encoding="utf-8") as handle:
        handle.write("\nUse quasar-protocol for the specialist operation.\n")
    promote(skills.import_skill(source))
    assert skills.search("quasar-protocol") == []
    assert skills.search("nebula")[0]["skill_id"] == "sample"


@pytest.mark.parametrize("backend", ["native", "fts5", "fusion"])
def test_wiki_recall_excludes_skills_but_capability_search_finds_them(kb, source, backend):
    from knowledge_studio.recall import _recall_knowledge_via_backend
    page = promote(skills.import_skill(source))
    ordinary = store.write_wiki_page("nebula evidence", "nebula evidence for a decision", human_reviewed=True)
    hits = _recall_knowledge_via_backend(
        query="nebula", topic_id=None, limit=1, scope=None,
        goal_context={"mode": "none", "requested": "none"},
        explain=True, search_backend=backend,
    )
    assert len(hits) == 1 and hits[0]["slug"] == ordinary.stem
    assert skills.search("nebula")[0]["slug"] == page["slug"]


def test_cached_python_execution_does_not_break_reload_or_hide_edits(kb, source):
    promote(skills.import_skill(source))
    cache = Path(skills.load("sample")["assets_root"])
    script = cache / "scripts/run.py"
    result = subprocess.run([sys.executable, "-c", "import run"], cwd=script.parent, capture_output=True)
    assert result.returncode == 0
    assert list((script.parent / "__pycache__").glob("*.pyc"))
    assert skills.load("sample")["assets_root"] == str(cache)
    # Runtime tolerance must not swallow new non-bytecode files.
    note = script.parent / "__pycache__/notes.txt"
    note.write_text("user notes")
    with pytest.raises(ValueError, match="cache was modified"):
        skills.load("sample")
    note.unlink()
    script.write_text("print('edited source')")
    with pytest.raises(ValueError, match="cache was modified"):
        skills.load("sample")


def test_chinese_authored_custom_skill_retains_original_task_terms(kb, source):
    (source / "SKILL.md").write_text(
        "---\nname: custom\ndescription: 多智能体协作与通信\n---\n\n"
        "明确记录交接与结果，等待审核；仅处理获得授权的任务。\n", encoding="utf-8")
    promote(skills.import_skill(source))
    assert skills.search("协作 通信")[0]["skill_id"] == "custom"


def test_batch_import_reports_partial_and_does_not_import_router(kb, tmp_path):
    collection = tmp_path / "collection"
    for name in ("good", "bad", "oks"):
        folder = collection / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: good\n---\nUse skills" if name == "good" else "", encoding="utf-8")
    result = CliRunner().invoke(app, ["skills", "import", str(collection), "--all"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "partial" and len(data["errors"]) == 1
    assert len(data["imported"]) == 1
    assert not data["imported"][0]["entry"]["human_reviewed_at"]
