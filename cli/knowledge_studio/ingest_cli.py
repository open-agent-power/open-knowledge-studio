"""`oks ingest` — agent-native ingestion preparation and execution.

Split out of `cli.py` as a verbatim move (B4-6b), including the custom
`_LegacyIngestGroup` that keeps `oks ingest <source>` working beside
`oks ingest prepare`. Source text was extracted programmatically.
"""
from __future__ import annotations

from knowledge_studio.output import emit_json as _emit_json

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from knowledge_studio import store
from knowledge_studio.capability_cli import _capability_already_installed
from knowledge_studio.i18n import t
from knowledge_studio.instance_cli import _instance_root

console = Console()


def _extractor_env_for(capability: str) -> str:
    return {"watch": "OKS_WATCH_PYTHON", "document": "OKS_DOCUMENT_PYTHON",
            "pdf": "OKS_MINERU_PYTHON", "formula": "OKS_FORMULA_PYTHON"}.get(capability, "")


class _LegacyIngestGroup(typer.core.TyperGroup):
    """Keep ``oks ingest <source>`` working beside ``oks ingest prepare``.

    ``resolve_command`` is click's real hook. An earlier attempt overrode
    ``_click_resolve_command``, which exists on neither click.Group nor
    TyperGroup, so it never ran and ``oks ingest <source>`` exited 2.
    """

    def resolve_command(self, ctx, args):
        if args and self.get_command(ctx, args[0]) is None:
            legacy_command = self.get_command(ctx, "run")
            if legacy_command is not None:
                return "run", legacy_command, args
        return super().resolve_command(ctx, args)


ingest_app = typer.Typer(
    help="Agent-native ingestion preparation and execution.",
    no_args_is_help=True,
    cls=_LegacyIngestGroup,
)


@ingest_app.command("validate")
def ingest_validate_cmd(
    run_id: str = typer.Argument(..., help="Agent run identifier"),
    collaboration: bool = typer.Option(False, "--collaboration", help="Require real owner-visible Mail handoffs"),
    review_owner: str = typer.Option("human", "--review-owner"),
):
    """Check persisted extraction, candidate and optional Mail facts without writes."""
    from knowledge_studio.ingest_workflow import validate_workflow

    try:
        result = validate_workflow(run_id, collaboration=collaboration, review_owner=review_owner)
    except (ValueError, OSError) as exc:
        _emit_json({"valid": False, "error": str(exc)})
        raise typer.Exit(2)
    _emit_json(result)
    if not result["valid"]:
        raise typer.Exit(2)


@ingest_app.command("finalize")
def ingest_finalize_cmd(
    run_id: str = typer.Argument(..., help="Agent run identifier"),
    source_only: bool = typer.Option(False, "--source-only", help="Explicit standalone intake without Mail handoffs"),
    review_owner: str = typer.Option("human", "--review-owner"),
):
    """Check handoffs and atomically save pending/incomplete workflow state.

    Does not acquire sources, send messages, approve drafts or promote to Wiki.
    """
    from knowledge_studio.ingest_workflow import finalize_workflow

    try:
        result = finalize_workflow(run_id, source_only=source_only, review_owner=review_owner)
    except (ValueError, OSError) as exc:
        _emit_json({"valid": False, "workflow_status": "incomplete", "error": str(exc)})
        raise typer.Exit(2)
    _emit_json(result)
    if not result["valid"]:
        raise typer.Exit(2)


@ingest_app.command("prepare")
def ingest_prepare_cmd(
    source: str = typer.Argument(..., help="Local file or URL to prepare for ingestion"),
    kb_root: Optional[str] = typer.Option(
        None, "--kb-root", help="Knowledge base root (default: OKS_ROOT or config)"
    ),
    json_output: bool = typer.Option(True, "--json/--text", help="Output as JSON"),
):
    """Create the Agent-native SourceEnvelope and EvidenceManifest skeleton."""
    from knowledge_studio.ingest_prepare import prepare_ingest

    root = Path(kb_root).expanduser().resolve() if kb_root else None
    result = prepare_ingest(source, kb_root=root)
    if json_output:
        _emit_json(result)
        return
    console.print(Panel.fit(
        f"[bold]Source:[/bold] {source}\n"
        f"[bold]Modality:[/bold] {result['modality']}\n"
        f"[bold]Manifest dir:[/bold] {result['manifest_dir']}\n\n"
        + "\n".join(f"  [green]+[/green] {item}" for item in result["files_generated"])
        + f"\n\n[bold cyan]{result['next_step']}[/bold cyan]",
        title="Ingest Prepared",
        border_style="green" if result.get("text_ready") else "yellow",
    ))


@ingest_app.command("run")
def ingest(
    source: str = typer.Argument(..., help="Local file or supported platform URL"),
    mode: str = typer.Option("quick", "--mode", help="quick or forensic"),
    timeout_seconds: Optional[float] = typer.Option(None, "--timeout-seconds"),
    progress: bool = typer.Option(True, "--progress/--no-progress"),
    formula_secondary: bool = typer.Option(False, "--formula-secondary", help="Run PaddleOCR PP-FormulaNet on PDF equation crops."),
    formula_max_regions: int = typer.Option(20, "--formula-max-regions", help="Cap equation blocks for formula secondary extraction."),
):
    """Acquire one source through the built-in connector; no Wiki promotion occurs here."""
    if mode not in {"quick", "forensic"}:
        raise typer.BadParameter("--mode must be quick or forensic")
    from oks_connector.route import extractor_capability, route_plan

    try:
        # ── pre-flight: check capability before running the connector ──
        needed = extractor_capability(route_plan(source)["extractor"])
        if needed and not _capability_already_installed(needed):
            env = _extractor_env_for(needed)
            console.print(Panel.fit(
                f"[bold yellow]{t('capability_missing', name=needed)}[/bold yellow]\n\n"
                f"{t('capability_missing_hint', name=needed, env=env)}",
                title=t("install_hint"),
                border_style="yellow",
            ))
            raise typer.Exit(2)

        # ── formula-secondary requires both pdf and formula capabilities ──
        if formula_secondary:
            if needed != "pdf":
                console.print(Panel.fit(
                    "[bold yellow]--formula-secondary 仅对 PDF 文件有效[/bold yellow]\n\n"
                    "当前来源不是 PDF 文件，已忽略 --formula-secondary 选项。",
                    title=t("install_hint"),
                    border_style="yellow",
                ))
            elif not _capability_already_installed("formula"):
                env = _extractor_env_for("formula")
                console.print(Panel.fit(
                    f"[bold yellow]{t('capability_missing', name='formula')}[/bold yellow]\n\n"
                    f"{t('capability_missing_hint', name='formula', env=env)}",
                    title=t("install_hint"),
                    border_style="yellow",
                ))
                raise typer.Exit(2)

        from argparse import Namespace
        from oks_connector.raw_bundle_adapter import run_ingest

        parsed = Namespace(
            command="ingest", source=source, output=None, title=None,
            mode=mode, subtitle_langs="zh.*,ai-zh,en.*",
            mineru_backend="pipeline", mineru_method="auto", overwrite=False,
            timeout_seconds=timeout_seconds, progress=progress,
            formula_secondary=formula_secondary and needed == "pdf",
            formula_max_regions=formula_max_regions if formula_secondary and needed == "pdf" else 20,
        )
        exit_code = run_ingest(parsed)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(Panel.fit(
            f"[bold red]{exc}[/bold red]",
            title=t("ingest_failed"),
            border_style="red",
        ))
        raise typer.Exit(1)
    if exit_code == 0:
        print(t("ingest_done_hint"), file=sys.stderr)
    raise typer.Exit(exit_code)
