import hashlib
import json
from pathlib import Path

import pytest

from knowledge_studio import draft_review, store


def test_promote_draft_preserves_tags_traces_and_review(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "base-loop.md"
    draft.parent.mkdir()
    draft.write_text(
        '''---
title: "Feishu Base learning loop"
draft_type: strategy
draft_area: computing
source_type: external
tags: "feishu, learning-loop"
traces:
  - kind: execution
    id: run_1
    path: raw/bundle
review:
  outcome: success
  decision_correct: true
  lesson: "accepted in Base"
  reviewed_at: "2026-07-22T00:20:00+08:00"
status: draft
---

The reviewed body is preserved as the Wiki page content.
''',
        encoding="utf-8",
    )

    slug = store.promote_draft("base-loop")
    page = store.get_wiki_page(slug)

    assert page is not None
    assert page["source_type"] == "external"
    assert page["tags"] == "feishu, learning-loop"
    assert page["traces"][0]["id"] == "run_1"
    assert page["review"]["lesson"] == "accepted in Base"
    assert Path(page["file_path"]).parent.name == "strategies"
    assert draft.read_text(encoding="utf-8").startswith("---")
    receipt = draft_review.read_receipt(tmp_path, "base-loop", hashlib.sha256(draft.read_bytes()).hexdigest())
    assert receipt["decision"] == "promoted"
    assert draft_review.read_original(tmp_path, receipt) == draft.read_bytes()
    assert "base-loop" not in {item["slug"] for item in store.list_drafts()}


def test_reject_draft_preserves_append_only_review_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "not-worth-keeping.md"
    draft.parent.mkdir()
    draft_content = """---
title: Not worth keeping
status: draft
---

This candidate was rejected.
"""
    draft.write_text(draft_content, encoding="utf-8")

    receipt_path = store.reject_draft("not-worth-keeping")

    assert draft.read_text(encoding="utf-8") == draft_content
    assert receipt_path.parent == tmp_path / "drafts" / "rejected"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["decision"] == "rejected"
    assert receipt["draft_slug"] == "not-worth-keeping"
    assert receipt["draft_title"] == "Not worth keeping"
    assert receipt["draft_sha256"] == hashlib.sha256(draft_content.encode()).hexdigest()
    assert "draft_content" not in receipt
    review = draft_review.read_receipt(tmp_path, "not-worth-keeping", receipt["draft_bytes_sha256"])
    assert review["decision"] == "rejected"
    assert draft_review.read_original(tmp_path, review) == draft.read_bytes()
    assert "not-worth-keeping" not in {item["slug"] for item in store.list_drafts()}


def test_reject_draft_creates_a_new_receipt_for_repeated_slug(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    drafts = tmp_path / "drafts"
    drafts.mkdir()

    (drafts / "repeat.md").write_text("---\ntitle: First\n---\nfirst", encoding="utf-8")
    first = store.reject_draft("repeat")
    (drafts / "repeat.md").write_text("---\ntitle: Second\n---\nsecond", encoding="utf-8")
    second = store.reject_draft("repeat")

    assert first != second
    assert first.exists()
    assert second.exists()
    assert (drafts / "repeat.md").exists()
    assert "repeat" not in {item["slug"] for item in store.list_drafts()}


@pytest.mark.parametrize("slug", ["../wiki/keep", "..\\wiki\\keep", ".", ""])
def test_draft_actions_reject_path_traversal(monkeypatch, tmp_path, slug):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="Invalid draft slug"):
        store.reject_draft(slug)
    with pytest.raises(ValueError, match="Invalid draft slug"):
        store.promote_draft(slug)


def test_reject_keeps_draft_when_receipt_write_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "keep-on-failure.md"
    draft.parent.mkdir()
    draft.write_text("---\ntitle: Keep on failure\n---\nbody", encoding="utf-8")

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_atomic_write", fail_write)

    with pytest.raises(OSError, match="disk full"):
        store.reject_draft("keep-on-failure")

    assert draft.exists()


def test_promote_draft_marks_the_superseded_page(monkeypatch, tmp_path):
    """CONSTITUTION A4: promotion must not leave the replaced page active."""
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    old_slug = store.write_wiki_page(
        title="Old caching guidance",
        content="Use a single global cache.",
        wiki_type="strategy",
        area="computing",
    ).stem

    draft = tmp_path / "drafts" / "caching-v2.md"
    draft.parent.mkdir(exist_ok=True)
    draft.write_text(
        f'''---
title: "Caching guidance v2"
draft_type: strategy
draft_area: computing
relates_to: {old_slug}
relationship: supersedes
status: draft
---

Per-tenant caches replace the single global cache.
''',
        encoding="utf-8",
    )

    new_slug = store.promote_draft("caching-v2")
    old_page = store.get_wiki_page(old_slug)
    new_page = store.get_wiki_page(new_slug)

    assert old_page["status"] == "superseded"
    assert old_page["superseded_by"] == new_slug
    assert new_page["relates_to"] == old_slug
    assert new_page["relationship"] == "supersedes"


def test_promote_draft_uses_explicit_slug_hint_for_non_ascii_title(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "feishu-review-return-provenance.md"
    draft.parent.mkdir()
    draft.write_text(
        '''---
title: "飞书个人审核回程的可追溯门禁"
draft_type: strategy
draft_area: computing
status: draft
---

Reviewed knowledge.
''',
        encoding="utf-8",
    )

    slug = store.promote_draft(
        "feishu-review-return-provenance",
        slug_hint="feishu-review-return-provenance",
    )

    assert slug.endswith("-feishu-review-return-provenance")
    assert store.get_wiki_page(slug)["title"] == "飞书个人审核回程的可追溯门禁"


def _write_draft(root: Path, name: str, body: str, **fields) -> None:
    import yaml

    meta = {
        "title": fields.pop("title", name),
        "draft_type": "concept",
        "draft_area": "computing",
        "status": "pending",
        **fields,
    }
    drafts = root / "drafts"
    drafts.mkdir(exist_ok=True)
    front = yaml.dump(meta, allow_unicode=True, sort_keys=False)
    (drafts / f"{name}.md").write_text(f"---\n{front}---\n\n{body}\n", encoding="utf-8")


@pytest.mark.parametrize("importance, confidence", [(0.3, 0.4), (0, 0), (1, 1)])
def test_promotion_preserves_declared_scores(monkeypatch, tmp_path, importance, confidence):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _write_draft(
        tmp_path, "scored", "A source with explicitly reviewed scores.",
        draft_type="strategy", draft_area="science",
        importance=importance, confidence=confidence,
    )

    page = store.get_wiki_page(store.promote_draft("scored"))

    assert page["importance"] == importance
    assert page["confidence"] == confidence
    assert page["type"] == "strategy"
    assert page["area"] == "science"
    assert Path(page["file_path"]).parent == tmp_path / "wiki/science/strategies"
    assert page["status"] == "active"
    assert page["human_reviewed_at"]
    assert (tmp_path / "drafts/scored.md").exists()


def test_promotion_keeps_legacy_score_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _write_draft(tmp_path, "legacy", "A legacy draft without scores.")

    page = store.get_wiki_page(store.promote_draft("legacy"))

    assert page["importance"] == 0.7
    assert page["confidence"] == 0.8


def test_promotion_preserves_candidate_summary_and_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    fields = {
        "summary": "Persist task state outside the context window.",
        "source_url": "https://example.org/memory",
        "source_bundle_id": "bundle:memory",
        "source_raw_bundle": "raw/2026/10/22/memory",
        "agent_observation": ".oks/runs/run-memory/agent-observation.json",
        "claim_ids": ["memory-external"],
        "evidence_refs": [{"artifact_id": "art-memory", "locator": {"kind": "document"}}],
    }
    _write_draft(tmp_path, "memory", "Read durable notes when resuming a task.",
                 **fields, wiki_promoted=False, workflow_status="awaiting_human_review")

    page = store.get_wiki_page(store.promote_draft("memory"))

    assert {key: page.get(key) for key in fields} == fields
    assert "wiki_promoted" not in page
    assert "workflow_status" not in page
    assert page["human_reviewed_at"]


def test_dedup_promotion_keeps_conflicting_source_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "The same conclusion may come from different sources."
    _write_draft(tmp_path, "first", body, source_bundle_id="bundle:first")
    page = store.get_wiki_page(store.promote_draft("first"))
    existing = Path(page["file_path"])
    before = existing.read_bytes()
    _write_draft(tmp_path, "second", body, source_bundle_id="bundle:second")

    with pytest.raises(ValueError, match="source_bundle_id"):
        store.promote_draft("second")

    assert existing.read_bytes() == before
    assert (tmp_path / "drafts/second.md").is_file()


def test_dedup_promotion_retains_evidence_and_reviewed_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "A body-identical draft with an explicit reviewed summary."
    _write_draft(tmp_path, "first", body, source_bundle_id="bundle:first", summary="Old summary")
    first = store.promote_draft("first")
    refs = [{"artifact_id": "art-first"}]
    _write_draft(tmp_path, "second", body, source_bundle_id="bundle:first",
                 summary="Reviewed summary", evidence_refs=refs)

    assert store.promote_draft("second") == first
    page = store.get_wiki_page(first)
    assert page["summary"] == "Reviewed summary"
    assert page["evidence_refs"] == refs
    assert page["source_bundle_id"] == "bundle:first"


@pytest.mark.parametrize("field", ["importance", "confidence"])
@pytest.mark.parametrize("value", [None, -0.1, 1.1, "0.4", True, float("nan"), float("inf")])
def test_promotion_rejects_invalid_scores_without_side_effects(monkeypatch, tmp_path, field, value):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    old = store.write_wiki_page("Old note", "Existing reviewed knowledge.", human_reviewed=True)
    before = old.read_bytes()
    _write_draft(
        tmp_path, "invalid", "A replacement with an invalid score.",
        relates_to=old.stem, relationship="supersedes", **{field: value},
    )
    draft = tmp_path / "drafts/invalid.md"
    draft_before = draft.read_bytes()

    with pytest.raises(ValueError, match=field):
        store.promote_draft("invalid")

    assert draft.read_bytes() == draft_before
    assert old.read_bytes() == before
    assert list((tmp_path / "wiki").rglob("*.md")) == [old]


def test_dedup_promotion_preserves_declared_scores(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "A second-hand claim with limited evidence."
    existing = store.write_wiki_page("Existing note", body)
    _write_draft(tmp_path, "reviewed", body, importance=0.3, confidence=0.4)

    slug = store.promote_draft("reviewed")
    page = store.get_wiki_page(slug)

    assert slug == existing.stem
    assert page["importance"] == 0.3
    assert page["confidence"] == 0.4
    assert page["status"] == "active"
    assert page["human_reviewed_at"]
    assert len(list((tmp_path / "wiki").rglob("*.md"))) == 1


def test_legacy_dedup_promotion_keeps_existing_importance(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    existing = store.write_wiki_page(
        "Existing note", "A body from an earlier review.", importance=0.3,
    )
    _write_draft(tmp_path, "legacy-duplicate", existing.read_text(encoding="utf-8").split("---", 2)[2].strip())

    slug = store.promote_draft("legacy-duplicate")
    page = store.get_wiki_page(slug)

    assert page["importance"] == 0.3
    assert page["confidence"] > 0.8
    assert page["status"] == "active"


def test_dedup_hit_still_records_the_human_review(monkeypatch, tmp_path):
    """Promoting a body-identical draft used to silently discard the approval.

    write_wiki_page returned the existing page early, so human_reviewed_at was
    never written and status stayed provisional — then promote_draft deleted the
    draft, making the lost review unrecoverable, with no error reported.
    """
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "Cache invalidation must be explicit."
    existing = store.write_wiki_page(
        title="Old Note", content=body, area="computing"
    )
    assert store.get_wiki_page(existing.stem)["status"] == "provisional"

    _write_draft(
        tmp_path, "d1", body,
        title="Reviewed Note",
        supersedes=existing.stem,
        relationship="supersedes",
    )
    slug = store.promote_draft("d1")

    page = store.get_wiki_page(slug)
    assert page["human_reviewed_at"], "the human review was discarded"
    assert page["status"] == "active"
    # The dedup target IS the page it declared it supersedes — a page cannot
    # supersede itself.
    assert page.get("superseded_by") in (None, "")


def test_dedup_hit_still_applies_the_declared_relationship(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "Cache invalidation must be explicit."
    store.write_wiki_page(title="Old Note", content=body, area="computing")
    other = store.write_wiki_page(
        title="Other", content="a completely different body", area="computing"
    )

    _write_draft(
        tmp_path, "d2", body,
        title="Duplicate Body",
        supersedes=other.stem,
        relationship="supersedes",
    )
    store.promote_draft("d2")

    superseded = store.get_wiki_page(other.stem)
    assert superseded["status"] == "superseded", "A4 relationship was dropped"
    assert superseded["superseded_by"]


@pytest.mark.parametrize("existing", [False, True])
def test_promotion_preserves_decision_options(monkeypatch, tmp_path, existing):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "Keep the scoped judgment and the unresolved alternative."
    if existing:
        store.write_wiki_page("Existing", body, wiki_type="concepts")
    options = [
        {"id": "local", "chosen": True, "rationale": "small report", "conditions": ["offline"]},
        {"id": "cloud", "chosen": False, "rejected_because": "private input"},
        {"id": "review", "status": "unresolved", "extension": {"owner": "team"}},
    ]
    _write_draft(tmp_path, "decisions", body, options=options)
    page = store.get_wiki_page(store.promote_draft("decisions"))
    assert page["options"] == options
    assert page["human_reviewed_at"]


def test_conflicting_dedup_decisions_keep_candidate_and_wiki(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "Same wording, different decisions."
    path = store.write_wiki_page("Original", body, wiki_type="concepts",
                                 options=[{"id": "A", "chosen": True}])
    before = path.read_bytes()
    _write_draft(tmp_path, "conflict", body, options=[{"id": "A", "chosen": False}])
    with pytest.raises(ValueError, match="options"):
        store.promote_draft("conflict")
    assert path.read_bytes() == before
    assert (tmp_path / "drafts/conflict.md").exists()


@pytest.mark.parametrize("options", ["text", {}, [1], [{"id": "x", "chosen": "false"}],
    [{"id": "x", "rationale": 7}], [{"id": "x", "extra": float("nan")}],
    [{"id": "x", "chosen": True}, {"id": "x", "chosen": False}]])
def test_invalid_options_keep_candidate_without_wiki_writes(monkeypatch, tmp_path, options):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _write_draft(tmp_path, "invalid-options", "Invalid decision.", options=options)
    with pytest.raises(ValueError, match="options"):
        store.promote_draft("invalid-options")
    assert (tmp_path / "drafts/invalid-options.md").exists()
    assert not list((tmp_path / "wiki").rglob("*.md"))


def test_dedup_io_failure_keeps_candidate_and_recovers_persisted_review(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "Review retry with the same decision."
    page = store.write_wiki_page("Original", body, wiki_type="concepts")
    options = [{"id": "offline", "chosen": True}]
    _write_draft(tmp_path, "retry", body, options=options)
    original = store._apply_relationship
    def fail(*args, **kwargs):
        raise OSError("simulated relationship write failure")
    monkeypatch.setattr(store, "_apply_relationship", fail)
    with pytest.raises(OSError, match="simulated"):
        store.promote_draft("retry")
    assert (tmp_path / "drafts/retry.md").exists()
    assert store.parse_wiki_file(page)["options"] == options
    digest = hashlib.sha256((tmp_path / "drafts/retry.md").read_bytes()).hexdigest()
    receipt = draft_review.disposition(tmp_path, "drafts/retry.md", digest)
    assert receipt["decision"] == "promoted"
    monkeypatch.setattr(store, "_apply_relationship", original)
    with pytest.raises(ValueError, match="already reviewed"):
        store.promote_draft("retry")
    assert store.parse_wiki_file(page)["options"] == options
    assert (tmp_path / "drafts/retry.md").exists()
