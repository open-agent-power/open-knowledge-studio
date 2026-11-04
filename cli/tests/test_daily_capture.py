from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from knowledge_studio import daily_capture


def test_recent_entries_are_ordered_by_capture_time_not_hash(tmp_path):
    daily_capture.append_events(tmp_path, _source()['id'], [_event(id='first')], source=_source())
    daily_capture.append_events(tmp_path, _source()['id'], [_event(id='second')], source=_source())
    records = daily_capture.list_entries(tmp_path)
    assert records[0]['id'] == daily_capture._capture_id(_source()['id'], 'second')


def _source():
    return {"id": "codex-session-1", "host": "codex", "workspace": "repo-a", "label": "Current session"}


def _event(text="A useful exchange", **updates):
    event = {"id": "event-1", "kind": "discussion", "role": "assistant", "phase": "final",
             "text": text, "timestamp": datetime.now(timezone.utc).isoformat(), "session_id": "session-1"}
    event.update(updates)
    return event


def test_capture_commits_excerpt_and_indexes_only_after_raw(tmp_path):
    records = daily_capture.append_events(tmp_path, "codex-session-1", [_event()], source=_source())
    assert len(records) == 1
    item = records[0]
    assert item["learning_status"] == "pending"
    assert item["excerpt"] is True
    assert item["raw_path"].startswith("raw/")
    assert daily_capture.list_entries(tmp_path)[0]["id"] == item["id"]
    assert "text" not in daily_capture.list_entries(tmp_path)[0]
    full = daily_capture.entry(tmp_path, item["id"])
    assert full["text"] == "A useful exchange"
    bundle = json.loads((tmp_path / item["raw_path"] / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "raw-multimodal/v0.2"
    manifest = json.loads((tmp_path / item["raw_path"] / "evidence-manifest.json").read_text(encoding="utf-8"))
    assert manifest["notes"]["byte_range"] == [0, len(b"A useful exchange")]
    assert manifest["notes"]["role"] == "assistant"
    assert "full transcript" in manifest["notes"].get("capture_notice", "") or "excerpt" in manifest["notes"]


def test_retry_is_idempotent_but_same_event_id_different_content_fails_closed(tmp_path):
    event = _event()
    first = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())[0]
    again = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())[0]
    assert again["id"] == first["id"]
    assert len(daily_capture.list_entries(tmp_path)) == 1
    with pytest.raises(ValueError, match="different content"):
        daily_capture.append_events(tmp_path, "codex-session-1", [_event("Changed bytes")], source=_source())
    assert daily_capture.entry(tmp_path, first["id"])["text"] == "A useful exchange"


def test_same_excerpt_with_changed_event_metadata_fails_closed(tmp_path):
    event = _event()
    daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())
    changed = dict(event, timestamp="2026-11-01T01:02:03Z")
    with pytest.raises(ValueError, match="different content"):
        daily_capture.append_events(tmp_path, "codex-session-1", [changed], source=_source())


def test_retry_recovers_raw_commit_when_index_write_was_interrupted(tmp_path, monkeypatch):
    original = daily_capture.store._atomic_write
    event = _event()

    def fail_index(path, content):
        if Path(path).name.startswith("capture-") and str(path).endswith(".json"):
            raise OSError("simulated index interruption")
        return original(path, content)

    monkeypatch.setattr(daily_capture.store, "_atomic_write", fail_index)
    with pytest.raises(OSError, match="simulated"):
        daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())
    assert daily_capture.list_entries(tmp_path) == []
    monkeypatch.setattr(daily_capture.store, "_atomic_write", original)
    recovered = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())
    assert len(recovered) == 1
    assert daily_capture.entry(tmp_path, recovered[0]["id"])["text"] == "A useful exchange"
    assert len(list((tmp_path / "raw").rglob("bundle.json"))) == 1


def test_entry_fails_closed_when_raw_bundle_bytes_change(tmp_path):
    item = daily_capture.append_events(tmp_path, "codex-session-1", [_event()], source=_source())[0]
    bundle = tmp_path / item["raw_path"] / "bundle.json"
    bundle.write_bytes(bundle.read_bytes() + b"\nchanged")
    with pytest.raises(ValueError, match="Raw bundle integrity"):
        daily_capture.entry(tmp_path, item["id"])


def test_all_captured_text_is_redacted_and_source_is_an_excerpt(tmp_path):
    token = "sk-" + "a" * 24
    event = _event(f"credential={token}")
    item = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())[0]
    captured = daily_capture.entry(tmp_path, item["id"])
    assert token not in captured["text"]
    assert "***REDACTED***" in captured["text"]
    assert item["redacted"] is True
    assert "excerpt" in (tmp_path / item["raw_path"] / "raw.md").read_text(encoding="utf-8").lower()
    with pytest.raises(ValueError, match="different content"):
        daily_capture.append_events(tmp_path, "codex-session-1", [_event("credential=sk-" + "b" * 24)], source=_source())


def test_source_read_event_is_preserved_as_reading_excerpt(tmp_path):
    event = {"id": "read-1", "kind": "reading", "role": "source", "text": "Public article excerpt",
             "timestamp": datetime.now(timezone.utc).isoformat(), "session_id": "session-1",
             "source_path": "https://example.test/article", "locator": {"section": "Introduction"}}
    item = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())[0]
    assert item["kind"] == "reading"
    assert item["role"] == "source"
    assert daily_capture.entry(tmp_path, item["id"])["text"] == "Public article excerpt"
    assert item["title"] == "article"
    assert str(tmp_path) not in item["title"]


def test_discussion_title_uses_first_markdown_heading_line_and_is_bounded(tmp_path):
    event = _event("\n  ## A readable title  \n" + ("x" * 120))
    item = daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())[0]
    assert item["title"] == "A readable title"
    long_event = dict(event, id="long-event", text="# " + ("y" * 120))
    long_item = daily_capture.append_events(tmp_path, "codex-session-1", [long_event], source=_source())[0]
    assert len(long_item["title"]) <= 90
    assert "#" not in long_item["title"]


@pytest.mark.parametrize("event", [
    _event(role="tool", phase="commentary"),
    _event(role="assistant", phase="analysis"),
    _event(role="assistant", phase=None),
    _event(role="source", kind="discussion", phase=None),
    _event(kind="other"),
])
def test_hidden_or_unsupported_event_shapes_are_rejected_without_writes(tmp_path, event):
    with pytest.raises(ValueError):
        daily_capture.append_events(tmp_path, "codex-session-1", [event], source=_source())
    assert daily_capture.list_entries(tmp_path) == []
    assert not (tmp_path / "raw").exists()


def test_update_entry_changes_only_learning_metadata(tmp_path):
    item = daily_capture.append_events(tmp_path, "codex-session-1", [_event()], source=_source())[0]
    updated = daily_capture.update_entry(tmp_path, item["id"], {"learning_status": "skipped", "error": None})
    assert updated["learning_status"] == "skipped"
    with pytest.raises(ValueError):
        daily_capture.update_entry(tmp_path, item["id"], {"text": "replacement"})
    assert daily_capture.entry(tmp_path, item["id"])["text"] == "A useful exchange"


def test_learning_worker_fields_and_large_scan_limit_are_supported(tmp_path):
    item = daily_capture.append_events(tmp_path, "codex-session-1", [_event()], source=_source())[0]
    updated = daily_capture.update_entry(tmp_path, item["id"], {
        "learning_status": "processing", "draft_path": None, "learning_error": None,
        "learning_attempts": 1, "learning_updated_at": "2026-11-02T00:00:00Z",
        "learning_source_ids": ["candidate-source-1"],
    })
    assert updated["learning_attempts"] == 1
    assert updated["learning_source_ids"] == ["candidate-source-1"]
    assert len(daily_capture.list_entries(tmp_path, limit=1000)) == 1
    assert "source_path" not in daily_capture.entry(tmp_path, item["id"])


def test_symlink_in_capture_root_is_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / ".oks").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        daily_capture.append_events(tmp_path, "codex-session-1", [_event()], source=_source())
    assert list(outside.iterdir()) == []
