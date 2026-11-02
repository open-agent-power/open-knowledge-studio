from __future__ import annotations

import json

from knowledge_studio.retrieval_audit import report


def test_report_uses_explicit_root_settings_and_does_not_probe(tmp_path, monkeypatch):
    root = tmp_path / "knowledge-base"
    settings = root / "settings"
    settings.mkdir(parents=True)
    config = settings / "recall.yaml"
    config.write_text("search_backend: fusion\n", encoding="utf-8")
    wiki = root / "wiki"
    wiki.mkdir()
    private = wiki / "private.md"
    private.write_text("query secret", encoding="utf-8")
    monkeypatch.setenv("OKS_SEARCH_BACKEND", "native")

    before = {path: path.stat().st_mtime_ns for path in (config, private)}
    result = report(root)

    assert result["configured_backend"] == "fusion"
    assert result["configuration_source"] == "settings/recall.yaml"
    assert result["actual_backend"] == "not_probed"
    assert "observed" not in result
    assert {path: path.stat().st_mtime_ns for path in before} == before
    assert "query secret" not in json.dumps(result)


def test_default_is_fts5_and_skill_entry_declares_forced_backend(tmp_path):
    result = report(tmp_path)
    assert result["configured_backend"] == "fts5"
    assert result["configuration_source"] == "code_default"
    skill = next(item for item in result["entries"] if item["id"] == "skill-search")
    assert "Forced fts5" in skill["configuration"]
    assert "Never selected" in skill["native_condition"]


def test_unknown_config_is_reported_without_claiming_fallback(tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "recall.yaml").write_text("search_backend: my-custom-backend\n", encoding="utf-8")

    result = report(tmp_path)
    recall_entry = next(item for item in result["entries"] if item["id"] == "cli-recall")
    assert result["configured_backend"] == "my-custom-backend"
    assert "Unknown/unavailable backend raises an error" in recall_entry["error"]
    assert "no Native fallback" in recall_entry["error"]
    assert result["actual_backend"] == "not_probed"


def test_observation_is_separate_and_filters_sensitive_diagnostic_text(tmp_path):
    result = report(
        tmp_path,
        {
            "requested_backend": "fts5",
            "actual_backends": ["like", 17, "native"],
            "fallback_reason": "sqlite_fts5_unavailable",
            "fallback_error": "ValueError: C:\\private\\secret query words",
            "query": "do not return",
            "wiki_path": "C:\\private\\wiki",
            "stderr": "sensitive output",
        },
    )

    assert result["actual_backend"] == "not_probed"
    assert result["observed"] == {
        "requested_backend": "fts5",
        "actual_backends": ["like", "native"],
        "fallback_reason": "sqlite_fts5_unavailable",
        "fallback_error": "ValueError",
    }
    serialized = json.dumps(result)
    assert "do not return" not in serialized
    assert "private" not in serialized
    assert "sensitive output" not in serialized


def test_report_includes_entry_contract_fields_and_source_functions(tmp_path):
    result = report(tmp_path)
    expected = {"id", "title", "configuration", "empty", "error", "native_condition", "sources"}
    assert result["entries"]
    for entry in result["entries"]:
        assert expected <= entry.keys()
        assert entry["sources"]
        assert all(set(source) == {"file", "function"} for source in entry["sources"])
