"""Build hook: bundle the shareable asset layer during any source build.

The repo root is the single source of truth for `.claude/`, `templates/`,
`_meta/`, `settings/`. When building from a git checkout (pip install ./cli,
pip install git+...#subdirectory=cli, python -m build), copy them into
`knowledge_studio/_assets/` before build_py runs, so source installs are
identical to PyPI wheels. When building from an sdist the repo root is
absent and `_assets/` is already included via MANIFEST.in — skip silently.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

_MAP = [
    (".claude", "claude"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]


class build_py_with_assets(build_py):
    def run(self):
        cli_dir = Path(__file__).resolve().parent
        repo_root = cli_dir.parent
        if (repo_root / ".claude").is_dir() and (repo_root / "templates").is_dir():
            dest_root = cli_dir / "knowledge_studio" / "_assets"
            if dest_root.exists():
                shutil.rmtree(dest_root)
            dest_root.mkdir(parents=True)
            for src_name, dest_name in _MAP:
                src = repo_root / src_name
                if src.is_dir():
                    shutil.copytree(src, dest_root / dest_name)
        super().run()


setup(cmdclass={"build_py": build_py_with_assets})
