"""Tests for `oks init` — instance scaffolding + shareable-asset materialization."""
from pathlib import Path

from typer.testing import CliRunner

from knowledge_studio.cli import app

runner = CliRunner()

# Contract: what `oks init` must produce. Buckets come from _INSTANCE_DIRS;
# the dotted editor dirs, templates, _meta and settings are materialized assets.
EXPECTED_BUCKETS = [
    "profiles/users", "profiles/projects", "profiles/recipes", "profiles/goals",
    "raw", "wiki", "drafts",
]
EXPECTED_TOP_LEVEL = {
    ".claude", ".codex", ".agents", "_meta", "settings", "templates",
    "profiles", "raw", "wiki", "drafts", ".gitignore",
}


def _load_map(path: Path) -> list[tuple[str, str]]:
    """Read the _MAP literal without importing the module (setup.py runs setup())."""
    source = path.read_text(encoding="utf-8")
    start = source.index("_MAP = [")
    end = source.index("]", start) + 1
    namespace: dict = {}
    exec(source[start:end], namespace)
    return namespace["_MAP"]


def test_asset_maps_agree_across_build_and_init():
    """A drift here ships assets that never land, or land under the wrong name."""
    from knowledge_studio.cli import _ASSET_MAP

    cli_dir = Path(__file__).parents[1]
    bundle_map = _load_map(cli_dir / "scripts" / "bundle_assets.py")
    setup_map = _load_map(cli_dir / "setup.py")

    assert bundle_map == setup_map, "bundle_assets and setup must vendor the same dirs"
    # _ASSET_MAP reverses the mapping: (bundled name, on-disk name).
    assert [(dest, src) for src, dest in bundle_map] == _ASSET_MAP
    assert (".codex", "codex") in bundle_map
    assert (".agents", "agents") in bundle_map


def _load_tuple(path: Path, name: str) -> tuple[str, ...]:
    """Read a module-level tuple literal without importing the module."""
    source = path.read_text(encoding="utf-8")
    start = source.index(f"{name} = ")
    end = source.index(")", start) + 1
    namespace: dict = {}
    exec(source[start:end], namespace)
    return namespace[name]


def test_dev_only_skills_are_excluded_from_every_build_path():
    """Maintainer PR-review skills must never ship to a user's knowledge base."""
    from knowledge_studio.cli import _DEV_ONLY_ASSET_NAMES as cli_names

    cli_dir = Path(__file__).parents[1]
    bundle_names = _load_tuple(cli_dir / "scripts" / "bundle_assets.py", "_DEV_ONLY_ASSET_NAMES")
    setup_names = _load_tuple(cli_dir / "setup.py", "_DEV_ONLY_ASSET_NAMES")

    # cli's copy governs source checkouts, where the build-time ignore is absent.
    assert bundle_names == setup_names == cli_names
    assert "review-upstream-pr" in bundle_names
    assert "upstream-pr-remediation" in bundle_names


def test_init_never_materializes_dev_only_skills(tmp_path):
    target = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"]).exit_code == 0

    skills = target / ".claude" / "skills"
    installed = {entry.name for entry in skills.iterdir()} if skills.is_dir() else set()
    assert "review-upstream-pr" not in installed
    assert "upstream-pr-remediation" not in installed
    # User-facing skills still arrive.
    assert {"ingest", "query", "promote"} <= installed


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
    assert (target / ".claude" / "settings.json").is_file()
    assert (target / "templates").is_dir()
    for schema in ("recall-case.schema.json", "trace-event.schema.json", "run-manifest.schema.json"):
        assert (target / "_meta" / schema).is_file()


def test_init_upgrade_refreshes_assets_but_keeps_user_files(tmp_path):
    target = tmp_path / "kb"
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])

    marker = target / ".claude" / "MARKER.txt"
    marker.write_text("local edit", encoding="utf-8")

    bundled = target / ".claude" / "settings.json"
    original = bundled.read_text(encoding="utf-8")
    bundled.write_text("{}", encoding="utf-8")

    # re-init without --upgrade keeps existing assets untouched
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert marker.exists()
    assert bundled.read_text(encoding="utf-8") == "{}"

    # --upgrade merge-copies bundled assets: bundled files refreshed,
    # user-owned files (marker) survive — no more whole-tree deletion
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default", "--upgrade"])
    assert marker.exists()
    assert bundled.read_text(encoding="utf-8") == original


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

    # target now contains wiki/ → treated as an existing KB, no --force needed
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output
