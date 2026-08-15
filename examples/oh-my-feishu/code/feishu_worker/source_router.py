"""Feishu worker source probing/routing and Raw packaging.

Leaf module: imports only from feishu_worker.base_client, feishu_worker.config,
and stdlib.  Never imports feishu_base_worker.  Callers must supply *root*
explicitly so this module has zero dependency on the ROOT constant in the
main worker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from feishu_worker.base_client import parse_json_output
from feishu_worker.config import WorkerConfig


def _connector_binary(root: Path) -> list[str]:
    """Return the argv prefix that invokes the oks-connector CLI.

    Prefers the entry point next to the current Python (pipx venv). Falls back
    to running the source script through the interpreter — a bare ``.py`` path
    is not directly executable on Windows (WinError 193).
    """
    suffix = ".exe" if os.name == "nt" else ""
    injected = Path(sys.executable).parent / f"oks-connector{suffix}"
    if injected.is_file():
        return [str(injected)]
    script = root / "scripts" / "raw_bundle_adapter.py"
    if script.is_file():
        return [sys.executable, str(script)]
    raise RuntimeError("oks-connector not found; reinstall open-knowledge-studio")


def _run_or_validate(output: Path, ingest_argv: list[str], root: Path) -> dict[str, Any]:
    """Run an ingest command or validate existing output.

    If *output* already exists as a directory the connector validates it
    and returns the report (or raises RuntimeError when invalid).  Otherwise
    the connector *ingest_argv* is executed, its output is validated, and
    the validation report is returned.
    """
    if output.is_dir():
        validation = subprocess.run(
            [*_connector_binary(root), "validate", str(output)],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        report = parse_json_output(validation)
        if report.get("valid") is True:
            return report
        raise RuntimeError(
            f"existing output is invalid: {json.dumps(report, ensure_ascii=False)}"
        )
    result = subprocess.run(
        ingest_argv,
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    validation = subprocess.run(
        [*_connector_binary(root), "validate", str(output)],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    report = parse_json_output(validation)
    if report.get("valid") is not True:
        raise RuntimeError(
            f"Raw validation failed: {json.dumps(report, ensure_ascii=False)}"
        )
    return report


def package_local_attachment(
    config: WorkerConfig, source: Path, output: Path, *, root: Path
) -> dict[str, Any]:
    """Package a local attachment file into a Raw bundle."""
    return _run_or_validate(
        output,
        [*_connector_binary(root), "ingest", str(source), "--output", str(output)],
        root,
    )


def package_routed_source(
    config: WorkerConfig, source: str, output: Path, *, root: Path
) -> dict[str, Any]:
    """Package a platform-routed source (e.g. Bilibili video) into a Raw bundle."""
    return _run_or_validate(
        output,
        [*_connector_binary(root), "ingest", source, "--output", str(output)],
        root,
    )


def package_public_web(
    config: WorkerConfig,
    url: str,
    output: Path,
    human_context: str,
    *,
    root: Path,
) -> dict[str, Any]:
    """Package a public web page into a Raw bundle via the production extractors.web module."""
    from extractors.web import package_web

    try:
        package_web(url, output, human_context=human_context or "omitted")
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    validation = subprocess.run(
        [*_connector_binary(root), "validate", str(output)],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    report = parse_json_output(validation)
    if report.get("valid") is not True:
        raise RuntimeError(
            f"Raw Bundle validation failed: {json.dumps(report, ensure_ascii=False)}"
        )
    return report
