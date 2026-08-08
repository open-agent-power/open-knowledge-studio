"""Shared, lazily-called Lark CLI resolver.

Importing this module never requires a CLI installation. The resolver is only
invoked at the point of use (e.g. when a Feishu command actually runs).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_lark_cli(_platform: str | None = None) -> Path:
    """Return the absolute path to a working lark-cli executable.

    Resolution order:
    1. ``LARK_CLI_EXE`` environment variable (exact path, any platform)
    2. Platform-specific fallbacks:
       - Windows: ``lark-cli.cmd``, ``lark-cli.exe``, npm global install
       - Linux/macOS: ``lark-cli`` on PATH

    The optional *_platform* parameter (``"nt"`` / ``"posix"``) is an internal
    hook for tests; callers should omit it to use the real host platform.
    """
    configured = os.environ.get("LARK_CLI_EXE")
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate.resolve()

    platform = _platform if _platform is not None else os.name

    if platform == "nt":
        for name in ("lark-cli.cmd", "lark-cli.exe"):
            located = shutil.which(name)
            if located:
                return Path(located).resolve()
        appdata = os.environ.get("APPDATA")
        if appdata:
            npm_candidate = (
                Path(appdata) / "npm" / "lark-cli.cmd"
            )
            if npm_candidate.is_file():
                return npm_candidate.resolve()
    else:
        located = shutil.which("lark-cli")
        if located:
            return Path(located).resolve()

    raise RuntimeError(
        "lark-cli not found; set LARK_CLI_EXE to its absolute path"
    )
