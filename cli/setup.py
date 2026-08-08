"""Build hook: vendor the shareable asset layer.

The repo root is the single source of truth for ``.claude/``, ``templates/``,
``_meta/``, ``settings/`` and ``scripts/``. Building from a git checkout copies
them into ``knowledge_studio/_assets/`` before the build runs, so
source installs, sdists and PyPI wheels are identical. When building from an
sdist the repo root is absent and the tree is already present — skip silently.

The legacy ``oks_connector`` package was permanently removed in v0.4.0;
two essential stdlib-only utilities (``capability_check``, ``_lark_cli``)
were inlined into ``knowledge_studio/``.
"""
from __future__ import annotations

import shutil
import stat
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

_MAP = [
    (".claude", "claude"),
    (".codex", "codex"),
    (".agents", "agents"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]

# Test modules would collide with the repo-root copies during collection;
# caches are build noise. Also exclude legacy bridge/assembler modules that
# were deleted in v0.4.0 — they must not reach user wheels.
_CONNECTOR_IGNORE = shutil.ignore_patterns(
    "test_*.py", "tests", "__pycache__", "*.pyc",
    # Legacy bridge/assembler/planner — deleted in v0.4.0
    "raw_assembler.py", "evidence_plan.py", "evidence_fragment.py",
    "degradation.py", "capture_contract.py", "observation_adapter.py",
    "agent_observation.py", "capability_check.py",
    # Legacy network layer — imports deleted route_plan
    "network.py",
    # Legacy directories
    "capture_adapters", "extractors", "experiments",
    # Build artefacts
    ".pytest_cache",
    # Docs not intended for wheel
    "PHASE6-DELETION-MANIFEST.md", "ARCHITECTURE.md",
    # Requirements files for deleted extractors
    "raw_extract_requirements.txt", "watch_extract_requirements.txt",
    "mineru_extract_requirements.txt", "media_ingest_requirements.txt",
    "formula_extract_requirements.txt",
)

# Maintainer-only and dev-only skills: they drive development workflows and must
# never reach a user's knowledge base, where they would pollute skill discovery
# and could be auto-matched by an agent. Kept in the repo for development.
_DEV_ONLY_ASSET_NAMES = (
    "review-upstream-pr",
    "upstream-pr-remediation",
    "triad-engineering-closure",
    "claude-code-vision-skill",
)
_DEV_ONLY_IGNORE = shutil.ignore_patterns(
    ".git", ".hg", ".svn", "__pycache__", "*.pyc", *_DEV_ONLY_ASSET_NAMES
)


def _remove_readonly(func, path, _exc_info):
    """Allow build cleanup to remove read-only files copied from skills."""
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _vendor_assets() -> None:
    repo_root = _repo_root()
    dest_root = Path(__file__).resolve().parent / "knowledge_studio" / "_assets"
    if dest_root.exists():
        shutil.rmtree(dest_root, onerror=_remove_readonly)
    dest_root.mkdir(parents=True)
    for src_name, dest_name in _MAP:
        src = repo_root / src_name
        if src.is_dir():
            shutil.copytree(src, dest_root / dest_name, ignore=_DEV_ONLY_IGNORE)
    # ── Skills live in skill_templates/, not _assets/ ──
    # _install_skills() reads from skill_templates/ via importlib.resources;
    # duplicating skills under _assets/ creates a second, diverging source
    # that shadows the canonical one during oks init (via _materialize_assets).
    for host in ("claude", "agents"):
        skills_dir = dest_root / host / "skills"
        if skills_dir.is_dir():
            shutil.rmtree(skills_dir, onerror=_remove_readonly)
    worker = repo_root / "scripts" / "feishu_base_worker.py"
    if worker.is_file():
        worker_dest = dest_root / "scripts"
        worker_dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(worker, worker_dest / worker.name)
        resolver = worker.parent / "_lark_cli.py"
        if resolver.is_file():
            shutil.copy2(resolver, worker_dest / resolver.name)
        worker_package = worker.parent / "feishu_worker"
        if worker_package.is_dir():
            shutil.copytree(
                worker_package,
                worker_dest / worker_package.name,
                ignore=_CONNECTOR_IGNORE,
            )
            # extractors/ was permanently deleted in v0.4.0.
            # network.py was permanently deleted — do not vendor.



def _purge_stale_build_copies(*relative: str) -> None:
    """Drop build/lib mirrors of vendored trees.

    build_py copies into build/lib incrementally and never deletes, so a tree
    that was vendored before an exclusion was added keeps shipping from there —
    observed as removed maintainer skills reappearing in a fresh wheel.
    """
    build_lib = Path(__file__).resolve().parent / "build" / "lib"
    for name in relative:
        stale = build_lib / name
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)


def _purge_stale_egg_infos() -> None:
    """Remove stale nested egg-info directories from old builds.

    ``scripts/open_knowledge_studio.egg-info/`` is a leftover from when
    ``scripts/`` was its own package.  ``cli/oks_connector/`` (the whole
    directory) is removed below.  Both pollute discovery tooling with dead
    entry points (e.g. ``oks-connector = raw_bundle_adapter:main``).
    """
    for candidate in (
        _repo_root() / "scripts" / "open_knowledge_studio.egg-info",
        Path(__file__).resolve().parent / "oks_connector",
    ):
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)


def _sync_from_checkout() -> None:
    repo_root = _repo_root()
    if (repo_root / ".claude").is_dir() and (repo_root / "templates").is_dir():
        _purge_stale_build_copies("knowledge_studio/_assets")
        _purge_stale_egg_infos()
        _vendor_assets()


class build_py_with_assets(build_py):
    def run(self):
        _sync_from_checkout()
        super().run()


class sdist_with_assets(sdist):
    def run(self):
        _sync_from_checkout()
        super().run()


_sync_from_checkout()

setup(cmdclass={"build_py": build_py_with_assets, "sdist": sdist_with_assets})
