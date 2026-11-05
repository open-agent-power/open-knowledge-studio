"""Shared JSON and instance-root handling for CLI command groups."""
from __future__ import annotations

import json
from pathlib import Path

import typer


def emit_json(data) -> None:
    """Write machine-readable JSON without Rich markup or ANSI styling."""
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def instance_root(path: str | None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    from knowledge_studio.config import get_kb_root
    return get_kb_root()
