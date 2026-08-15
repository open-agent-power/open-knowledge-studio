"""Build hook: vendor the instance-template assets.

`assets/` at the repo root is the single source for everything an instance
gets: skills, hooks, rules, templates, _meta, settings, per-agent config.
Maintainer-only tooling lives in the repo's own `.claude/`, outside `assets/` —
physical separation instead of ignore rules.

Building from a git checkout copies `assets/` into `knowledge_studio/_assets/`,
so source installs, sdists and PyPI wheels are identical. The connector
package (`oks_connector`) is a regular PyPI dependency (>=0.2.0), no longer
vendored from `scripts/`. When building from an sdist the repo root is absent
and the assets tree already exists — skip silently.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

# Caches are build noise.
_ASSET_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _vendor_assets() -> None:
    """Copy ../assets verbatim into knowledge_studio/_assets/."""
    repo_root = _repo_root()
    source = repo_root / "assets"
    if not source.is_dir():
        return
    dest_root = Path(__file__).resolve().parent / "knowledge_studio" / "_assets"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    shutil.copytree(source, dest_root, ignore=_ASSET_IGNORE)

    # Feishu intake moved to examples/feishu-loop/code/ as a reference script;
    # the CLI no longer ships a feishu command group, so _assets/scripts/ is
    # not created anymore.


def _purge_stale_build_copies(*relative: str) -> None:
    """Drop build/lib mirrors of vendored trees.

    build_py copies into build/lib incrementally and never deletes, so a tree
    vendored before a layout change keeps shipping from there — observed as
    removed maintainer skills reappearing in a fresh wheel.
    """
    build_lib = Path(__file__).resolve().parent / "build" / "lib"
    for name in relative:
        stale = build_lib / name
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)


def _sync_from_checkout() -> None:
    if (_repo_root() / "assets").is_dir():
        _purge_stale_build_copies("knowledge_studio/_assets")
        _vendor_assets()


class build_py_with_assets(build_py):
    def run(self):
        _sync_from_checkout()
        super().run()


class sdist_with_assets(sdist):
    def run(self):
        _sync_from_checkout()
        super().run()


# Materialize generated package assets before setuptools validates the package
# list. In a clean checkout, knowledge_studio/_assets does not exist until the
# build hook vendors it. The separately packaged oks-connector is never copied.
_sync_from_checkout()
setup(cmdclass={"build_py": build_py_with_assets, "sdist": sdist_with_assets})
