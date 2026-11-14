"""Tests for `oks init` — instance scaffolding + asset materialization."""
import json
from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

import knowledge_studio.cli as cli_module
from knowledge_studio.cli import app

runner = CliRunner()

# Contract: what `oks init` must produce. Buckets come from _INSTANCE_DIRS; the
# per-agent dirs, missing settings and the context index come from assets/.
EXPECTED_BUCKETS = [
    "profiles/discuss", "skills", "records/studio",
    "profiles/users", "profiles/projects", "profiles/recipes", "profiles/goals",
    "raw", "wiki", "drafts",
]
EXPECTED_TOP_LEVEL = {
    ".claude", ".qoder", ".pi", ".codex", ".agents", ".codebuddy", ".workbuddy", "settings",
    "profiles", "raw", "wiki", "drafts", "mail", "skills", "records", ".gitignore", "AGENTS.md", "README.md",
}


def test_maintainer_skills_live_outside_assets():
    """Physical separation replaces ignore rules: dev tooling is not in assets/.

    Everything under assets/ ships to users, so maintainer skills must not be
    there. They stay in the repo's own .claude/ for development.
    """
    repo_root = Path(__file__).parents[2]
    shipped = {entry.name for entry in (repo_root / "assets" / "skills").iterdir()}
    assert {"ingest", "query", "promote"} <= shipped


def test_both_build_paths_use_shared_asset_assembly():
    """The workflow and setuptools must use the same assembly implementation."""
    cli_dir = Path(__file__).parents[1]
    sources = {
        "bundle_assets.py": (cli_dir / "scripts" / "bundle_assets.py").read_text(encoding="utf-8"),
        "setup.py": (cli_dir / "setup.py").read_text(encoding="utf-8"),
    }
    for name, source in sources.items():
        assert "from _build_assets import bundle_assets" in source
        assert "shutil.copytree" not in source


@pytest.mark.parametrize("bundled", [False, True])
def test_installed_assets_ignore_an_unrelated_parent_checkout(tmp_path, monkeypatch, bundled):
    checkout = tmp_path / "project"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "assets").mkdir()
    package = checkout / ".venv" / "Lib" / "site-packages" / "knowledge_studio"
    package.mkdir(parents=True)
    module = package / "cli.py"
    module.write_text("# installed module", encoding="utf-8")
    if bundled:
        assets = package / "_assets"
        assets.mkdir()
        (assets / "marker.txt").write_text("wheel asset", encoding="utf-8")
    monkeypatch.setattr(cli_module, "__file__", str(module))

    assert cli_module._asset_source() == (package / "_assets" if bundled else None)


@pytest.mark.parametrize("git_metadata", ["directory", "file", "archive"])
def test_source_assets_take_precedence_over_generated_copies(tmp_path, monkeypatch, git_metadata):
    source = tmp_path / "source"
    assets = source / "assets"
    assets.mkdir(parents=True)
    package = source / "cli" / "knowledge_studio"
    package.mkdir(parents=True)
    module = package / "cli.py"
    module.write_text("# source module", encoding="utf-8")
    generated = package / "_assets"
    generated.mkdir()
    (generated / "stale.txt").write_text("stale build", encoding="utf-8")
    if git_metadata == "directory":
        (source / ".git").mkdir()
    elif git_metadata == "file":
        (source / ".git").write_text("gitdir: ../common.git", encoding="utf-8")
    monkeypatch.setattr(cli_module, "__file__", str(module))

    assert cli_module._asset_source() == assets


def test_init_never_materializes_dev_only_skills(tmp_path):
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0

    skills = target / ".claude" / "skills"
    installed = {entry.name for entry in skills.iterdir()} if skills.is_dir() else set()
    assert "review-upstream-pr" not in installed
    assert "upstream-pr-remediation" not in installed
    # User-facing skills still arrive.
    assert installed == {"oh-my-oks"}


def test_init_assembles_each_agent_ecosystem(tmp_path):
    """Single-source components are composed per agent target."""
    from knowledge_studio.cli import _AGENT_TARGETS

    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0

    for dest_name, spec in _AGENT_TARGETS.items():
        dest = target / dest_name
        assert dest.is_dir(), f"{dest_name} was not assembled"
        assert (dest / "skills").is_dir() is bool(spec["skills"] or spec.get("skill_names"))
        assert (dest / "hooks").is_dir() is spec["hooks"]
        assert (dest / "rules").is_dir() is spec["rules"]

    # Per-agent config lands at the ecosystem root, not under a nested dir.
    assert (target / ".claude" / "settings.json").is_file()
    assert (target / ".codex" / "hooks.json").is_file()
    for directory in (".codebuddy", ".workbuddy"):
        assert (target / directory / "README.md").is_file()
    assert (target / ".codebuddy" / "skills" / "oks-knowledge" / "SKILL.md").is_file()
    assert not (target / ".workbuddy" / "skills").exists()
    assert not (target / ".codebuddy" / "skills" / "promote").exists()


def test_skills_install_adds_workbuddy_skill_to_existing_instances(tmp_path, monkeypatch):
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0
    shutil.rmtree(target / ".codebuddy")
    monkeypatch.chdir(target)

    result = runner.invoke(app, ["skills-install"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert (target / ".codebuddy" / "skills" / "oks-knowledge" / "SKILL.md").is_file()
    assert not (target / ".codebuddy" / "skills" / "promote").exists()


def test_asset_materialization_and_legacy_install_skip_generated_bytecode(tmp_path, monkeypatch):
    base = tmp_path / "packaged-assets"
    skill = base / "skills" / "oh-my-oks"
    cache = skill / "scripts/__pycache__"
    cache.mkdir(parents=True)
    (cache / "run.cpython-314.pyc").write_bytes(b"generated cache")
    (skill / "SKILL.md").write_text("# Sample", encoding="utf-8")
    (skill / "scripts/run.py").write_text("print('sample')", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_asset_source", lambda: base)
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0
    for host in (".agents", ".claude", ".qoder"):
        installed = target / host / "skills/oh-my-oks"
        assert (installed / "scripts/run.py").exists()
        assert not (installed / "scripts/__pycache__").exists()
    other = tmp_path / "legacy-kb"
    (other / "wiki").mkdir(parents=True)
    monkeypatch.chdir(other)
    assert runner.invoke(app, ["skills-install"]).exit_code == 0
    assert (other / ".agents/skills/oh-my-oks/scripts/run.py").exists()
    assert not (other / ".agents/skills/oh-my-oks/scripts/__pycache__").exists()


def test_workbuddy_skill_requires_read_only_cli_recall(tmp_path):
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0

    skill = (target / ".codebuddy" / "skills" / "oks-knowledge" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert 'oks recall "<query>" --knowledge-only --format json --limit 3' in skill
    assert 'oks fs read "<oks-uri>" --format json' in skill
    assert "human_reviewed_at" in skill
    assert "`uri` (not `oks_uri`)" in skill
    assert "oks raw-commit" in skill


def test_hook_install_refreshes_persistence_support_file_and_stale_engine(tmp_path):
    """Old instances receive support files and the current hook protocol."""
    from knowledge_studio.cli import _ensure_recall_scripts

    target = tmp_path / "kb"
    hooks = target / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "user-prompt-recall.py").write_text("old\n", encoding="utf-8")
    (hooks / "post-tool-edit.py").write_text("old\n", encoding="utf-8")

    created = _ensure_recall_scripts(target)

    assert "_persistence.py" in created
    assert (hooks / "_persistence.py").is_file()
    assert "old\n" != (hooks / "user-prompt-recall.py").read_text(encoding="utf-8")
    assert "old\n" != (hooks / "post-tool-edit.py").read_text(encoding="utf-8")
    assert "independent from knowledge recall" in (hooks / "user-prompt-recall.py").read_text(encoding="utf-8")


def test_init_recommends_the_current_ingest_command(tmp_path):
    target = tmp_path / "kb"

    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])

    assert result.exit_code == 0, result.output
    assert "oks ingest prepare" in result.output
    assert "--mode quick" not in result.output


def test_init_scaffolds_buckets_and_data_gitignore(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output

    for d in EXPECTED_BUCKETS:
        assert (target / d).is_dir(), f"missing bucket {d}"

    gi = (target / ".gitignore").read_text(encoding="utf-8")
    # instance gitignore ignores only per-machine state, and TRACKS memory
    assert ".oks/" in gi
    assert "wiki/**/*.md" not in gi
    assert "drafts/*.md" not in gi


def test_init_structure_matches_contract_exactly(tmp_path):
    """Guard against silent drift between `oks init` and the documented layout."""
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output

    assert {entry.name for entry in target.iterdir()} == EXPECTED_TOP_LEVEL
    # A fresh instance carries no execution traces or proposals: those paths are
    # created on first use, so users who never trace never see the directories.
    assert not (target / "raw" / "executions").exists()
    assert not (target / "drafts" / "proposals").exists()


def test_trace_and_proposal_paths_are_created_on_demand(tmp_path, monkeypatch):
    """`oks trace` must work on a freshly initialized instance."""
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0
    monkeypatch.setenv("OKS_ROOT", str(target))

    from knowledge_studio.proposals import create_proposal
    from knowledge_studio.trace import start_trace

    start_trace("goal-init", "run-init")
    run_dir = target / "raw" / "executions" / "run-init"
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "run.json").is_file()

    proposal = create_proposal("run-init", "wiki", "Init lesson", "Scaffold works.")
    assert proposal.parent == target / "drafts" / "proposals" / "wiki"


def test_init_materializes_shareable_assets(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output

    # Only operational assets arrive; schemas/templates stay with the tool.
    assert (target / ".claude" / "skills" / "oh-my-oks").is_dir()
    assert not (target / ".claude" / "skills" / "office").exists()
    assert not (target / "skills" / "oh-my-oks").exists()
    assert (target / ".claude" / "settings.json").is_file()
    assert not (target / "templates").exists()
    assert not (target / "_meta").exists()
    assert (target / "settings" / "capabilities" / "video.watch.json").is_file()
    assert (target / "profiles" / "INDEX.md").is_file()
    assert not (target / "profiles" / "team.md").exists()
    assert not (target / "profiles" / "goals" / "team.md").exists()
    assert not list((target / "profiles" / "recipes").glob("*.md"))



def test_init_upgrade_refreshes_assets_but_keeps_user_files(tmp_path):
    target = tmp_path / "kb"
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])

    marker = target / ".claude" / "MARKER.txt"
    marker.write_text("local edit", encoding="utf-8")

    bundled = target / ".claude" / "rules" / "wiki-writing.md"
    original = bundled.read_text(encoding="utf-8")
    bundled.write_text("stale\n", encoding="utf-8")

    # Editor config holds live hook wiring, so an upgrade must not restore it.
    wiring = target / ".claude" / "settings.json"
    wiring.write_text("{}", encoding="utf-8")

    # re-init without --upgrade keeps existing assets untouched
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert marker.exists()
    assert bundled.read_text(encoding="utf-8") == "stale\n"

    # --upgrade merge-copies bundled assets: bundled files refreshed,
    # user-owned files (marker) survive — no more whole-tree deletion
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default", "--upgrade"])
    assert marker.exists()
    assert bundled.read_text(encoding="utf-8") == original
    assert wiring.read_text(encoding="utf-8") == "{}"


def test_init_requires_path_argument():
    result = runner.invoke(app, ["init"])
    assert result.exit_code != 0


def test_init_aborts_on_nonempty_non_kb_dir(tmp_path):
    target = tmp_path / "documents"
    target.mkdir()
    (target / "important.txt").write_text("do not touch", encoding="utf-8")

    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 1
    assert not (target / "wiki").exists()

    # --force overrides the guard
    result = runner.invoke(
        app, ["init", str(target), "--no-git", "--no-set-default", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert (target / "wiki").is_dir()
    assert (target / "important.txt").exists()


def test_init_rerun_on_existing_kb_is_idempotent(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output


def test_team_init_creates_profile_without_inventing_active_goal(tmp_path):
    target = tmp_path / "team-knowledge-studio"

    result = runner.invoke(
        app,
        [
            "team",
            "init",
            str(target),
            "--name",
            "Platform Knowledge Team",
            "--no-git",
            "--no-set-default",
        ],
    )

    assert result.exit_code == 0, result.output
    profile = (target / "profiles" / "team.md").read_text(encoding="utf-8")
    assert not (target / "profiles" / "goals" / "team.md").exists()
    assert 'title: "Platform Knowledge Team"' in profile
    assert "# Platform Knowledge Team" in profile
    assert "settings/sources.yaml" in result.output


def test_team_init_rerun_preserves_custom_profile(tmp_path):
    target = tmp_path / "team-knowledge-studio"
    args = ["team", "init", str(target), "--no-git", "--no-set-default"]
    assert runner.invoke(app, args).exit_code == 0

    profile_path = target / "profiles" / "team.md"
    goal_path = target / "profiles" / "goals" / "team.md"
    profile_path.write_text("---\ntitle: Custom Team\n---\n\n# Custom Team\n", encoding="utf-8")
    goal_path.write_text("---\ntitle: Custom Goal\n---\n\n# Custom Goal\n", encoding="utf-8")
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert profile_path.read_text(encoding="utf-8").startswith("---\ntitle: Custom Team")
    assert goal_path.read_text(encoding="utf-8").startswith("---\ntitle: Custom Goal")


def test_team_init_upgrade_preserves_custom_profile_and_goal(tmp_path):
    target = tmp_path / "team-knowledge-studio"
    args = ["team", "init", str(target), "--no-git", "--no-set-default"]
    assert runner.invoke(app, args).exit_code == 0

    profile_path = target / "profiles" / "team.md"
    goal_path = target / "profiles" / "goals" / "team.md"
    profile_path.write_text('---\ntitle: "Custom: Team"\n---\n\n# Custom Team\n', encoding="utf-8")
    goal_path.write_text('---\ntitle: "Custom: Goal"\n---\n\n# Custom Goal\n', encoding="utf-8")
    result = runner.invoke(app, [*args, "--upgrade"])

    assert result.exit_code == 0, result.output
    assert profile_path.read_text(encoding="utf-8").startswith('---\ntitle: "Custom: Team"')
    assert goal_path.read_text(encoding="utf-8").startswith('---\ntitle: "Custom: Goal"')


def test_team_init_quotes_yaml_unsafe_name(tmp_path):
    target = tmp_path / "team-knowledge-studio"
    result = runner.invoke(
        app,
        [
            "team",
            "init",
            str(target),
            "--name",
            'Team: "Quoted"',
            "--no-git",
            "--no-set-default",
        ],
    )

    assert result.exit_code == 0, result.output
    import yaml

    profile = yaml.safe_load((target / "profiles" / "team.md").read_text(encoding="utf-8").split("---")[1])
    assert not (target / "profiles" / "goals" / "team.md").exists()
    assert profile["title"] == 'Team: "Quoted"'


def test_team_init_fallback_without_bundled_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_asset_source", lambda: None)
    target = tmp_path / "team-knowledge-studio"
    result = runner.invoke(
        app,
        ["team", "init", str(target), "--no-git", "--no-set-default"],
    )

    assert result.exit_code == 0, result.output
    assert (target / "profiles" / "team.md").is_file()
    assert not (target / "profiles" / "goals" / "team.md").exists()

    # target now contains wiki/ → treated as an existing KB, no --force needed
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output


# ── active KB pointer ────────────────────────────────────────────────

@pytest.fixture
def _isolated_config(tmp_path, monkeypatch):
    """Point ~/.oks at a temp dir so these tests cannot touch the real config."""
    import knowledge_studio.config as _cfg

    home = tmp_path / "home" / ".oks"
    home.mkdir(parents=True)
    monkeypatch.setattr(_cfg, "config_dir", lambda: home)
    return home / "config.json"


def test_init_does_not_silently_repoint_an_existing_active_kb(_isolated_config, tmp_path):
    """A throwaway instance must not hijack where the user's memory is written.

    Overwriting knowledge_base_path loses the old path for good, and every
    later `oks ingest` / `oks wiki create` would land in the scratch folder.
    """
    real_kb = tmp_path / "real"
    result = runner.invoke(app, ["init", str(real_kb), "--no-git", "--set-default"])
    assert result.exit_code == 0, result.output

    scratch = tmp_path / "scratch"
    result = runner.invoke(app, ["init", str(scratch), "--no-git"])
    assert result.exit_code == 0, result.output

    config = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert config["knowledge_base_path"] == str(real_kb.resolve()), (
        f"active KB was silently repointed: {config['knowledge_base_path']}"
    )
    assert "--set-default" in result.output, (
        f"the user was not told how to switch:\n{result.output}"
    )


def test_init_set_default_still_switches_explicitly(_isolated_config, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    runner.invoke(app, ["init", str(first), "--no-git", "--set-default"])
    result = runner.invoke(app, ["init", str(second), "--no-git", "--set-default"])
    assert result.exit_code == 0, result.output

    config = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert config["knowledge_base_path"] == str(second.resolve())


def test_init_adopts_when_no_active_kb_is_registered(_isolated_config, tmp_path):
    target = tmp_path / "first-ever"
    result = runner.invoke(app, ["init", str(target), "--no-git"])
    assert result.exit_code == 0, result.output

    config = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert config["knowledge_base_path"] == str(target.resolve())


def test_qoder_no_hooks_dir_but_runs_via_claude_hooks(tmp_path):
    """plan A (qoder-cli): _AGENT_TARGETS['.qoder']['hooks']=False.
    .qoder/ no longer gets a hooks/ dir (dead weight — settings.json
    points to .claude/hooks), but qoder config + skills still install."""
    from knowledge_studio.cli import _AGENT_TARGETS
    assert _AGENT_TARGETS[".qoder"]["hooks"] is False, "plan A: .qoder hooks should be disabled"
    assert _AGENT_TARGETS[".qoder"]["skills"] is True, "qoder skills still install"
    assert _AGENT_TARGETS[".qoder"]["config"] == "qoder", "qoder config still install"


def test_upgrade_preserves_overrides_and_does_not_reseed_removed_assets(tmp_path):
    target = tmp_path / "kb"
    args = ["init", str(target), "--no-git", "--no-set-default"]
    assert runner.invoke(app, args).exit_code == 0
    settings = target / "settings" / "recall.yaml"
    settings.write_text("search_backend: native\nrecall:\n  topn: 2\n", encoding="utf-8")
    context = target / "profiles" / "INDEX.md"
    context.write_text("# My context\n", encoding="utf-8")
    readme = target / "README.md"
    readme.write_text("# My prerequisites\n", encoding="utf-8")
    custom = target / "profiles" / "projects" / "mine.md"
    custom.write_text("# User project\n", encoding="utf-8")
    result = runner.invoke(app, [*args, "--upgrade"])
    assert result.exit_code == 0, result.output
    assert settings.read_text() == "search_backend: native\nrecall:\n  topn: 2\n"
    assert context.read_text() == "# My context\n"
    assert readme.read_text() == "# My prerequisites\n"
    assert custom.read_text() == "# User project\n"
    assert not (target / "_meta").exists()
    assert not (target / "templates").exists()
    assert not (target / "profiles" / "team.md").exists()
    assert not (target / "profiles" / "goals" / "team.md").exists()
    assert not list((target / "profiles" / "recipes").glob("*.md"))


def test_team_init_uses_folder_name_by_default(tmp_path):
    target = tmp_path / "team-knowledge"
    result = runner.invoke(app, ["team", "init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output
    import yaml
    profile = yaml.safe_load((target / "profiles" / "team.md").read_text().split("---")[1])
    assert profile["title"] == "team-knowledge"
