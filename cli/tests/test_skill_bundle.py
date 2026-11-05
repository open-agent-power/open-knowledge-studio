from pathlib import Path
import hashlib
import json
from typer.testing import CliRunner
from knowledge_studio import skill_bundle
from knowledge_studio.cli import app


def test_consolidation_archives_managed_packages_and_keeps_user_skills(tmp_path):
    base = Path(__file__).resolve().parents[2] / "assets"
    for name in ["query", "office", "my-project"]:
        folder = tmp_path / ".agents/skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("# " + name)
    original = (tmp_path / ".agents/skills/office/SKILL.md").read_bytes()
    result = skill_bundle.consolidate(tmp_path, base, [".agents"])
    assert result["status"] == "completed" and len(result["items"]) == 2
    assert (tmp_path / ".agents/skills/my-project/SKILL.md").exists()
    assert not (tmp_path / ".agents/skills/query").exists()
    item = next(i for i in result["items"] if i["from"].endswith("office"))
    assert (tmp_path / item["to"] / "SKILL.md").read_bytes() == original
    assert item["files"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert (
        skill_bundle.consolidate(tmp_path, base, [".agents"])["status"] == "unchanged"
    )


def test_force_updates_only_managed_files_and_keeps_custom_skill(tmp_path, monkeypatch):
    (tmp_path / "wiki").mkdir()
    custom = tmp_path / ".agents/skills/my-project/SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("# custom")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["skills-install", "--force"])
    assert result.exit_code == 0, result.output
    assert custom.read_text() == "# custom"
    assert (tmp_path / ".agents/skills/oh-my-oks/SKILL.md").exists()
    assert (tmp_path / "skills/oh-my-oks/references/context.md").exists()
    assert not (tmp_path / ".agents/skills/office").exists()
    result = CliRunner().invoke(app, ["skills-install", "--all-bundled"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".agents/skills/office/SKILL.md").exists()
    assert custom.read_text() == "# custom"


def test_vfs_skills_does_not_fall_back_to_host_installations(tmp_path):
    import pytest
    from knowledge_studio.vfs import VfsResolver, VfsError

    old = tmp_path / ".agents/skills/query/SKILL.md"
    old.parent.mkdir(parents=True)
    old.write_text("# host")
    resolver = VfsResolver(tmp_path)
    with pytest.raises(VfsError):
        resolver.resolve("oks://skills/query/SKILL.md")
    assert resolver.resolve("oks://host-skills/query/SKILL.md").path == old
