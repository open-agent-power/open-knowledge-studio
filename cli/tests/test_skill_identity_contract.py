"""Characterize existing identities for the P02 contract; no host deployment."""
import json
from pathlib import Path

import frontmatter
import pytest

from knowledge_studio import skills, store


@pytest.fixture
def example():
    path = Path(__file__).parent / "fixtures/skill-identity-projection.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def instance(tmp_path, monkeypatch, example):
    root, source = tmp_path / "kb", tmp_path / "source"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    for name, body in example["source_files"].items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode("utf-8"))
    monkeypatch.setenv("OKS_ROOT", str(root))
    return root, source


def reviewed(source, **kwargs):
    result = skills.import_skill(source, **kwargs)
    return store.get_wiki_page(store.promote_draft(result["entry"]["slug"]))


def set_reviewed_at(page, value):
    path = Path(page["file_path"])
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post["human_reviewed_at"] = value
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def test_golden_package_identity_matches_actual_import(instance, example):
    root, source = instance
    imported = skills.import_skill(source)
    page = store.parse_wiki_file(Path(imported["entry"]["file_path"]))
    actual = json.loads((root / page["skill_manifest"]).read_text(encoding="utf-8"))
    assert actual == example["package_manifest"]
    assert page["skill_version"] == example["package_manifest"]["version"]
    assert len({page[field] for field in ("skill_version", "skill_package_sha256", "skill_manifest_sha256")}) == 3
    assert skills._unpack(page) == {name: value.encode("utf-8") for name, value in example["source_files"].items()}
    assert page["status"] == "draft" and not page.get("human_reviewed_at")


def test_multiple_cards_share_package_but_receipt_cannot_identify_card(instance, example):
    root, source = instance
    pages = [reviewed(source, kind=p["type"], category=p["skill_category"])
             for p in example["card_projections"]]
    assert len({p["slug"] for p in pages}) == 2
    assert len({(p["skill_id"], p["skill_version"]) for p in pages}) == 1
    assert all(p["status"] == "active" for p in pages)
    # Read an old-format synthetic receipt; do not pretend it captures a card ID.
    path = root / ".oks/skill-loads.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(example["receipt_projection"]), encoding="utf-8")
    _, receipts = skills._receipts(root)
    assert receipts == example["receipt_projection"]
    receipt = receipts["agents/sample"]
    candidates = [p for p in pages if p["skill_id"] == "sample" and p["skill_version"] == receipt["version"]]
    assert len(candidates) == 2
    assert set(receipt) == {"version", "files", "loaded_at"}
    ordinary = store.write_wiki_page("Ordinary", "Independent ordinary knowledge.", human_reviewed=True)
    assert not store.parse_wiki_file(ordinary).get("artifact_kind")
    assert ordinary.stem not in {p["slug"] for p in skills.entries(include_drafts=False)}


def test_same_content_hash_does_not_merge_logical_ids(instance):
    root, source = instance
    first = reviewed(source, skill_id="sample-a")
    second = reviewed(source, skill_id="sample-b")
    assert first["skill_version"] == second["skill_version"]
    assert first["skill_package_sha256"] == second["skill_package_sha256"]
    assert first["skill_manifest_sha256"] != second["skill_manifest_sha256"]
    assert first["skill_id"] != second["skill_id"]
    assert len(skills.entries(include_drafts=False)) == 2


def test_default_selection_is_review_time_not_newest_content_or_category(instance):
    _, source = instance
    first = reviewed(source, category="alpha")
    (source / "references/example.txt").write_bytes(b"New content version.\n")
    second = reviewed(source, category="beta")
    set_reviewed_at(first, "2026-06-01T00:00:00Z")
    set_reviewed_at(second, "2026-01-01T00:00:00Z")
    assert skills._selected("sample")["skill_version"] == first["skill_version"]
    assert skills._selected("sample", second["skill_version"])["slug"] == second["slug"]
    assert store.get_wiki_page(first["slug"])["status"] == "active"


def test_display_version_text_is_part_of_content_identity(instance):
    _, source = instance
    first = skills.import_skill(source)["entry"]["skill_version"]
    path = source / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(b"name: sample\n", b"name: sample\nversion: 1.0.0\n"))
    second = skills.import_skill(source)["entry"]["skill_version"]
    assert first != second and len(second) == 64


@pytest.mark.parametrize("excluded", ["draft", "superseded", "archived", "unreviewed"])
def test_nonadmitted_cards_cannot_be_selected(instance, monkeypatch, excluded):
    candidate = {"skill_id": "sample", "skill_version": "a" * 64,
                 "status": "active", "human_reviewed_at": "2026-01-01T00:00:00Z"}
    if excluded in ("draft", "superseded"):
        candidate["status"] = excluded
    elif excluded == "archived":
        candidate["archived"] = True
    else:
        candidate.pop("human_reviewed_at")
    monkeypatch.setattr(skills, "entries", lambda **kwargs: [candidate])
    with pytest.raises(ValueError, match="human-reviewed"):
        skills._selected("sample")


def test_version_prefix_ambiguity_does_not_guess(instance, monkeypatch):
    candidates = [{"skill_id": "sample", "skill_version": "a" * 12 + suffix * 52,
                   "status": "active", "human_reviewed_at": "2026-01-01T00:00:00Z"}
                  for suffix in ("b", "c")]
    monkeypatch.setattr(skills, "entries", lambda **kwargs: candidates)
    with pytest.raises(ValueError, match="Ambiguous"):
        skills._selected("sample", "a" * 12)
