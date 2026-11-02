from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_studio import daily_capture, daily_sources


def _claude(root, workspace, **updates):
    src = {"id": "claude-one", "kind": "claude-workspace", "host": "claude", "workspace": str(workspace), "label": "Trial", "read_roots": [str(workspace / "docs")]}
    daily_sources.connect_source(root, src)
    payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(workspace), "session_id": "sess-1", "prompt": "Please summarize this source"}
    payload.update(updates)
    return payload


def test_codex_starts_at_eof_and_captures_only_public_message_phases(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "old"}]}}) + "\n")
    root = tmp_path / "kb"; root.mkdir()
    src = {"id": "codex-one", "kind": "codex-transcript", "host": "codex", "workspace": "repo", "label": "Current", "path": str(transcript)}
    daily_sources.connect_source(root, src)
    with transcript.open("a", encoding="utf-8") as f:
        for role, phase, typ, txt in [("assistant", "analysis", "output_text", "hidden"), ("assistant", "final", "output_text", "visible"), ("assistant", "commentary", "output_text", "progress"), ("user", None, "input_text", "question")]:
            p = {"type": "message", "role": role, "content": [{"type": typ, "text": txt}]}
            if phase: p["phase"] = phase
            f.write(json.dumps({"type": "response_item", "payload": p}) + "\n")
    out = daily_sources.sync(root, "codex-one")
    assert out["count"] == 3
    entries = list((root / ".oks/daily-capture/entries").glob("*.json"))
    texts = [json.loads(p.read_text())["preview"] for p in entries]
    assert set(texts) == {"visible", "progress", "question"}
    assert daily_sources.sync(root, "codex-one")["count"] == 0


def test_claude_prompt_literal_and_read_roots_only(tmp_path):
    root = tmp_path / "kb"; root.mkdir()
    ws = tmp_path / "work"; (ws / "docs").mkdir(parents=True)
    prompt = "Raw prompt text\nwith newline"
    result = daily_sources.observe_claude(root, _claude(root, ws, prompt=prompt))
    assert result["count"] == 1
    outside = {"hook_event_name": "PostToolUse", "cwd": str(ws), "session_id": "sess-1", "tool_name": "Read", "tool_input": {"file_path": str(ws / "secret.md")}, "tool_response": {"file": {"content": "no"}}}
    assert daily_sources.observe_claude(root, outside)["count"] == 0
    unknown = {**outside, "tool_input": {"file_path": str(ws / "docs" / "a.md")}, "tool_response": {"unexpected": "body"}}
    assert daily_sources.observe_claude(root, unknown)["status"] == "partial"


def test_claude_stop_real_schema_and_timestamp_fallback(tmp_path, monkeypatch):
    root = tmp_path / "kb"; root.mkdir()
    ws = tmp_path / "work"; ws.mkdir()
    src = _claude(root, ws)
    # Only the allowed Claude project/session JSONL path is accepted.
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'home'))
    project = Path.home() / ".claude" / "projects" / "test-session"
    project.mkdir(parents=True, exist_ok=True)
    file = project / "sess-1.jsonl"
    stop = {"hook_event_name": "Stop", "cwd": str(ws), "session_id": "sess-1", "transcript_path": str(file)}
    file.write_text('')
    daily_sources.observe_claude(root, {**stop, 'hook_event_name': 'SessionStart'})
    file.write_text(json.dumps({"type": "assistant", "timestamp": None, "message": {"type": "message", "role": "assistant", "content": [{"type": "thinking", "text": "secret reasoning"}, {"type": "text", "text": "answer"}]}, "stop_reason": "end_turn"}) + "\n")
    result = daily_sources.observe_claude(root, stop)
    assert result["count"] == 1
    assert "secret reasoning" not in json.dumps(result)
    assert daily_sources.overview(root)["sources"][0]["status"] == "captured"


def test_claude_stop_payload_does_not_need_delayed_transcript(tmp_path):
    root = tmp_path / 'kb'; root.mkdir()
    ws = tmp_path / 'work'; ws.mkdir()
    payload = _claude(root, ws, hook_event_name='Stop', last_assistant_message='Public final answer')
    result = daily_sources.observe_claude(root, payload)
    assert result['count'] == 1
    item = daily_capture.entry(root, result['captured'][0]['id'])
    assert item['text'] == 'Public final answer' and item['final']
    assert daily_sources.observe_claude(root, payload)['captured'][0]['id'] == item['id']


def test_claude_workspace_cannot_contain_knowledge_base(tmp_path):
    root = tmp_path / 'work' / 'kb'; root.mkdir(parents=True)
    with pytest.raises(ValueError, match='overlap'):
        daily_sources.connect_source(root, {'id': 'x', 'kind': 'claude-workspace', 'host': 'claude',
            'workspace': str(root.parent), 'label': 'x', 'read_roots': [str(root.parent)]})


def test_claude_read_success_and_user_prompt_distinct_identity(tmp_path):
    root = tmp_path / "kb"; root.mkdir()
    ws = tmp_path / "work"; (ws / "docs").mkdir(parents=True)
    payload = _claude(root, ws)
    p1 = daily_sources.observe_claude(root, payload)
    p2 = daily_sources.observe_claude(root, {**payload, "event_id": "second-prompt"})
    assert p1["count"] == p2["count"] == 1
    read = {"hook_event_name": "PostToolUse", "cwd": str(ws), "session_id": "sess-1", "tool_name": "Read", "tool_input": {"file_path": str(ws / "docs" / "a.md"), "offset": 4, "limit": 10}, "tool_response": {"file": {"content": "read excerpt"}}}
    got = daily_sources.observe_claude(root, read)
    assert got["count"] == 1
    records = [json.loads(p.read_text()) for p in (root / ".oks/daily-capture/entries").glob("*.json")]
    record = next(r for r in records if r["role"] == "source")
    assert record["preview"] == "read excerpt"
    assert daily_capture.entry(root, record["id"])["locator"] == {"line_start": 4, "line_count": 10}


def test_codex_truncate_and_malformed_lines_fail_closed(tmp_path):
    root = tmp_path / "kb"; root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "event_msg", "payload": {"type": "task_started"}}) + "\n")
    src = {"id": "codex-one", "kind": "codex-transcript", "host": "codex", "workspace": "repo", "label": "Current", "path": str(transcript), "start_offset": 0}
    daily_sources.connect_source(root, src)
    transcript.write_text("{broken}\n")
    with pytest.raises(ValueError, match="Malformed complete"):
        daily_sources.sync(root, "codex-one")
    cursors = list((root / ".oks/daily-capture/cursors").glob("*.json")) if (root / ".oks/daily-capture/cursors").exists() else []
    assert not cursors or all(json.loads(p.read_text())["offset"] == 0 for p in cursors)


def test_missing_timestamp_retry_after_cursor_write_failure_is_idempotent(tmp_path, monkeypatch):
    root = tmp_path / "kb"; root.mkdir()
    transcript = tmp_path / "session.jsonl"
    src = {"id": "codex-retry", "kind": "codex-transcript", "host": "codex", "workspace": "repo", "label": "Current", "path": str(transcript), "start_offset": 0}
    transcript.write_text("")
    daily_sources.connect_source(root, src)
    row = {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final", "content": [{"type": "output_text", "text": "stable answer"}]}}
    with transcript.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    original = daily_sources.store._atomic_write
    failed = {"done": False}
    def fail_cursor_once(path, data):
        if not failed["done"] and "cursors" in str(path):
            failed["done"] = True
            raise OSError("synthetic cursor write failure")
        return original(path, data)
    monkeypatch.setattr(daily_sources.store, "_atomic_write", fail_cursor_once)
    with pytest.raises(OSError):
        daily_sources.sync(root, "codex-retry")
    monkeypatch.setattr(daily_sources.store, "_atomic_write", original)
    retried = daily_sources.sync(root, "codex-retry")
    assert retried["count"] == 1
    assert len(list((root / ".oks/daily-capture/entries").glob("*.json"))) == 1


def test_disabled_and_oversized_incomplete_line_fail_closed(tmp_path):
    root = tmp_path / "kb"; root.mkdir()
    transcript = tmp_path / "session.jsonl"; transcript.write_text("")
    src = {"id": "codex-disabled", "kind": "codex-transcript", "host": "codex", "workspace": "repo", "label": "Current", "path": str(transcript), "start_offset": 0}
    daily_sources.connect_source(root, src)
    config = daily_sources.load_config(root); config["enabled"] = False
    daily_sources._write_config(root, config)
    transcript.write_text("x" * (daily_sources.MAX_LINE + 20))
    assert daily_sources.sync(root)["status"] == "disabled"


def test_connect_rejects_symlink_and_invalid_source(tmp_path):
    root = tmp_path / "kb"; root.mkdir()
    actual = tmp_path / "real.jsonl"; actual.write_text("")
    link = tmp_path / "link.jsonl"
    try:
        link.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError):
        daily_sources.connect_source(root, {"id": "x", "kind": "codex-transcript", "host": "codex", "workspace": "repo", "label": "x", "path": str(link)})
