"""Tests for `oks init` — instance scaffolding + shareable-asset materialization."""
from pathlib import Path

from typer.testing import CliRunner

from knowledge_studio.cli import app

runner = CliRunner()


def test_init_scaffolds_buckets_and_data_gitignore(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output

    for d in ["wiki", "drafts", "raw", "profiles/goals", "settings", "_meta", "templates"]:
        assert (target / d).is_dir(), f"missing bucket {d}"

    gi = (target / ".gitignore").read_text(encoding="utf-8")
    # instance gitignore ignores only per-machine state, and TRACKS memory
    assert ".oks/" in gi
    assert "wiki/**/*.md" not in gi
    assert "drafts/*.md" not in gi


def test_init_materializes_shareable_assets(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert result.exit_code == 0, result.output

    # skills + templates arrive so the Claude Code experience works out of the box
    assert (target / ".claude" / "skills" / "ingest").is_dir()
    assert (target / ".claude" / "settings.json").is_file()
    assert (target / "templates").is_dir()


def test_init_upgrade_refreshes_assets(tmp_path):
    target = tmp_path / "kb"
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])

    marker = target / ".claude" / "MARKER.txt"
    marker.write_text("local edit", encoding="utf-8")

    # re-init without --upgrade keeps existing assets (marker survives)
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default"])
    assert marker.exists()

    # --upgrade re-copies bundled assets, dropping the local marker
    runner.invoke(app, ["init", str(target), "--no-git", "--no-set-default", "--upgrade"])
    assert not marker.exists()
