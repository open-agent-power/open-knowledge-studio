"""Shared CLI output helpers.

Command modules and the CLI entry point both import from here. Keeping the
implementation out of ``cli.py`` removes the reverse dependency that used to
re-import ``knowledge_studio.cli`` while a command was running.
"""
from __future__ import annotations

import json

import typer
from rich.console import Console

console = Console()


def validate_output_format(value: str) -> str:
    normalized = value.lower().strip()
    if normalized not in {"table", "json"}:
        console.print("[red]--format must be one of: table, json[/red]")
        raise typer.Exit(2)
    return normalized


def emit_json(data) -> None:
    """Write machine-readable JSON without Rich markup or ANSI styling."""
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
