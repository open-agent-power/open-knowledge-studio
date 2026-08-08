#!/usr/bin/env python3
"""Bundle the shareable asset layer into the package as data, before build.

The repo root is the single source of truth. This copies:

  <repo>/.claude    -> cli/knowledge_studio/_assets/claude
  <repo>/templates  -> cli/knowledge_studio/_assets/templates
  <repo>/_meta      -> cli/knowledge_studio/_assets/_meta
  <repo>/settings   -> cli/knowledge_studio/_assets/settings

`.claude` is stored as `claude` (no leading dot) so setuptools package-data
globs pick it up; `oks init` writes it back to `.claude` in the instance.

Run before `python -m build` (the publish workflow does this). The bundled
`_assets/` dir is gitignored — it is a build artifact, not source.
"""
from __future__ import annotations

import shutil
from pathlib import Path

# (source dir name at repo root, dest dir name under _assets/)
# Leading dots are stripped for the bundle; cli._ASSET_MAP restores them.
_MAP = [
    (".claude", "claude"),
    (".codex", "codex"),
    (".agents", "agents"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]

_SCRIPT_ASSETS = ("feishu_base_worker.py", "feishu_setup.py")

# Maintainer-only skills: they drive the upstream-PR review workflow and must
# never reach a user's knowledge base, where they would pollute skill discovery
# and could be auto-matched by an agent. Kept in the repo for development.
_DEV_ONLY_ASSET_NAMES = (
    "review-upstream-pr",
    "upstream-pr-remediation",
    "triad-engineering-closure",
    "claude-code-vision-skill",
)
_DEV_ONLY_IGNORE = shutil.ignore_patterns(*_DEV_ONLY_ASSET_NAMES)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]  # cli/scripts/x.py -> repo root
    dest_root = repo_root / "cli" / "knowledge_studio" / "_assets"

    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)

    copied: list[str] = []
    for src_name, dest_name in _MAP:
        src = repo_root / src_name
        if not src.is_dir():
            print(f"  skip (missing): {src_name}")
            continue
        shutil.copytree(src, dest_root / dest_name, ignore=_DEV_ONLY_IGNORE)
        copied.append(dest_name)

    # ── Skills live in skill_templates/, not _assets/ ──
    # _install_skills() reads from skill_templates/ via importlib.resources;
    # duplicating skills under _assets/ creates a second, diverging source.
    for host in ("claude", "agents"):
        skills_dir = dest_root / host / "skills"
        if skills_dir.is_dir():
            shutil.rmtree(skills_dir)
            print(f"  stripped skills from _assets/{host}/")

    scripts_dest = dest_root / "scripts"
    scripts_dest.mkdir()
    for name in _SCRIPT_ASSETS:
        source = repo_root / "scripts" / name
        if source.is_file():
            shutil.copy2(source, scripts_dest / name)
            copied.append(f"scripts/{name}")
        else:
            print(f"  skip (missing): scripts/{name}")

    print(f"Bundled assets into {dest_root}: {', '.join(copied) or '(none)'}")


if __name__ == "__main__":
    main()
