#!/usr/bin/env python3
"""Assert a built wheel and sdist actually contain what an install needs.

Every invariant here corresponds to a shipping bug that reached a release:

  - maintainer-only skills leaked into user installs
  - ``.codex``/``.agents`` agent config was never packaged
  - the connector was missing from sdists (now a PyPI dependency, no longer vendored)
  - ``build/lib`` kept shipping a tree that had already been deleted from
    ``assets/``, so a "fresh" wheel still carried removed skills

The expected sets are derived from the source tree instead of hardcoded, so
adding or removing an asset cannot silently drift away from this check.

Usage::

    cd cli && python -m build --outdir ../dist
    python cli/scripts/check_dist.py dist
"""
from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSETS = _REPO_ROOT / "assets"
_MAINTAINER_SKILLS = _REPO_ROOT / ".claude" / "skills"

# Entry point declared in pyproject: its module must be in the wheel.
# (oks_connector.raw_bundle_adapter is provided by the PyPI oks-connector
# package, a declared dependency — not vendored here.)
_REQUIRED_MODULES = (
    "knowledge_studio/cli.py",
    "knowledge_studio/evaluation.py",
    "knowledge_studio/evaluation_dataset.py",
)


def _fail(problems: list[str]) -> None:
    for problem in problems:
        print(f"::error::{problem}")
    raise SystemExit(1)


def _wheel_names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return archive.namelist()


def _sdist_names(sdist: Path) -> list[str]:
    with tarfile.open(sdist) as archive:
        # Strip the leading `<name>-<version>/` component.
        return [m.name.split("/", 1)[1] for m in archive.getmembers() if "/" in m.name]


def _shipped_skills() -> set[str]:
    return {p.name for p in (_ASSETS / "skills").iterdir() if p.is_dir()}


def _maintainer_only_skills() -> set[str]:
    if not _MAINTAINER_SKILLS.is_dir():
        return set()
    return {p.name for p in _MAINTAINER_SKILLS.iterdir() if p.is_dir()} - _shipped_skills()


def check_wheel(names: list[str]) -> list[str]:
    problems: list[str] = []
    prefix = "knowledge_studio/_assets/"

    for module in _REQUIRED_MODULES:
        if module not in names:
            problems.append(f"wheel is missing required module {module}")

    # Every asset file in the single source must reach the wheel.
    for path in sorted(_ASSETS.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        expected = prefix + path.relative_to(_ASSETS).as_posix()
        if expected not in names:
            problems.append(f"wheel is missing asset {expected}")

    # Maintainer tooling must never reach a user's knowledge base.
    for skill in sorted(_maintainer_only_skills()):
        leaked = [n for n in names if f"skills/{skill}/" in n]
        if leaked:
            problems.append(
                f"maintainer-only skill {skill!r} leaked into the wheel: {leaked[:3]}"
            )

    for name in names:
        if name.endswith(".pyc") or "__pycache__" in name:
            problems.append(f"wheel carries build noise: {name}")
        if Path(name).name.startswith("test_"):
            problems.append(f"wheel carries a test module: {name}")

    return problems


def check_sdist(names: list[str]) -> list[str]:
    problems: list[str] = []
    # The connector (oks_connector) is a PyPI dependency, not vendored in the
    # sdist — a source install pulls it via pip from pyproject dependencies.
    if not any(n.startswith("knowledge_studio/_assets/") for n in names):
        problems.append("sdist carries no knowledge_studio/_assets/ — `oks init` would be empty")
    for module in _REQUIRED_MODULES:
        if module not in names:
            problems.append(f"sdist is missing required module {module}")
    for path in sorted(_ASSETS.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            expected = "knowledge_studio/_assets/" + path.relative_to(_ASSETS).as_posix()
            if expected not in names:
                problems.append(f"sdist is missing asset {expected}")
    return problems


def main(argv: list[str]) -> int:
    dist_dir = Path(argv[1] if len(argv) > 1 else "dist").resolve()
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))

    if len(wheels) != 1 or len(sdists) != 1:
        _fail([
            f"expected exactly one wheel and one sdist in {dist_dir}, "
            f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s) — "
            f"a stale artifact makes this check meaningless"
        ])

    problems = check_wheel(_wheel_names(wheels[0])) + check_sdist(_sdist_names(sdists[0]))
    if problems:
        _fail(problems)

    print(f"OK {wheels[0].name} and {sdists[0].name} carry every required asset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
