import hashlib
from pathlib import Path
import pytest

from knowledge_studio import draft_review, mail_knowledge, store


def _draft(tmp_path, name, body):
    path = tmp_path / "drafts" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"---\ntitle: {name}\ndraft_type: concept\ndraft_area: computing\n---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return path, path.read_bytes()


@pytest.mark.parametrize("decision", ["promoted", "rejected"])
def test_review_decision_is_bound_to_exact_sha_and_retains_original(monkeypatch, tmp_path, decision):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "exact", "Version one")
    expected = hashlib.sha256(original).hexdigest()

    if decision == "promoted":
        store.promote_draft("exact", expected_sha256=expected)
    else:
        store.reject_draft("exact")

    assert path.read_bytes() == original
    receipt = draft_review.read_receipt(tmp_path, "exact", expected)
    assert receipt["decision"] == decision
    assert draft_review.read_original(tmp_path, receipt) == original
    assert "exact" not in {item["slug"] for item in store.list_drafts()}

    path.write_bytes(original + b"\nEdited after review\n")
    assert "exact" in {item["slug"] for item in store.list_drafts()}
    current = draft_review.capture(tmp_path, "exact")
    assert draft_review.disposition(tmp_path, current["relative"], current["sha256"]) is None


def test_list_drafts_reuses_one_promotion_index(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    for name in ("one", "two", "three"):
        _draft(tmp_path, name, "Pending review")
    scans = []
    original = draft_review.promotions

    def counted(root):
        scans.append(root)
        return original(root)

    monkeypatch.setattr(draft_review, "promotions", counted)

    assert len(store.list_drafts()) == 3
    assert scans == [tmp_path]


def test_promotion_recovery_reuses_supplied_index(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "recover-index", "Exact Wiki proof")
    digest = hashlib.sha256(original).hexdigest()

    def failed_receipt(*args, **kwargs):
        raise OSError("receipt write interrupted")

    monkeypatch.setattr(draft_review, "record_decision", failed_receipt)
    with pytest.raises(OSError, match="receipt write interrupted"):
        store.promote_draft(path.stem)
    index = draft_review.promotions(tmp_path)

    def no_rescan(root):
        raise AssertionError("Recovery must reuse the supplied promotion index")

    monkeypatch.setattr(draft_review, "promotions", no_rescan)
    receipt = draft_review.disposition(tmp_path, "drafts/recover-index.md", digest, promotions=index)

    assert receipt["decision"] == "promoted"
    assert draft_review.read_original(tmp_path, receipt) == original
    assert draft_review.read_receipt(tmp_path, path.stem, digest, promotions=index) == receipt


def test_exact_review_rejects_stale_sha_without_writing_wiki(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "stale", "Version one")
    stale = hashlib.sha256(original).hexdigest()
    path.write_bytes(original + b"Edited")

    with pytest.raises(ValueError, match="changed"):
        store.promote_draft("stale", expected_sha256=stale)
    assert not list((tmp_path / "wiki").rglob("*.md"))
    assert "stale" in {item["slug"] for item in store.list_drafts()}
    current = draft_review.capture(tmp_path, "stale")
    assert draft_review.disposition(tmp_path, current["relative"], current["sha256"]) is None


@pytest.mark.parametrize("slug", ["stale-reject", "task-learning-0123456789abcdef0123456789ab"])
def test_exact_rejection_rejects_stale_sha_without_receipts(monkeypatch, tmp_path, slug):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, slug, "Version inspected by the reviewer")
    stale = hashlib.sha256(original).hexdigest()
    path.write_bytes(original + b"New unreviewed edit")
    current = path.read_bytes()

    with pytest.raises(ValueError, match="changed"):
        store.reject_draft(slug, expected_sha256=stale)

    assert path.read_bytes() == current
    assert not (tmp_path / "drafts/rejected").exists()
    assert not (tmp_path / ".oks/draft-reviews").exists()
    assert not (tmp_path / ".oks/reviewed-drafts").exists()


def test_external_edit_during_promotion_is_a_new_pending_version(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "editing", "Reviewed version")
    original_hash = hashlib.sha256(original).hexdigest()
    real_write = store.write_wiki_page

    def write_then_edit(*args, **kwargs):
        result = real_write(*args, **kwargs)
        path.write_bytes(original + b"New concurrent edit")
        return result

    monkeypatch.setattr(store, "write_wiki_page", write_then_edit)
    store.promote_draft("editing", expected_sha256=original_hash)

    current = path.read_bytes()
    assert current != original
    assert draft_review.read_receipt(tmp_path, "editing", original_hash)["decision"] == "promoted"
    assert draft_review.disposition(tmp_path, "drafts/editing.md", hashlib.sha256(current).hexdigest()) is None
    assert "editing" in {item["slug"] for item in store.list_drafts()}


def test_opposite_decision_for_same_revision_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "one-way", "Do not reverse decisions")
    store.reject_draft("one-way")
    before = list((tmp_path / "wiki").rglob("*.md"))

    with pytest.raises(ValueError, match="already reviewed"):
        store.promote_draft("one-way", expected_sha256=hashlib.sha256(original).hexdigest())

    assert list((tmp_path / "wiki").rglob("*.md")) == before
    assert path.read_bytes() == original


def test_review_receipts_are_isolated_by_slug_and_exact_sha(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    first, first_raw = _draft(tmp_path, "shared-a", "A")
    second, second_raw = _draft(tmp_path, "shared-b", "B")
    store.reject_draft("shared-a")
    store.reject_draft("shared-b")

    first_hash = hashlib.sha256(first_raw).hexdigest()
    second_hash = hashlib.sha256(second_raw).hexdigest()
    first_receipt = draft_review.read_receipt(tmp_path, "shared-a", first_hash)
    second_receipt = draft_review.read_receipt(tmp_path, "shared-b", second_hash)
    assert first_receipt["draft_slug"] == "shared-a"
    assert second_receipt["draft_slug"] == "shared-b"
    assert first_receipt["original"]["path"] != second_receipt["original"]["path"]
    assert first.exists() and second.exists()


def test_reject_decision_survives_legacy_receipt_write_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "reject-half-write", "Keep rejection authoritative")
    digest = hashlib.sha256(original).hexdigest()
    real_atomic_write = store._atomic_write

    def fail_compat_receipt(target, content):
        if Path(target).parent == tmp_path / "drafts" / "rejected":
            raise OSError("legacy receipt unavailable")
        return real_atomic_write(target, content)

    monkeypatch.setattr(store, "_atomic_write", fail_compat_receipt)
    with pytest.raises(OSError, match="legacy receipt unavailable"):
        store.reject_draft("reject-half-write", expected_sha256=digest)

    assert path.read_bytes() == original
    assert draft_review.disposition(tmp_path, "drafts/reject-half-write.md", digest)["decision"] == "rejected"
    with pytest.raises(ValueError, match="already reviewed"):
        store.promote_draft("reject-half-write", expected_sha256=digest)


@pytest.mark.parametrize("snapshot_damage", ["removed", "corrupted"])
def test_promotion_receipt_failure_with_missing_original_fails_closed(monkeypatch, tmp_path, snapshot_damage):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, "promote-half-write", "Recover from exact Wiki proof")
    digest = hashlib.sha256(original).hexdigest()

    def fail_decision(*args, **kwargs):
        raise OSError("decision receipt unavailable")

    monkeypatch.setattr(draft_review, "record_decision", fail_decision)
    with pytest.raises(OSError, match="decision receipt unavailable"):
        store.promote_draft("promote-half-write", expected_sha256=digest)

    assert path.read_bytes() == original
    snapshot = tmp_path / ".oks" / "reviewed-drafts" / f"{digest}.md"
    if snapshot_damage == "removed":
        snapshot.unlink()
    else:
        snapshot.write_bytes(b"damaged original evidence")

    with pytest.raises(ValueError, match="original is missing or mismatched"):
        store.reject_draft("promote-half-write", expected_sha256=digest)
    assert path.read_bytes() == original
    assert draft_review._receipt_path(tmp_path, "promote-half-write", digest).exists() is False


def test_review_root_is_explicit_and_does_not_follow_global_oks_root(monkeypatch, tmp_path):
    env_root = tmp_path / "env-root"
    explicit_root = tmp_path / "explicit-root"
    monkeypatch.setenv("OKS_ROOT", str(env_root))
    path, raw = _draft(explicit_root, "root-bound", "Use explicit root")

    captured = draft_review.capture(explicit_root, "root-bound")

    assert captured["raw"] == raw == path.read_bytes()
    assert captured["path"].is_relative_to(explicit_root)


def test_invalid_receipt_fails_closed_and_does_not_enable_redecision(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, raw = _draft(tmp_path, "corrupt", "Keep this candidate")
    digest = hashlib.sha256(raw).hexdigest()
    draft_review.preserve_original(tmp_path, "drafts/corrupt.md", raw)
    receipt_path = draft_review._receipt_path(tmp_path, "corrupt", digest)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="receipt is invalid"):
        store.reject_draft("corrupt")

    assert path.read_bytes() == raw
    assert not (tmp_path / "drafts/rejected").exists()


def test_original_proof_cannot_be_rebound_to_another_slug(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _, raw = _draft(tmp_path, "proof-source", "Bind proof to its candidate")
    receipt = draft_review.record_decision(tmp_path, "proof-source", raw, "rejected")
    forged = {**receipt, "draft_slug": "other-slug", "draft_path": "drafts/other-slug.md"}

    assert draft_review.read_original(tmp_path, receipt) == raw
    assert draft_review.read_original(tmp_path, forged) is None


@pytest.mark.parametrize("decision", ["promoted", "rejected"])
def test_knowledge_map_hides_only_exact_reviewed_draft_version(monkeypatch, tmp_path, decision):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    path, original = _draft(tmp_path, f"map-{decision}", "Exact review projection")
    digest = hashlib.sha256(original).hexdigest()

    if decision == "promoted":
        store.promote_draft(path.stem, expected_sha256=digest)
    else:
        store.reject_draft(path.stem, expected_sha256=digest)

    reviewed = draft_review.read_receipt(tmp_path, path.stem, digest)
    assert reviewed["decision"] == decision
    assert draft_review.read_original(tmp_path, reviewed) == original
    projection = mail_knowledge.knowledge_map(tmp_path)
    points = [point for domain in projection["domains"] for cluster in domain["clusters"]
              for point in cluster["points"]]
    assert all(item["path"] != f"drafts/{path.stem}.md" for item in points)
    assert path.read_bytes() == original

    path.write_bytes(original + b"\nEdited revision\n")
    edited = mail_knowledge.knowledge_map(tmp_path)
    points = [point for domain in edited["domains"] for cluster in domain["clusters"]
              for point in cluster["points"]]
    assert any(item["path"] == f"drafts/{path.stem}.md" and item["kind"] == "candidate"
               for item in points)


def test_capture_rejects_draft_directory_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.md").write_text("---\ntitle: Outside\n---\nbody", encoding="utf-8")
    root = tmp_path / "kb"
    root.mkdir()
    try:
        (root / "drafts").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="stay inside"):
        draft_review.capture(root, "escaped")
