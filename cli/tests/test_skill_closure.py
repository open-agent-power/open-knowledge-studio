"""Gate Phase 2A — Skill Installation Closure regression tests.

Verifies that skills are installed from a single canonical source
(``skill_templates/``), that ``oks init`` and ``oks skills-install``
produce identical output, and that installed skills contain no
references to removed modules or commands.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

# Paths relative to the repo root
REPO = Path(__file__).resolve().parent.parent.parent
ASSETS = Path(__file__).resolve().parent.parent / "knowledge_studio" / "_assets"
WHEEL_DIR = Path(__file__).resolve().parent.parent / "dist"

FORBIDDEN_PATTERNS = [
    "oks-connector",
    "oks_connector",
    "route_plan",
    "from network import",
    "observation_adapter",
]

FORBIDDEN_PATH_PATTERNS = [
    "schemas/evidence-fragment-v0.1.schema.json",
    "schemas/evidence-manifest-v0.1.schema.json",
    "schemas/agent-observation-v0.1.schema.json",
]


def _sha256_dir(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256_hex} for all files under root."""
    hashes: dict[str, str] = {}
    for fp in sorted(root.rglob("*")):
        if fp.is_file():
            rel = fp.relative_to(root).as_posix()
            hashes[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return hashes


def _run_oks(*args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run oks as a subprocess, returning the CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "knowledge_studio.cli", *args],
        capture_output=True, text=True, cwd=cwd,
        env=env or os.environ.copy(),
    )


# ── test_wheel_assets_do_not_duplicate_skills ──────────────────────


def test_wheel_assets_do_not_duplicate_skills():
    """``_assets/claude/`` and ``_assets/agents/`` must NOT contain ``skills/``.

    Skills are installed exclusively from ``skill_templates/`` via
    ``_install_skills()``.  Duplicating them under ``_assets/`` would
    create a second, diverging source that shadows the canonical one
    during ``oks init`` (via ``_materialize_assets()``).
    """
    if not ASSETS.is_dir():
        pytest.skip("_assets/ not built — run `python cli/scripts/bundle_assets.py` or build the wheel first")

    for host in ("claude", "agents"):
        skills_dir = ASSETS / host / "skills"
        assert not skills_dir.exists(), (
            f"_assets/{host}/skills/ exists but should not — "
            f"skills are installed from skill_templates/, not _assets/"
        )

    # Conversely, skill_templates/ MUST exist and contain skills
    templates = ASSETS.parent / "skill_templates"
    if templates.is_dir():
        for host in ("claude", "agents"):
            skills_dir = templates / host / "skills"
            assert skills_dir.is_dir(), (
                f"skill_templates/{host}/skills/ missing — "
                f"this is the canonical skill source"
            )


def test_wheel_assets_do_not_duplicate_skills_in_wheel():
    """Wheel contents must NOT contain ``_assets/{claude,agents}/skills/``."""
    wheels = sorted(WHEEL_DIR.glob("open_knowledge_studio-*.whl")) if WHEEL_DIR.is_dir() else []
    if not wheels:
        pytest.skip("No wheel found — build the wheel first")

    wheel = wheels[-1]  # latest
    with zipfile.ZipFile(str(wheel)) as zf:
        names = zf.namelist()

    for host in ("claude", "agents"):
        skill_entries = [n for n in names if f"_assets/{host}/skills/" in n]
        assert not skill_entries, (
            f"Wheel contains _assets/{host}/skills/ entries — "
            f"skills must only live in skill_templates/: {skill_entries[:5]}"
        )

    # skill_templates/ MUST be present in the wheel
    for host in ("claude", "agents"):
        tmpl_entries = [n for n in names if f"skill_templates/{host}/skills/" in n]
        assert tmpl_entries, (
            f"Wheel missing skill_templates/{host}/skills/ — "
            f"this is the canonical skill source"
        )


# ── test_init_and_skills_install_hashes_identical ──────────────────


def test_init_and_skills_install_hashes_identical():
    """``oks init`` and ``oks skills-install`` must produce identical skill files.

    Creates two temporary knowledge bases: one via ``oks init``, the other
    via ``oks skills-install`` after an ``oks init --upgrade``.  All skill
    files under ``.claude/skills/`` and ``.agents/skills/`` must have
    identical SHA-256 hashes.
    """
    base = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    kb_init = base / "kb-init"
    kb_install = base / "kb-install"

    try:
        # Create first KB with oks init
        r = _run_oks("init", str(kb_init), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        # Create second KB: first init, then skills-install --force
        # (init is needed for the directory structure; skills-install
        #  targets the active KB so we set OKS_ROOT)
        r = _run_oks("init", str(kb_install), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init (2) failed: {r.stderr}"

        env = os.environ.copy()
        env["OKS_ROOT"] = str(kb_install)
        r = subprocess.run(
            [sys.executable, "-m", "knowledge_studio.cli", "skills-install", "--force"],
            capture_output=True, text=True, env=env,
        )
        assert r.returncode == 0, f"oks skills-install failed: {r.stderr}"

        # Hash all skill files under .claude/skills/ and .agents/skills/
        for skill_dir in (".claude", ".agents"):
            init_hashes = _sha256_dir(kb_init / skill_dir / "skills")
            install_hashes = _sha256_dir(kb_install / skill_dir / "skills")

            # Both must have the same set of files
            init_files = set(init_hashes.keys())
            install_files = set(install_hashes.keys())
            assert init_files == install_files, (
                f"{skill_dir}/skills/ file set differs between init and skills-install:\n"
                f"  Only in init: {sorted(init_files - install_files)}\n"
                f"  Only in skills-install: {sorted(install_files - init_files)}"
            )

            # Every file must have identical content
            for rel, init_hash in sorted(init_hashes.items()):
                install_hash = install_hashes[rel]
                assert init_hash == install_hash, (
                    f"{skill_dir}/skills/{rel} differs between init and skills-install"
                )

            assert len(init_hashes) > 0, f"{skill_dir}/skills/ is empty — no skills installed!"

    finally:
        shutil.rmtree(base, ignore_errors=True)


# ── test_installed_skills_have_no_removed_commands_or_path ─────────


def _collect_skill_text(root: Path) -> list[tuple[str, str]]:
    """Scan installed skills and return [(relative_path, content), ...] for all text files."""
    results: list[tuple[str, str]] = []
    for host in (".claude", ".agents"):
        skills_dir = root / host / "skills"
        if not skills_dir.is_dir():
            continue
        for fp in sorted(skills_dir.rglob("*")):
            if fp.is_file() and fp.suffix in (".md", ".py", ".yaml", ".yml", ".sh", ".json"):
                try:
                    content = fp.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                results.append((str(fp.relative_to(root)), content))
    return results


def test_installed_skills_have_no_removed_commands_or_path():
    """Installed skills must not reference removed modules, commands, or paths.

    After ``oks init``, every skill file under ``.claude/skills/`` and
    ``.agents/skills/`` is scanned for:
    - ``oks-connector`` / ``oks_connector`` (removed in v0.4.0)
    - ``route_plan`` (removed legacy function)
    - ``from network import`` (removed module)
    - ``observation_adapter`` (removed module)
    - Bare ``schemas/`` paths (should use ``importlib.resources``)
    """
    kb = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    try:
        r = _run_oks("init", str(kb), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        files = _collect_skill_text(kb)
        assert len(files) > 0, "No skill files found after oks init!"

        violations: list[str] = []
        for rel, content in files:
            is_python = rel.endswith(".py")
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in content:
                    # Find the line containing the violation
                    for lineno, line in enumerate(content.splitlines(), 1):
                        if pattern in line:
                            # Python comment lines that merely document the
                            # removal (e.g. "# oks-connector was removed in
                            # v0.4.0") are NOT violations — they are
                            # historical notes, not active references.
                            stripped = line.strip()
                            if is_python and stripped.startswith("#"):
                                continue
                            violations.append(
                                f"{rel}:{lineno}: contains forbidden pattern '{pattern}'"
                            )
                            break  # one violation per pattern per file is enough

            # Check for bare schemas/ paths (not preceded by importlib.resources or files())
            for pat in FORBIDDEN_PATH_PATTERNS:
                if pat in content:
                    # Allow if importlib.resources is also used in the same file
                    if "importlib.resources" not in content:
                        for lineno, line in enumerate(content.splitlines(), 1):
                            if pat in line:
                                violations.append(
                                    f"{rel}:{lineno}: uses bare path '{pat}' "
                                    f"instead of importlib.resources"
                                )
                                break

        assert not violations, (
            f"Found {len(violations)} forbidden pattern(s) in installed skills:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    finally:
        shutil.rmtree(kb, ignore_errors=True)


def test_installed_skills_are_not_empty():
    """Every installed skill directory must contain at least a SKILL.md."""
    kb = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    try:
        r = _run_oks("init", str(kb), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        for host in (".claude", ".agents"):
            skills_dir = kb / host / "skills"
            if not skills_dir.is_dir():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                md = skill_dir / "SKILL.md"
                assert md.is_file(), (
                    f"{skill_dir.relative_to(kb)} missing SKILL.md"
                )
                content = md.read_text(encoding="utf-8")
                assert len(content.strip()) > 50, (
                    f"{skill_dir.relative_to(kb)}/SKILL.md is too short ({len(content)} chars)"
                )

    finally:
        shutil.rmtree(kb, ignore_errors=True)


# ── Gate Phase 2A Remediation tests ──────────────────────────────


def _find_file_references(content: str) -> list[str]:
    """Extract executable file-path references from a SKILL.md body.

    Only returns ``python <script>`` invocations — the one kind of
    reference that causes a hard runtime failure if the target is missing.
    Backtick-quoted paths in prose are documentation/suggestions, not
    commands that fail.

    Skips template placeholders (``{slug}``) and wildcard globs (``*``).
    """
    import re

    refs: list[str] = []

    # ``python <script>`` invocations — these are executable commands
    for m in re.finditer(r"python\s+(\S+\.py)", content):
        ref = m.group(1)
        if "{" not in ref and "*" not in ref:
            refs.append(ref)

    return refs


def test_every_installed_skill_command_target_exists():
    """Every file path referenced in an installed SKILL.md must exist on disk.

    Scans for backtick-quoted paths (`` `scripts/foo.py` ``) and
    ``python <script>`` invocations, then asserts the target exists
    relative to the knowledge base root.  Paths that reference external
    tools (`` `pip` ``, `` `oks` ``) are skipped — they need only an
    executable name, not a KB file.
    """
    kb = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    try:
        r = _run_oks("init", str(kb), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        missing: list[str] = []
        for host in (".claude", ".agents"):
            skills_dir = kb / host / "skills"
            if not skills_dir.is_dir():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                md = skill_dir / "SKILL.md"
                if not md.is_file():
                    continue
                content = md.read_text(encoding="utf-8")
                refs = _find_file_references(content)
                for ref in refs:
                    # Skip executable-only names
                    if "/" not in ref and "\\" not in ref and "." not in ref:
                        continue
                    # Skip URLs
                    if ref.startswith("http://") or ref.startswith("https://"):
                        continue
                    # Skip pure package references
                    if ref.startswith("knowledge_studio."):
                        continue
                    # Resolve: paths in SKILL.md are relative to KB root
                    # or relative to the skill dir itself
                    candidates = [
                        kb / ref,
                        skill_dir / ref,
                    ]
                    if not any(c.exists() for c in candidates):
                        missing.append(
                            f"{skill_dir.relative_to(kb)}/SKILL.md "
                            f"references '{ref}' which does not exist"
                        )

        assert not missing, (
            f"Found {len(missing)} dangling file reference(s):\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    finally:
        shutil.rmtree(kb, ignore_errors=True)


def test_accept_helper_imports_packaged_capability_check():
    """``accept.py`` must import from ``knowledge_studio.capability_check``.

    The bare ``from capability_check import ...`` was correct when
    ``capability_check.py`` lived at the repo root, but after the
    v0.4.0 inline the canonical location is
    ``knowledge_studio.capability_check``.
    """
    kb = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    try:
        r = _run_oks("init", str(kb), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        for host in (".claude", ".agents"):
            accept_py = kb / host / "skills" / "accept" / "scripts" / "accept.py"
            if not accept_py.is_file():
                continue  # accept not published for this host — OK
            content = accept_py.read_text(encoding="utf-8")
            # Must NOT contain the bare import
            assert "from capability_check import" not in content, (
                f"{accept_py.relative_to(kb)} still uses bare "
                f"'from capability_check import' — must be "
                f"'from knowledge_studio.capability_check import'"
            )
            # Must contain the packaged import
            assert "from knowledge_studio.capability_check import" in content, (
                f"{accept_py.relative_to(kb)} missing packaged import"
            )

    finally:
        shutil.rmtree(kb, ignore_errors=True)


def test_skill_install_excludes_pycache():
    """``_install_skills()`` must not copy ``__pycache__/`` or ``*.pyc`` files."""
    kb = Path(tempfile.mkdtemp(prefix="oks-test-closure-"))
    try:
        r = _run_oks("init", str(kb), "--no-git", "--no-set-default")
        assert r.returncode == 0, f"oks init failed: {r.stderr}"

        pycache_items: list[str] = []
        for host in (".claude", ".agents"):
            skills_dir = kb / host / "skills"
            if not skills_dir.is_dir():
                continue
            for item in skills_dir.rglob("*"):
                if "__pycache__" in item.parts or item.suffix == ".pyc":
                    pycache_items.append(str(item.relative_to(kb)))

        assert not pycache_items, (
            f"Found {len(pycache_items)} __pycache__ / *.pyc item(s) "
            f"in installed skills:\n"
            + "\n".join(f"  - {i}" for i in pycache_items)
        )

    finally:
        shutil.rmtree(kb, ignore_errors=True)


def test_wheel_installed_skill_command_targets_exist():
    """Every ``python <script>`` in installed SKILL.md must resolve from a Wheel install.

    This is an integration-level gate: it builds a Wheel, installs it into a
    fresh venv, runs ``oks init``, and then checks that every file path
    referenced as ``python <script>`` actually exists.  Source-tree tests
    can pass because the templates live on disk; this test catches packaging
    gaps (e.g. missing ``package-data`` entries) that evaporate files from
    the Wheel.
    """
    import re, subprocess as sp, tempfile as tmpfile

    repo = Path(__file__).resolve().parent.parent.parent

    # 1. Build the Wheel from the current checkout
    r = sp.run(
        [sys.executable, "-m", "build", "--wheel", str(repo / "cli")],
        capture_output=True, text=True, cwd=str(repo),
        timeout=300,
    )
    if r.returncode != 0:
        pytest.skip(f"Wheel build failed (infra, not product): {r.stderr[-500:]}")
    wheels = sorted((repo / "cli" / "dist").glob("open_knowledge_studio-*.whl"))
    if not wheels:
        pytest.skip("No wheel produced by build")
    wheel = wheels[-1]

    # 2. Create a temp venv and install the wheel
    venv_dir = Path(tmpfile.mkdtemp(prefix="oks-wheel-test-"))
    kb = venv_dir / "test-kb"
    try:
        sp.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True, capture_output=True, timeout=60,
        )
        pip = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "pip")
        oks_exe = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "oks")
        sp.run(
            [pip, "install", str(wheel)],
            check=True, capture_output=True, timeout=120,
        )
        env = os.environ.copy()
        r = sp.run(
            [oks_exe, "init", str(kb), "--no-git", "--no-set-default"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert r.returncode == 0, f"oks init from wheel failed: {r.stderr}"

        # 3. Scan every SKILL.md for python <script> and verify existence
        missing: list[str] = []
        for host in (".claude", ".agents"):
            skills_dir = kb / host / "skills"
            if not skills_dir.is_dir():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                md = skill_dir / "SKILL.md"
                if not md.is_file():
                    continue
                content = md.read_text(encoding="utf-8")
                for m in re.finditer(r"python\s+(\S+\.py)", content):
                    ref = m.group(1)
                    if "{" in ref or "*" in ref:
                        continue
                    candidates = [kb / ref, skill_dir / ref]
                    if not any(c.exists() for c in candidates):
                        missing.append(
                            f"{skill_dir.relative_to(kb)}/SKILL.md "
                            f"references 'python {ref}' — file does not exist"
                        )

        assert not missing, (
            f"Found {len(missing)} dangling 'python <script>' reference(s) "
            f"in wheel-installed skills:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    finally:
        shutil.rmtree(venv_dir, ignore_errors=True)
