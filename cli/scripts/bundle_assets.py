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
_MAP = [
    (".claude", "claude"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]


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
        shutil.copytree(src, dest_root / dest_name)
        copied.append(dest_name)

    print(f"Bundled assets into {dest_root}: {', '.join(copied) or '(none)'}")


if __name__ == "__main__":
    main()
