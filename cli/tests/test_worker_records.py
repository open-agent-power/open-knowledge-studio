import json
import hashlib

from knowledge_studio import store, draft_review
from knowledge_studio.worker_records import clean_fields, clean_records, merge_records


def test_snapshot_allowlist_excludes_credentials_attachments_and_leases():
    fields = clean_fields({
        "评级": "A", "base_token": "SECRET", "附件": [{"file_token": "PRIVATE"}],
        "租约所有者": "PRIVATE", "内容": [{"text": "原"}, {"text": "文"}],
        "希望解决的问题": "问题",
    })
    assert fields == {"评级": "A", "重点问题（可选）": "问题", "内容": "原文"}
    assert "SECRET" not in json.dumps(fields) and "PRIVATE" not in json.dumps(fields)


def test_records_require_full_source_identity_and_keep_quality_states():
    records = clean_records([
        {"source": {"base_token_hash": "abc", "table_id": "tbl1", "record_id": "r1", "token": "SECRET"},
         "fields": {"质量状态": "partial", "错误说明": "missing page"}, "observed_at": "now"},
        {"source": {"base_token_hash": "abc", "table_id": "tbl1"}, "fields": {"评级": "A"}},
    ])
    assert len(records) == 1
    assert records[0]["source"] == {"base_token_hash": "abc", "table_id": "tbl1", "record_id": "r1"}
    assert records[0]["fields"]["质量状态"] == "partial"
    assert records[0]["state"] == "snapshot"


def test_merge_uses_instant_and_scoped_identity_while_preserving_omitted_fields():
    identity = {"base_token_hash": "abc", "table_id": "tbl1", "record_id": "r1"}
    old = {"source": identity, "observed_at": "2026-10-19T01:00:00Z",
           "fields": {"评级": "A", "质量状态": "partial"}}
    newer = {"source": identity, "observed_at": "2026-10-19T09:30:00+08:00",
             "fields": {"审核动作": "accept", "质量状态": "failed"}}
    other = {"source": {**identity, "base_token_hash": "other"}, "observed_at": newer["observed_at"],
             "fields": {"质量状态": "skipped"}}
    result = merge_records([old], [newer, other])
    assert len(result) == 2
    first = next(row for row in result if row["source"]["base_token_hash"] == "abc")
    assert first["fields"] == {"评级": "A", "质量状态": "failed", "审核动作": "accept"}
    assert {row["fields"]["质量状态"] for row in result} == {"failed", "skipped"}


def test_promotion_and_content_dedup_preserve_worker_observations(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    body = "A reviewed body that is long enough to exercise the normal promotion path."
    source = {"base_token_hash": "abc", "table_id": "tbl1", "record_id": "r1"}
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "first.md").write_text(
        "---\ntitle: First\ndraft_type: concept\ndraft_area: computing\n"
        f"worker_records:\n  - source: {source}\n    observed_at: '2026-10-19T01:00:00Z'\n"
        "    fields:\n      质量状态: partial\n---\n\n" + body + "\n", encoding="utf-8"
    )
    slug = store.promote_draft("first")
    assert store.get_wiki_page(slug)["worker_records"][0]["fields"]["质量状态"] == "partial"

    second_path = drafts / "second.md"
    second_path.write_text(
        "---\ntitle: Second\ndraft_type: concept\ndraft_area: computing\n"
        f"worker_records:\n  - source: {source}\n    observed_at: '2026-10-19T02:00:00Z'\n"
        "    fields:\n      质量状态: failed\n      审核动作: accept\n---\n\n" + body + "\n",
        encoding="utf-8",
    )
    original = second_path.read_bytes()
    assert store.promote_draft("second") == slug
    row = store.get_wiki_page(slug)["worker_records"][0]
    assert row["fields"] == {"质量状态": "failed", "审核动作": "accept"}
    assert second_path.read_bytes() == original
    proof = draft_review.read_receipt(tmp_path, "second", hashlib.sha256(original).hexdigest())
    assert proof["decision"] == "promoted"
    assert draft_review.read_original(tmp_path, proof) == original
