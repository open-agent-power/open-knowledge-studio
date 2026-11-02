"""Synthetic temporary-KB Skill version tests; review timestamps below are test fixtures, not real human approval."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knowledge_studio import skills, store, tasks
from knowledge_studio.cli import app


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_ROOT", str(root))
    return root


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nVersion one.\n", encoding="utf-8")
    (folder / "notes.txt").write_text("unchanged\n", encoding="utf-8")
    return folder


def _promote(result):
    return store.get_wiki_page(store.promote_draft(result["entry"]["slug"]))


def test_list_and_compare_versions_include_pending_state_and_bounded_text_diff(kb, source):
    # Promotion uses the repository's human-review pathway, but this is test-only fixture data.
    old = _promote(skills.import_skill(source))
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nVersion two.\n", encoding="utf-8")
    pending = skills.import_skill(source)["entry"]

    listing = skills.list_versions(kb, "sample")
    assert listing["schema_version"] == "skill-versions/v1"
    assert {v["version"] for v in listing["versions"]} == {old["skill_version"], pending["skill_version"]}
    assert any(v["review_state"] == "pending_review" for v in listing["versions"])
    compared = skills.compare_versions(kb, "sample", old["skill_version"], pending["skill_version"])
    assert compared["from"]["review_state"] == "reviewed"
    assert compared["to"]["review_state"] == "pending_review"
    change = next(row for row in compared["changes"] if row["path"] == "SKILL.md")
    assert change["status"] == "modified"
    assert "-Version one." in change["unified_diff"]
    assert "\x00" not in change["unified_diff"]
    with pytest.raises(ValueError, match="full 64-character"):
        skills.compare_versions(kb, "sample", old["skill_version"][:12], pending["skill_version"])


def test_diff_omits_when_large_old_side_is_compared_to_small_new_side(kb, source):
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\n" + "x" * (64 * 1024), encoding="utf-8")
    old = skills.import_skill(source)["entry"]
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nShort update.\n", encoding="utf-8")
    new = skills.import_skill(source)["entry"]
    result = skills.compare_versions(kb, "sample", old["skill_version"], new["skill_version"])
    change = next(row for row in result["changes"] if row["path"] == "SKILL.md")
    assert change["unified_diff"] is None
    assert change["diff_omitted_reason"] == "one side exceeds 64 KiB text diff limit"


def test_diff_omits_pathological_line_count_before_difflib(kb, source):
    header = "---\nname: sample\ndescription: fixture\n---\n\n"
    (source / "SKILL.md").write_text(header + "".join(f"line-{i}\n" for i in range(2100)), encoding="utf-8")
    old = skills.import_skill(source)["entry"]
    (source / "SKILL.md").write_text(header + "".join(f"updated-{i}\n" for i in range(2100)), encoding="utf-8")
    new = skills.import_skill(source)["entry"]
    result = skills.compare_versions(kb, "sample", old["skill_version"], new["skill_version"])
    change = next(row for row in result["changes"] if row["path"] == "SKILL.md")
    assert change["unified_diff"] is None
    assert change["diff_omitted_reason"] == f"one side exceeds {skills.MAX_DIFF_LINES} line diff limit"


def test_cli_versions_diff_and_old_version_load_after_update(kb, source):
    runner = CliRunner()
    first_import = runner.invoke(app, ["skills", "import", str(source), "--id", "sample"])
    assert first_import.exit_code == 0, first_import.output
    old = _promote(json.loads(first_import.output))
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nUpdated.\n", encoding="utf-8")
    second_import = runner.invoke(app, ["skills", "import", str(source), "--id", "sample"])
    assert second_import.exit_code == 0, second_import.output
    new = _promote(json.loads(second_import.output))
    versions = runner.invoke(app, ["skills", "versions", "sample"])
    assert versions.exit_code == 0, versions.output
    assert old["skill_version"] in versions.output and new["skill_version"] in versions.output
    listing = json.loads(versions.output)
    assert next(v for v in listing['versions'] if v['version'] == old['skill_version'])['review_state'] == 'superseded'
    diff = runner.invoke(app, ["skills", "diff", "sample", "--from-version", old["skill_version"], "--to-version", new["skill_version"]])
    assert diff.exit_code == 0, diff.output
    diff_data = json.loads(diff.output)
    assert diff_data["change_count"] == 1
    assert all(host["recovery_commands"] == [f"oks skills load sample --version {old['skill_version']} --target {host['host']}"]
               for host in diff_data["recovery"]["hosts"] if host["state"] == "not_loaded")
    loaded = runner.invoke(app, ["skills", "load", "sample", "--version", old["skill_version"]])
    assert loaded.exit_code == 0, loaded.output
    assert json.loads(loaded.output)["entry"]["skill_version"] == old["skill_version"]


def test_comparison_reports_current_task_old_binding_and_unverified_use(kb, source):
    old = _promote(skills.import_skill(source))
    goal = kb / "profiles/goals"
    goal.mkdir(parents=True)
    (goal / "work.md").write_text("---\ntype: goal\n---\n\nFixture goal.\n", encoding="utf-8")
    tasks.start(kb, "task-one", "profiles/goals/work.md", [Path(old["file_path"]).relative_to(kb).as_posix()])
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nUpdated.\n", encoding="utf-8")
    new = _promote(skills.import_skill(source))
    result = skills.compare_versions(kb, "sample", old["skill_version"], new["skill_version"])
    task = result["affected_tasks"][0]
    assert task["task_id"] == "task-one"
    assert task["comparison_status"] == "needs_review"
    assert task["binding"] == "bound_to_old_version"
    assert task["task_status"] == "needs_review"
    assert task["uses"] == []
    assert result["recovery"]["load_command"] == f"oks skills load sample --version {old['skill_version']}"


@pytest.mark.parametrize("damage", ["missing_package", "corrupt_package"])
def test_missing_or_corrupt_immutable_package_is_diagnostic(kb, source, damage):
    page = _promote(skills.import_skill(source))
    package = kb / page["skill_package"]
    if damage == "missing_package":
        package.unlink()
    else:
        package.write_bytes(b"not a zip")
    result = skills.list_versions(kb, "sample")
    card = result["versions"][0]["cards"][0]
    assert card["integrity"] == "failed"
    assert card["integrity_issue"]
    with pytest.raises(ValueError, match="No intact Skill package"):
        skills.compare_versions(kb, "sample", page["skill_version"], page["skill_version"])


def test_modified_host_copy_has_no_destructive_recovery_command(kb, source):
    page = _promote(skills.import_skill(source))
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: fixture\n---\n\nUpdated.\n", encoding="utf-8")
    new = _promote(skills.import_skill(source))
    host = Path(skills.load("sample", version=page["skill_version"], host="agents")["host_path"])
    unchanged = skills.compare_versions(kb, "sample", page["skill_version"], new["skill_version"])
    state = next(host_state for host_state in unchanged["recovery"]["hosts"] if host_state["host"] == "agents")
    assert state["state"] == "unchanged_managed"
    assert state["recovery_commands"] == ["oks skills unload sample --target agents", f"oks skills load sample --version {page['skill_version']} --target agents"]
    (host / "SKILL.md").write_text("local edit\n", encoding="utf-8")
    result = skills.compare_versions(kb, "sample", page["skill_version"], new["skill_version"])
    state = next(host for host in result["recovery"]["hosts"] if host["host"] == "agents")
    assert state["state"] == "modified_managed"
    assert state["recovery_commands"] == []
    assert "never overwritten" in state["note"]
