"""Tests for the shared snapshot, append, and read-modify-write contracts."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _load_hook_persistence():
    path = Path(__file__).parents[2] / "assets" / "hooks" / "_persistence.py"
    spec = importlib.util.spec_from_file_location("oks_hook_persistence", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_core_jsonl_append_is_complete_under_concurrency(tmp_path):
    from knowledge_studio.store import _append_jsonl

    path = tmp_path / "records" / "events.jsonl"
    lock = tmp_path / ".oks" / "locks" / "events.lock"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: _append_jsonl(path, {"i": i}, lock_path=lock), range(32)))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(item["i"] for item in records) == list(range(32))


def test_core_read_modify_write_keeps_all_updates(tmp_path):
    from knowledge_studio.store import _atomic_write, _locked_atomic_update

    path = tmp_path / "state.json"
    lock = tmp_path / ".oks" / "locks" / "state.lock"
    _atomic_write(path, json.dumps({"count": 0}))

    def increment(current: str) -> str:
        state = json.loads(current)
        state["count"] += 1
        return json.dumps(state)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _locked_atomic_update(path, increment, lock_path=lock), range(32)))

    assert json.loads(path.read_text(encoding="utf-8"))["count"] == 32


def test_standalone_hook_persistence_matches_contract(tmp_path):
    persistence = _load_hook_persistence()
    snapshot = tmp_path / ".oks" / "state.json"
    persistence.atomic_write_text(snapshot, '{"ok": true}\n')
    assert snapshot.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert not list(snapshot.parent.glob("*.tmp"))

    records = tmp_path / "records" / "inject.jsonl"
    lock = tmp_path / ".oks" / "locks" / "inject.lock"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda i: persistence.append_jsonl(records, {"i": i}, lock_path=lock),
            range(16),
        ))
    values = [json.loads(line)["i"] for line in records.read_text(encoding="utf-8").splitlines()]
    assert sorted(values) == list(range(16))
