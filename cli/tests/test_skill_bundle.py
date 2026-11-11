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
    assert not (tmp_path / "skills/oh-my-oks").exists()
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


def test_global_install_without_kb_preserves_existing_package(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    args = ['skills-install', '--global', '--editor', 'codex']
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    installed = json.loads(result.output)
    dest = home / '.codex/skills/oh-my-oks'
    assert installed['path'] == str(dest)
    assert (dest / 'references/onboarding.md').is_file()
    assert not (tmp_path / 'wiki').exists()
    (dest / 'SKILL.md').write_text('# customized')
    (dest / 'references/onboarding.md').unlink()
    result = runner.invoke(app, args)
    assert json.loads(result.output)['status'] == 'preserved'
    assert (dest / 'SKILL.md').read_text() == '# customized'
    assert not (dest / 'references/onboarding.md').exists()
    result = runner.invoke(app, args + ['--force'])
    assert result.exit_code == 0, result.output
    saved = json.loads(result.output)
    assert (Path(saved['backup']) / 'SKILL.md').read_text() == '# customized'
    assert (dest / 'references/onboarding.md').is_file()
    assert not (home / '.claude').exists()


def test_global_install_respects_codex_home_and_rejects_symlink(tmp_path, monkeypatch):
    import pytest
    base = Path(__file__).resolve().parents[2] / 'assets'
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'custom-codex'))
    result = skill_bundle.install_global(base, 'codex')
    dest = Path(result['path'])
    assert dest == tmp_path / 'custom-codex/skills/oh-my-oks'
    other = tmp_path / 'foreign'
    other.mkdir()
    # Replace the package with a link; a force request must not write through it.
    import shutil
    shutil.rmtree(dest)
    dest.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match='link'):
        skill_bundle.install_global(base, 'codex', overwrite=True)
    assert not list(other.iterdir())
    with pytest.raises(ValueError):
        skill_bundle.install_global(base, 'workbuddy')
