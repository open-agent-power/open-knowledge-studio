"""`oks capability` — optional modality capabilities.

Split out of `cli.py` as a verbatim move (B4-6a). Source text was extracted
programmatically, so bodies are byte-identical; `block_equivalence.py` confirms it.
"""
from __future__ import annotations

from knowledge_studio.output import emit_json as _emit_json

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from knowledge_studio import store
from knowledge_studio.i18n import t
from knowledge_studio.instance_cli import _instance_root

console = Console()


capability_app = typer.Typer(help="Optional modality capabilities; core dependencies stay lightweight.")


_CAPABILITIES = {
    "watch": {
        "purpose": "Video/audio subtitles, ASR, frames, and OCR",
        "deps": [
            "faster-whisper==1.2.1",
            "rapidocr==3.9.1",
            "onnxruntime==1.27.0",
            "scenedetect>=0.7,<0.8",
            "imagehash>=4.3,<5",
            "yt-dlp==2026.7.4",
            "watch-skill @ git+https://github.com/oxbshw/watch-skill.git@bf177b09a4c8a4d850c878f3965caecf971555e6",
        ],
    },
    "document": {
        "purpose": "Office, HTML, and text extraction",
        "deps": ["markitdown[docx,pptx]==0.1.6"],
    },
    "pdf-lite": {
        "purpose": "Lightweight text-layer PDF extraction",
        "deps": ["pymupdf4llm==0.0.27", "pymupdf==1.28.0"],
    },
    "pdf": {
        "purpose": "MinerU PDF layout and asset evidence",
        "deps": ["mineru[pipeline]==3.4.4", "six==1.17.0"],
    },
    "formula": {
        "purpose": "PaddleOCR formula candidates",
        "deps": [
            "paddlepaddle==3.2.0",
            "paddleocr==3.7.0",
            # MinerU 3.4.4 requires >=0.22.0,<=0.23.0. 0.23.0 is not
            # published for the supported interpreter index, while 0.22.1 is.
            "tokenizers==0.22.1",
            "ftfy==6.3.1",
        ],
    },
}


@capability_app.command("list")
def capability_list():
    """List optional capabilities and their explicit install boundary."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Capability")
    table.add_column("Purpose")
    table.add_column("Install")
    for name, info in _CAPABILITIES.items():
        install = f"oks capability install {name}"
        table.add_row(name, info["purpose"], install)
    console.print(table)


def _capability_already_installed(name: str) -> bool:
    """Check whether a capability is available (delegates to shared module)."""
    from oks_connector.capability_check import is_capability_available
    ok, _ = is_capability_available(name)
    return ok


@capability_app.command("install")
def capability_install(
    name: str = typer.Argument(..., help="watch, document, pdf, or formula"),
    yes: bool = typer.Option(False, "--yes", help="Execute the displayed installation command"),
):
    """Show or explicitly install one optional capability (heavy dependencies)."""
    info = _CAPABILITIES.get(name)
    if info is None:
        raise typer.BadParameter(f"unknown capability: {name}; run `oks capability list`")
    purpose = info["purpose"]

    if _capability_already_installed(name):
        console.print(f"[green]{t('capability_already', name=name)}[/green]")
        return

    deps = info["deps"]
    cmd = [sys.executable, "-m", "pip", "install"] + deps

    if not yes:
        console.print(Panel.fit(
            f"[bold]{name}[/bold]: {purpose}\n\n"
            f"{t('capability_install_prompt', n=len(deps), cmd=' '.join(cmd))}",
            title=t("optional_install"), border_style="yellow",
        ))
        return

    console.print(f"[yellow]{t('capability_installing', name=name)}[/yellow]")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        console.print(f"[bold red]{t('capability_failed', name=name, code=result.returncode)}[/bold red]")
        raise typer.Exit(result.returncode)
    console.print(f"[green]{t('capability_installed', name=name)}[/green]")


@capability_app.command("status")
def capability_status_cmd(
    json_output: bool = typer.Option(True, "--json/--text", help="Output as JSON"),
):
    """Show the current capability catalog and local provider truth."""
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    if json_output:
        _emit_json(result)
        return

    console.print(f"[bold]Overall:[/bold] {result['overall']}\n")
    for action_name, action_info in sorted(result["actions"].items()):
        provider_ids = result["by_action"].get(action_name, [])
        providers = [
            p for p in result["providers"] if p["id"] in provider_ids
        ]
        labels = ", ".join(
            f"{p.get('label', p['id'])} [{p.get('status', 'unknown')}]"
            for p in providers
        )
        console.print(f"[cyan]{action_info['label']}[/cyan] ({action_name})")
        console.print(f"  {labels or '[dim]no provider[/dim]'}")


@capability_app.command("guide")
def capability_guide_cmd(
    provider: str = typer.Argument(..., help="Provider id, e.g. pdf-lite"),
):
    """Print a provider's execution guide.

    The ingest skill points Agents here instead of reading ``providers/`` from
    disk: a user's knowledge base has no such directory, the guides ship inside
    the package.
    """
    from importlib.resources import files as _pkg_files

    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", provider):
        console.print(f"[red]Invalid provider id:[/red] {provider!r}")
        raise typer.Exit(2)

    root = _pkg_files("knowledge_studio.providers")
    guide = root / provider / "SKILL.md"
    if not guide.is_file():
        available = sorted(
            entry.name for entry in root.iterdir()
            if entry.is_dir() and (entry / "SKILL.md").is_file()
        )
        console.print(
            f"[red]No guide for provider {provider!r}.[/red]\n"
            f"Available: {', '.join(available) or 'none'}"
        )
        raise typer.Exit(2)

    # Rich reads square brackets as style tags and silently drops them, which
    # mangles footnote markers and Markdown links inside a provider guide.
    console.print(guide.read_text(encoding="utf-8"), markup=False)
