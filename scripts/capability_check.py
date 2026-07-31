"""Single source of truth for extractor capability availability.

Used by both the CLI layer (``cli.py``) and the connector layer
(``raw_bundle_adapter.py``) so that ``oks capability install`` and
``oks ingest`` always agree on whether a capability is ready.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# ── capability ↔ module mapping ──────────────────────────────────

_MODULES: dict[str, str] = {
    "watch": "watch_skill",
    "rapidocr": "rapidocr",
    "document": "markitdown",
    "pdf": "mineru",
    "formula": "paddleocr",
}

_ENV_VARS: dict[str, str] = {
    "watch": "OKS_WATCH_PYTHON",
    "rapidocr": "OKS_WATCH_PYTHON",
    "document": "OKS_DOCUMENT_PYTHON",
    "pdf": "OKS_MINERU_PYTHON",
    "formula": "OKS_FORMULA_PYTHON",
}


def is_capability_available(name: str) -> tuple[bool, Path | None]:
    """Return ``(available, python_path_or_None)`` for *name*.

    Priority:
    1. Module is importable in the current interpreter → (True, sys.executable)
    2. Environment variable points to a valid Python → (True, env_path)
    3. Not available → (False, None)
    """
    module = _MODULES.get(name)
    if module and importlib.util.find_spec(module) is not None:
        return True, Path(sys.executable).resolve()

    env_var = _ENV_VARS.get(name, "")
    if env_var:
        configured = os.environ.get(env_var)
        if configured:
            candidate = Path(configured).expanduser().resolve()
            if candidate.is_file() and module and python_can_import(candidate, module):
                return True, candidate

    return False, None


def python_can_import(candidate: Path, module: str, *, timeout: float = 15.0) -> bool:
    """Return whether *candidate* can start and import *module*.

    Environment-variable overrides are only useful if the target interpreter can
    actually load the extractor dependency. A path-only check caused false
    positives such as ``OKS_DOCUMENT_PYTHON`` pointing at a Python executable
    without ``markitdown`` installed.
    """
    try:
        result = subprocess.run(
            [str(candidate), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
