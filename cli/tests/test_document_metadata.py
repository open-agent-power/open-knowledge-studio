"""Common document fields keep list and graph projections consistent."""
from datetime import date, datetime, timezone

import pytest

from knowledge_studio import document_metadata, mail_knowledge, mail_web, store


@pytest.mark.parametrize("value", [date(2026, 11, 9), datetime(2026, 11, 9), "2026-11-09", "2026-11-09T08:00:00+08:00"])
def test_recorded_times_are_normalized_to_utc(value):
    assert document_metadata.parse_time(value) == datetime(2026, 11, 9, tzinfo=timezone.utc)


def test_quote_handling_preserves_the_two_existing_summary_views():
    body = "# Title\n\n> Original claim\nActual paragraph\n"
    assert document_metadata.summary({}, body) == "> Original claim Actual paragraph"
    assert document_metadata.summary({}, body, skip_quotes=True) == "Actual paragraph"


@pytest.mark.parametrize("body", ["Actual paragraph", ""])
def test_reader_keeps_its_body_fallback_for_markup_only_metadata(tmp_path, body):
    meta = {"summary": "***", "updated_at": "2026-11-09"}
    item = mail_web._memory_summary(meta, body, tmp_path / "note.md")
    assert item["summary"] == (body or "这份知识还没有可显示的摘要，打开详情查看原文。")
    assert document_metadata.summary(meta, body, skip_quotes=True) == ""


def test_list_and_graph_use_the_same_document_fields(tmp_path):
    path = tmp_path / "wiki" / "note.md"
    path.parent.mkdir()
    path.write_text("---\ntitle: A **shared** title\nupdated_at: 2026-11-09\narea: computing\n---\n\nAn ordinary paragraph.\n", encoding="utf-8")
    parsed = store.parse_wiki_file(path)
    body = parsed.pop("body")
    item = mail_web._memory_summary(parsed, body, path)
    graph = mail_knowledge.knowledge_map(tmp_path)
    point = graph["domains"][0]["clusters"][0]["points"][0]
    for key in ("title", "summary", "updated_at", "timestamp_source"):
        assert item[key] == point[key]
    assert item["title"] == "A shared title"


@pytest.mark.parametrize("metadata", [{"status": "archived"}, {"status": "retired"}, {"archived": "YES"}, {"archived": True}])
def test_visibility_uses_explicit_archive_fields(metadata):
    assert not document_metadata.is_visible(metadata)
