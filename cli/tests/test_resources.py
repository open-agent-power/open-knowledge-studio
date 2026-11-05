"""Resource resolution is shared by commands, Web, hooks and evaluation."""
from pathlib import Path

import pytest

from knowledge_studio import resources


@pytest.fixture
def package(tmp_path, monkeypatch):
    folder = tmp_path / "cli/knowledge_studio"
    folder.mkdir(parents=True)
    monkeypatch.setattr(resources, "__file__", str(folder / "resources.py"))
    return folder


@pytest.mark.parametrize("git_marker", ["directory", "worktree_file"])
def test_checkout_resources_take_precedence_over_packaged_copy(package, git_marker):
    checkout = package.parents[1]
    marker = checkout / ".git"
    if git_marker == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: ../git/worktrees/sample", encoding="utf-8")
    source = checkout / "assets"
    source.mkdir()
    packaged = package / "_assets"
    packaged.mkdir()
    (packaged / "stale.txt").write_text("stale generated copy", encoding="utf-8")

    assert resources.asset_source() == source
    assert resources.asset_root() == source


def test_installed_resources_use_the_packaged_tree(package):
    packaged = package / "_assets"
    packaged.mkdir()
    (packaged / "present.txt").write_text("bundled", encoding="utf-8")

    assert resources.asset_source() == packaged
    assert resources.asset_root() == packaged


@pytest.mark.parametrize("empty_package", [False, True])
def test_missing_resources_preserve_optional_and_required_boundaries(package, empty_package):
    if empty_package:
        (package / "_assets").mkdir()

    assert resources.asset_source() is None
    with pytest.raises(FileNotFoundError, match="Bundled OKS assets"):
        resources.asset_root()


def test_hook_bridge_keeps_structured_error_when_resources_are_missing(package):
    from knowledge_studio.cli import _run_hook_recall

    result = _run_hook_recall(Path("missing-kb"), "query", "session", "cwd", "agent")

    assert result["reason"] == "hook_script_unavailable"
