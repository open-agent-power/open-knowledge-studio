import pytest
from knowledge_studio.vfs import VfsError
from knowledge_studio.vfs_observation import execute, history


def test_read_is_equivalent_with_nested_real_spans_and_private_content_not_logged(
    tmp_path,
):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_text("# private\n中文 content")
    data = execute(tmp_path, "compare", "oks://wiki/a.md", offset=2, limit=7)
    assert data["result"]["content"] == "private"
    record = data["trace"]
    assert record["comparison"]["equivalent"] is True
    assert record["output_bytes"] > 0 and record["model_tokens"] is None
    assert record["spans"][0]["parent_id"] is None
    assert all(s["duration_ms"] >= 0 for s in record["spans"])
    assert all(
        s["start_ms"] + s["duration_ms"] <= record["total_ms"] for s in record["spans"]
    )
    assert all(s["parent_id"] is not None for s in record["spans"][1:])
    assert "private" not in (tmp_path / "records/observability/vfs.json").read_text()
    assert history(tmp_path)["records"][0]["id"] == record["id"]


def test_failure_and_missing_mount_do_not_create_knowledge_files(tmp_path):
    with pytest.raises(VfsError):
        execute(tmp_path, "read", "oks://wiki/nope.md")
    assert history(tmp_path)["records"][0]["status"] == "failed"
    assert not (tmp_path / "wiki").exists()
    names = {e["name"] for e in execute(tmp_path, "ls", "oks://")["result"]["entries"]}
    assert {"profiles", "skills"} <= names
    assert "host-skills" not in names
    assert not {"goal", "discuss", "skill"} & names


def test_boundary_rejection_is_retained_as_failed_trace(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/out.md").symlink_to("/etc/passwd")
    with pytest.raises(VfsError):
        execute(tmp_path, "read", "oks://wiki/out.md")
    assert history(tmp_path)["records"][0]["error_code"] == "SYMLINK_NOT_ALLOWED"


def test_ordinary_fs_cli_has_observation_without_changing_schema(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from knowledge_studio.cli import app

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_text("# evidence")
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    result = CliRunner().invoke(
        app, ["fs", "read", "oks://wiki/a.md", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert data["schema_version"] == "oks-fs-response/v1"
    assert history(tmp_path)["records"][0]["operation"] == "read"


def test_recall_exposes_real_spans_without_persisting_query_or_using_wiki(
    tmp_path, monkeypatch
):
    from knowledge_studio.recall import recall

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_text(
        "---\ntitle: Evidence\ntype: concept\narea: computing\n---\nQuartz evidence"
    )
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    result = recall(
        "quartz private-query",
        knowledge_only=True,
        use_task=False,
        goal="none",
        search_backend="native",
    )
    trace = result["diagnostics"]["call_trace"]
    assert trace["kind"] == "recall" and len(trace["spans"]) == 6
    assert all(
        s["start_ms"] + s["duration_ms"] <= trace["total_ms"] for s in trace["spans"]
    )
    assert history(tmp_path, "recall")["records"][0]["id"] == trace["id"]
    assert (
        "private-query"
        not in (tmp_path / "records/observability/recall.json").read_text()
    )
    assert not (tmp_path / ".oks/access.json").exists()
