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
# per-agent dirs and templates/_meta/settings/profiles are assembled from assets/.
EXPECTED_BUCKETS = [
    "profiles/users", "profiles/projects", "profiles/recipes", "profiles/goals",
    "raw", "wiki", "drafts",
]
EXPECTED_TOP_LEVEL = {
    ".claude", ".qoder", ".pi", ".codex", ".agents", ".codebuddy", ".workbuddy", "_meta", "settings", "templates",
    "profiles", "raw", "wiki", "drafts", "mail", ".gitignore", "AGENTS.md",
}


def test_maintainer_skills_live_outside_assets():
    """Physical separation replaces ignore rules: dev tooling is not in assets/.

    Everything under assets/ ships to users, so maintainer skills must not be
    there. They stay in the repo's own .claude/ for development.
    """
    repo_root = Path(__file__).parents[2]
    shipped = {entry.name for entry in (repo_root / "assets" / "skills").iterdir()}
    assert "review-upstream-pr" not in shipped
    assert "upstream-pr-remediation" not in shipped
    assert {"ingest", "query", "promote"} <= shipped

    dev_skills = {entry.name for entry in (repo_root / ".claude" / "skills").iterdir()}
    assert {"review-upstream-pr", "upstream-pr-remediation"} <= dev_skills


def test_both_build_paths_vendor_assets_verbatim():
    """bundle_assets.py (workflow) and setup.py (pip) must produce one tree."""
    cli_dir = Path(__file__).parents[1]
    sources = {
        "bundle_assets.py": (cli_dir / "scripts" / "bundle_assets.py").read_text(encoding="utf-8"),
        "setup.py": (cli_dir / "setup.py").read_text(encoding="utf-8"),
    }
    for name, source in sources.items():
        assert 'repo_root / "assets"' in source, f"{name} must copy from assets/"
        assert "_MAP = [" not in source, f"{name} still uses the retired per-dir map"


def test_init_never_materializes_dev_only_skills(tmp_path):
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0

    skills = target / ".claude" / "skills"
    installed = {entry.name for entry in skills.iterdir()} if skills.is_dir() else set()
    assert "review-upstream-pr" not in installed
    assert "upstream-pr-remediation" not in installed
    # User-facing skills still arrive.
    assert {"ingest", "query", "promote"} <= installed


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


def test_hook_install_refreshes_persistence_support_file_for_old_instances(tmp_path):
    """Old instances with hooks must receive the helper used by both engines."""
    from knowledge_studio.cli import _ensure_recall_scripts

    target = tmp_path / "kb"
    hooks = target / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "user-prompt-recall.py").write_text("old\n", encoding="utf-8")
    (hooks / "post-tool-edit.py").write_text("old\n", encoding="utf-8")

    created = _ensure_recall_scripts(target)

    assert "_persistence.py" in created
    assert (hooks / "_persistence.py").is_file()
    assert (hooks / "user-prompt-recall.py").read_text(encoding="utf-8") == "old\n"
    assert (hooks / "post-tool-edit.py").read_text(encoding="utf-8") == "old\n"


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

    # skills + templates arrive so the Claude Code experience works out of the box
    assert (target / ".claude" / "skills" / "ingest").is_dir()
    assert (target / ".claude" / "skills" / "office" / "SKILL.md").is_file()
    assert (target / ".claude" / "settings.json").is_file()
    assert (target / "templates").is_dir()
    for schema in ("recall-case.schema.json", "trace-event.schema.json", "run-manifest.schema.json"):
        assert (target / "_meta" / schema).is_file()
    # Contracts that used to sit at the repo root now ship inside the two layers.
    assert (target / "_meta" / "schemas" / "raw-bundle-v0.2.schema.json").is_file()
    assert (target / "settings" / "capabilities" / "video.watch.json").is_file()
    # Recipes and goal templates travel with the instance.
    assert (target / "profiles" / "recipes" / "daily-arxiv-scan.md").is_file()


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


def test_team_init_creates_shared_profile_and_goal(tmp_path):
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
    goal = (target / "profiles" / "goals" / "team.md").read_text(encoding="utf-8")
    assert 'title: "Platform Knowledge Team"' in profile
    assert "# Platform Knowledge Team" in profile
    assert "owner: team" in goal
    assert "Platform Knowledge Team Goals" in goal
    assert "oks registry bind" in result.output


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
    goal = yaml.safe_load((target / "profiles" / "goals" / "team.md").read_text(encoding="utf-8").split("---")[1])
    assert profile["title"] == 'Team: "Quoted"'
    assert goal["title"] == 'Team: "Quoted" Goals'


def test_team_init_fallback_without_bundled_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_asset_source", lambda: None)
    target = tmp_path / "team-knowledge-studio"
    result = runner.invoke(
        app,
        ["team", "init", str(target), "--no-git", "--no-set-default"],
    )

    assert result.exit_code == 0, result.output
    assert (target / "profiles" / "team.md").is_file()
    assert (target / "profiles" / "goals" / "team.md").is_file()

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
