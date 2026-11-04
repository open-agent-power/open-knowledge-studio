"""Strict knowledge classification must retain reviewed Skill promotion."""
import pytest
import hashlib

from knowledge_studio import skills, store, draft_review
from knowledge_studio.knowledge_policy import validate_classification


def test_skill_area_requires_explicit_skill_identity():
    with pytest.raises(ValueError, match="Unknown knowledge domain"):
        validate_classification("skills", "strategy")
    assert validate_classification("skills", "strategy", skill=True) == ("skills", "strategies")
    with pytest.raises(ValueError):
        validate_classification("invented", "strategy", skill=True)


def test_imported_skill_keeps_review_and_independent_classification(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_ROOT", str(root))
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: sample\ndescription: Test reviewed Skill\n---\n\n"
        + "Keep instructions under explicit human review.\n" * 8,
        encoding="utf-8",
    )
    imported = skills.import_skill(source, category="knowledge/retrieval")
    candidate = imported["entry"]["slug"]
    assert not list((root / "wiki").rglob("*.md"))
    candidate_path = root / "drafts" / f"{candidate}.md"
    original = candidate_path.read_bytes()
    slug = store.promote_draft(candidate)
    page = store.get_wiki_page(slug)
    assert page["area"] == "skills"
    assert page["artifact_kind"] == "skill"
    assert page["human_reviewed_at"]
    assert candidate_path.read_bytes() == original
    receipt = draft_review.read_receipt(root, candidate, hashlib.sha256(original).hexdigest())
    assert receipt["decision"] == "promoted"
    assert draft_review.read_original(root, receipt) == original
