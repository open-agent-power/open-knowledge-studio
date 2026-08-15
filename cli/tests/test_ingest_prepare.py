import json
from hashlib import sha256
from pathlib import Path

from knowledge_studio.ingest_prepare import prepare_ingest


def _source_envelope(result: dict) -> dict:
    path = Path(result["manifest_dir"]) / "source-envelope.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_remote_source_requires_explicit_processing_decision(tmp_path):
    result = prepare_ingest("https://example.com/private?token=sample", kb_root=tmp_path)

    assert _source_envelope(result)["policy"]["remote_processing"] == "ask"


def test_local_source_denies_remote_processing_by_default(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("local knowledge", encoding="utf-8")

    result = prepare_ingest(str(source), kb_root=tmp_path)

    assert _source_envelope(result)["policy"]["remote_processing"] == "deny"


def test_binary_source_hashes_file_bytes_not_its_path(tmp_path):
    source = tmp_path / "scan.pdf"
    payload = b"%PDF-1.4\ntruth lives in the bytes\n"
    source.write_bytes(payload)

    result = prepare_ingest(str(source), kb_root=tmp_path)

    assert _source_envelope(result)["content_hash"] == sha256(payload).hexdigest()


def test_binary_source_hash_changes_when_same_path_content_changes(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"first version")
    first = _source_envelope(prepare_ingest(str(source), kb_root=tmp_path))["content_hash"]

    source.write_bytes(b"second version")
    second = _source_envelope(prepare_ingest(str(source), kb_root=tmp_path))["content_hash"]

    assert first != second


def test_local_policy_excludes_external_provider_candidates(tmp_path, monkeypatch):
    source = tmp_path / "notes.txt"
    source.write_text("local knowledge", encoding="utf-8")

    monkeypatch.setattr(
        "knowledge_studio.capability_commands.capability_status",
        lambda: {
            "by_action": {"document.text.extract": ["local", "remote"]},
            "providers": [
                {"id": "local", "execution": "managed", "status": "ready"},
                {"id": "remote", "execution": "external", "status": "ready"},
            ],
        },
    )

    result = prepare_ingest(str(source), kb_root=tmp_path)

    assert [provider["id"] for provider in result["candidate_providers"]] == ["local"]
