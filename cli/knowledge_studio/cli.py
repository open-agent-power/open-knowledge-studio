"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markup import escape

from knowledge_studio import store
from knowledge_studio.i18n import t
from knowledge_studio.raw_commit import CommitError as _CommitError
from knowledge_studio.raw_commit import raw_commit as _raw_commit
from knowledge_studio.vfs import FS_RESPONSE_SCHEMA, VfsError, VfsService
from knowledge_studio.skills_cli import app as skills_app
from knowledge_studio.handoff_cli import app as handoff_app
from knowledge_studio.feedback_cli import app as feedback_app
from knowledge_studio.tasks_cli import app as tasks_app
from knowledge_studio.cli_common import emit_json, instance_root
from knowledge_studio.hooks_cli import app as hook_app
from knowledge_studio.instance_cli import app as instance_app
from knowledge_studio.mail_cli import mail_app, registry_app

def _configure_utf8_stdio() -> None:
    """Keep Unicode Raw evidence printable in Windows legacy code pages."""
    if sys.platform != "win32":
        return

    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding not in {"utf8", "utf8sig"} and callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_configure_utf8_stdio()

app = typer.Typer(
    name="oks",
    help="Open Knowledge Studio — file-based knowledge engineering CLI.",
    no_args_is_help=True,
)
console = Console()


def _validate_output_format(value: str) -> str:
    normalized = value.lower().strip()
    if normalized not in {"table", "json"}:
        console.print("[red]--format must be one of: table, json[/red]")
        raise typer.Exit(2)
    return normalized



def _vfs_success(operation: str, uri: str, result: dict) -> dict:
    return {
        "schema_version": FS_RESPONSE_SCHEMA,
        "operation": operation,
        "uri": uri,
        "result": result,
    }


def _vfs_error(operation: str, uri: str, exc: VfsError) -> dict:
    return {
        "schema_version": FS_RESPONSE_SCHEMA,
        "operation": operation,
        "uri": uri,
        "error": {"code": exc.code, "message": exc.public_message},
    }


def _render_vfs_text(operation: str, uri: str, result: dict[str, Any]) -> None:
    console.print(f"[bold]{escape(operation)}[/bold] {escape(uri)}")
    rows = result.get("entries") or result.get("matches") or result.get("items")
    if isinstance(rows, list):
        table = Table(show_header=True)
        columns = list(rows[0]) if rows else ["uri"]
        for column in columns:
            table.add_column(str(column))
        for row in rows:
            table.add_row(*(escape(str(row.get(column, ""))) for column in columns))
        console.print(table)
    elif "content" in result:
        console.print(escape(str(result["content"])))
    else:
        for key, value in result.items():
            if key != "uri":
                console.print(f"{escape(str(key))}: {escape(str(value))}")
    if "truncated" in result:
        console.print(f"truncated: {str(bool(result['truncated'])).lower()}")


def _run_vfs(
    operation: str,
    uri: str,
    output_format: str,
    call: Callable[[VfsService], dict[str, Any]],
) -> None:
    output_format = _validate_output_format(output_format)
    try:
        from .vfs_observation import observe_call
        result = observe_call(VfsService().resolver.root, operation, uri, call)
    except VfsError as exc:
        payload = _vfs_error(operation, uri, exc)
        if output_format == "json":
            emit_json(payload)
        else:
            console.print(
                f"[red]{escape(exc.code)}:[/red] {escape(exc.public_message)}"
            )
        raise typer.Exit(2)
    except OSError:
        exc = VfsError("IO_ERROR", "Filesystem operation failed")
        payload = _vfs_error(operation, uri, exc)
        if output_format == "json":
            emit_json(payload)
        else:
            console.print(f"[red]{exc.code}:[/red] {exc.public_message}")
        raise typer.Exit(1)

    canonical_uri = str(result.get("uri", uri))
    payload = _vfs_success(operation, canonical_uri, result)
    if output_format == "json":
        emit_json(payload)
    else:
        _render_vfs_text(operation, canonical_uri, result)


def _version_callback(value: bool):
    if value:
        from importlib.metadata import version, PackageNotFoundError
        try:
            console.print(f"oks {version('open-knowledge-studio')}")
        except PackageNotFoundError:
            console.print("oks (development, not installed as a package)")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show the oks version and exit.",
    ),
):
    pass


wiki_app = typer.Typer(help="Wiki page management.")
drafts_app = typer.Typer(help="Draft proposal management.")
config_app = typer.Typer(help="Global configuration (~/.oks/config.json).")
eval_app = typer.Typer(help="Offline recall evaluation and run comparison.")
sources_app = typer.Typer(help="Link independent read-only Git knowledge repositories.")
trace_app = typer.Typer(help="Append-only execution traces and feedback.")
workbuddy_app = typer.Typer(
    help="WorkBuddy local Agent workflow.", no_args_is_help=True,
)
fs_app = typer.Typer(
    help="Read-only virtual context filesystem.", no_args_is_help=True
)

capability_app = typer.Typer(help="Optional modality capabilities; core dependencies stay lightweight.")
schema_app = typer.Typer(help="Protocol document shapes an Agent must author.")
security_app = typer.Typer(help="Credential redaction for provider raw output.")


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
from .daily_cli import app as capture_app
app.add_typer(capture_app, name="capture")
app.add_typer(wiki_app, name="wiki")
app.add_typer(skills_app, name="skills")
app.add_typer(drafts_app, name="drafts")
app.add_typer(config_app, name="config")
app.add_typer(hook_app, name="hook")
app.add_typer(mail_app, name="mail")
app.add_typer(handoff_app, name="handoff")
app.add_typer(feedback_app, name="feedback")
app.add_typer(tasks_app, name="task")
app.add_typer(registry_app, name="registry")
app.add_typer(eval_app, name="eval")
app.add_typer(sources_app, name="sources")
app.add_typer(trace_app, name="trace")
app.add_typer(workbuddy_app, name="workbuddy")
app.add_typer(fs_app, name="fs")

app.add_typer(capability_app, name="capability")
app.add_typer(schema_app, name="schema")
app.add_typer(security_app, name="security")
app.add_typer(ingest_app, name="ingest")
app.add_typer(instance_app)

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


@fs_app.command("ls")
def fs_ls(
    uri: str = typer.Argument(..., help="Canonical oks:// URI."),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """List the direct children of a public VFS directory."""
    _run_vfs("ls", uri, output_format, lambda service: service.ls(uri))


@fs_app.command("tree")
def fs_tree(
    uri: str = typer.Argument(..., help="Canonical oks:// URI."),
    depth: int = typer.Option(3, "--depth", help="Traversal depth (0..10)."),
    max_entries: int = typer.Option(
        1_000, "--max-entries", help="Maximum returned entries."
    ),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Show a bounded recursive directory tree."""
    _run_vfs(
        "tree",
        uri,
        output_format,
        lambda service: service.tree(uri, depth=depth, max_entries=max_entries),
    )


@fs_app.command("stat")
def fs_stat(
    uri: str = typer.Argument(..., help="Canonical oks:// URI."),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Show metadata for a public VFS node."""
    _run_vfs("stat", uri, output_format, lambda service: service.stat(uri))


@fs_app.command("read")
def fs_read(
    uri: str = typer.Argument(..., help="Canonical oks:// URI."),
    offset: int = typer.Option(0, "--offset", help="Character offset."),
    limit: int = typer.Option(20_000, "--limit", help="Maximum characters."),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Read a bounded UTF-8 text page."""
    _run_vfs(
        "read",
        uri,
        output_format,
        lambda service: service.read(uri, offset=offset, limit=limit),
    )


@fs_app.command("read-many")
def fs_read_many(
    uris: list[str] = typer.Argument(..., help="Canonical oks:// file URIs."),
    limit: int = typer.Option(20_000, "--limit", help="Maximum characters per file."),
    max_total_chars: int = typer.Option(
        8 * 1024 * 1024,
        "--max-total-chars",
        help="Maximum characters returned across all files.",
    ),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Read multiple bounded UTF-8 text files in one CLI invocation."""
    _run_vfs(
        "read-many",
        "oks://",
        output_format,
        lambda service: service.read_many(
            uris, limit=limit, max_total_chars=max_total_chars
        ),
    )


@fs_app.command("overview")
def fs_overview(
    uri: str = typer.Argument(..., help="Canonical oks:// URI."),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Summarize a public VFS directory."""
    _run_vfs("overview", uri, output_format, lambda service: service.overview(uri))


@fs_app.command("find")
def fs_find(
    query: str = typer.Argument(..., help="Case-insensitive literal query."),
    under: str = typer.Option(..., "--under", help="Directory oks:// URI."),
    max_results: int = typer.Option(
        50, "--max-results", help="Maximum matches (1..200)."
    ),
    output_format: str = typer.Option("table", "--format", help="table or json"),
):
    """Find literal path or UTF-8 content matches."""
    _run_vfs(
        "find",
        under,
        output_format,
        lambda service: service.find(query, under=under, max_results=max_results),
    )


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
        emit_json(result)
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


@schema_app.command("show")
def schema_show_cmd(
    name: str = typer.Argument(
        ..., help="Protocol document name, e.g. evidence-manifest"
    ),
):
    """Print a validated example of a protocol document.

    Agents author these documents by hand, so they need the exact shape rather
    than prose about it.
    """
    from knowledge_studio.schema_examples import get_example, list_schema_names

    example = get_example(name)
    if example is None:
        console.print(
            f"[red]Unknown schema {name!r}.[/red]\n"
            f"Available: {', '.join(list_schema_names())}"
        )
        raise typer.Exit(2)
    emit_json(example)


@security_app.command("sanitize")
def security_sanitize_cmd(
    path: str = typer.Argument(..., help="File to sanitize in place, e.g. work/<provider>/output.json"),
    content_type: str = typer.Option(
        "application/json", "--content-type", help="MIME hint for the payload"
    ),
):
    """Strip credentials from a provider's raw output, in place.

    The ingest skill requires this before external provider output enters the
    Run Workspace: API keys, bearer tokens, session cookies and internal IPs
    must not be committed into raw/.
    """
    from knowledge_studio.security.redaction import sanitize_remote_artifact
    from knowledge_studio.security.sensitive_fields import REDACTED
    from knowledge_studio.store import _atomic_write

    target = Path(path).expanduser().resolve()
    if not target.is_file():
        console.print(f"[red]Not a file:[/red] {target}")
        raise typer.Exit(2)

    original = target.read_bytes()
    sanitized = sanitize_remote_artifact(original, content_type=content_type)
    text = sanitized.decode("utf-8", errors="replace")
    redaction_count = text.count(REDACTED) - original.decode(
        "utf-8", errors="replace"
    ).count(REDACTED)

    # Only write when a credential was actually removed. The redactor
    # re-serializes JSON with indent=2, so writing unconditionally would
    # reformat a provider's raw output that had nothing to redact — P3 requires
    # that output be preserved at maximum fidelity.
    if redaction_count <= 0:
        emit_json({"path": str(target), "changed": False, "redaction_count": 0})
        return

    _atomic_write(target, text)
    emit_json({
        "path": str(target),
        "changed": True,
        "redaction_count": redaction_count,
    })


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
        emit_json({"valid": False, "error": str(exc)})
        raise typer.Exit(2)
    emit_json(result)
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
        emit_json({"valid": False, "workflow_status": "incomplete", "error": str(exc)})
        raise typer.Exit(2)
    emit_json(result)
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
        emit_json(result)
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


# Both extract from PDFs: pdf-lite reads the text layer, pdf runs MinerU for
# layout and asset evidence. Guards must accept either, not the literal "pdf".
_PDF_CAPABILITIES = frozenset({"pdf-lite", "pdf"})


def _recommended_capability(source: str) -> str:
    suffix = Path(source.split("?", 1)[0]).suffix.lower()
    if suffix == ".pdf":
        return "pdf-lite"
    if suffix in {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".csv"}:
        return "document"
    return "watch"  # video, audio, and platform URLs all route to watch


@ingest_app.command("run")
def ingest(
    source: str = typer.Argument(..., help="Local file or supported platform URL"),
    mode: str = typer.Option("quick", "--mode", help="quick or forensic"),
    timeout_seconds: Optional[float] = typer.Option(None, "--timeout-seconds"),
    progress: bool = typer.Option(True, "--progress/--no-progress"),
    formula_secondary: bool = typer.Option(False, "--formula-secondary", help="Run PaddleOCR PP-FormulaNet on PDF equation crops."),
    formula_max_regions: int = typer.Option(20, "--formula-max-regions", help="Cap equation blocks for formula secondary extraction."),
):
    """Acquire one source through the installed oks-connector dependency; no Wiki promotion occurs here."""
    if mode not in {"quick", "forensic"}:
        raise typer.BadParameter("--mode must be quick or forensic")
    # ── pre-flight: check capability before running the connector ──
    needed = _recommended_capability(source)
    if not _capability_already_installed(needed):
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
        if needed not in _PDF_CAPABILITIES:
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

    cli_args = ["ingest", source, "--mode", mode]
    if timeout_seconds is not None:
        cli_args.extend(["--timeout-seconds", str(timeout_seconds)])
    if progress:
        cli_args.append("--progress")
    if formula_secondary and needed in _PDF_CAPABILITIES:
        cli_args.append("--formula-secondary")
        cli_args.extend(["--formula-max-regions", str(formula_max_regions)])
    from oks_connector.raw_bundle_adapter import build_parser, run_ingest

    try:
        parsed = build_parser().parse_args(cli_args)
    except SystemExit as exc:
        raise typer.Exit(exc.code)
    try:
        exit_code = run_ingest(parsed)
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


@app.command(name="raw-commit")
def raw_commit_cmd(
    manifest_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Agent-submitted manifest directory containing source-envelope.json, evidence-manifest.json, and artifacts/.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination directory for the assembled Raw Bundle.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace an existing Raw Bundle destination.",
    ),
):
    """Validate an Agent manifest and assemble a Raw Bundle v0.2."""
    try:
        result = _raw_commit(
            manifest_dir,
            output=output,
            overwrite=overwrite,
        )
    except _CommitError as exc:
        error: dict[str, object] = {
            "code": exc.code,
            "message": exc.message,
        }
        if exc.details:
            error["details"] = exc.details
        emit_json({"status": "rejected", "error": error})
        raise typer.Exit(1)

    emit_json(result)


def _extractor_env_for(capability: str) -> str:
    return {"watch": "OKS_WATCH_PYTHON", "document": "OKS_DOCUMENT_PYTHON",
            "pdf": "OKS_MINERU_PYTHON", "formula": "OKS_FORMULA_PYTHON"}.get(capability, "")


# ── Recall ───────────────────────────────────────────────────────

@app.command(name="recall")
def recall_cmd(
    query: str = typer.Argument(help="Search query"),
    topic_id: Optional[int] = typer.Option(None, "--topic-id", help="Filter by topic ID"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results per path"),
    scope: Optional[str] = typer.Option(None, "--scope", "-s", help="Soft scope: narrow knowledge path to one area (opt-in, not a hard partition)"),
    goal: str = typer.Option("active", "--goal", help="Goal mode: active | none | <goal-slug>"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
    explain: bool = typer.Option(False, "--explain", help="Include score components and match reasons"),
    user: Optional[str] = typer.Option(None, "--user", envvar="OKS_USER", help="Current user id; required to recall your own profiles/users/<id>/ (A2 scope)"),
    project: Optional[str] = typer.Option(None, "--project", envvar="OKS_PROJECT", help="Current project slug; required to recall profiles/projects/<slug> (A2 scope)"),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t", help="Restrict the knowledge path to one wiki type"),
    knowledge_only: bool = typer.Option(False, "--knowledge-only", help="Skip the episodic path — only wiki/ results, no raw/ source material"),
    search_backend: str = typer.Option(None, "--search-backend", help="Search backend: native | fts5 | fusion | <connector-name> (默认读 settings/recall.yaml，显式传值优先)"),
    agreement: Optional[Path] = typer.Option(None, "--agreement", envvar="OKS_TASK_AGREEMENT", help="Reviewed task agreement JSON"),
    task_scope: Optional[str] = typer.Option(None, "--task-scope", envvar="OKS_TASK_SCOPE", help="Exact agreement scope label"),
    feedback_subject: Optional[str] = typer.Option(None, "--feedback-subject", envvar="OKS_FEEDBACK_SUBJECT", help="Explicit private feedback subject (routing label, not authentication)"),
    feedback_project: Optional[str] = typer.Option(None, "--feedback-project", envvar="OKS_FEEDBACK_PROJECT", help="Explicit private feedback project; requires current agreement and scope"),
    no_task: bool = typer.Option(False, "--no-task", help="Ignore this workspace's selected task for this query"),
    compact: bool = typer.Option(False, "--compact", help="Compact JSON context; preserve requirements and source references, omit diagnostic detail unless --explain"),
    debug_record: bool = typer.Option(False, "--debug-record", help="Store local bounded retrieval evidence"),
    floor_override: Optional[float] = typer.Option(None, "--floor", help="临时调 floor（不改 settings/recall.yaml，一次性）"),
):
    """Two-path recall: episodic (raw/) + knowledge (wiki/).

    `--knowledge-only` drops the episodic path for a wiki-only view; `--type`
    narrows the knowledge path to one wiki type before ranking and `--limit`.
    """
    from knowledge_studio.recall import recall
    output_format = _validate_output_format(output_format)
    if compact and output_format != 'json':
        raise typer.BadParameter('--compact requires --format json')
    try:
        from knowledge_studio.handoff_cli import load_agreement
        task = load_agreement(agreement) if agreement else None
        result = recall(
            agreement=task, task_scope=task_scope, debug_record=debug_record,
            feedback_subject=feedback_subject, feedback_project=feedback_project,
            use_task=not no_task,
            query=query,
            topic_id=topic_id,
            limit=limit,
            scope=scope,
            goal=goal,
            explain=explain,
            user_id=user,
            project_slug=project,
            type_filter=type_filter,
            knowledge_only=knowledge_only,
            search_backend=search_backend,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    if floor_override is not None:
        result["episodic"] = [
            h for h in result.get("episodic", [])
            if float(h.get("relevance", h.get("rel", 0))) >= floor_override
        ]
        result["knowledge"] = [
            h for h in result.get("knowledge", [])
            if float(h.get("relevance", h.get("rel", 0))) >= floor_override
        ]

    if output_format == "json":
        if compact:
            from knowledge_studio.recall import compact_context
            typer.echo(json.dumps(compact_context(result, explain=explain), ensure_ascii=False, separators=(',', ':')))
        else:
            emit_json(result)
        return

    if result["episodic"]:
        console.print("\n[bold blue]Episodic Memory (raw/ + profiles/)[/bold blue]")
        for item in result["episodic"]:
            console.print(Panel(
                item.get("snippet", "")[:200],
                title=f"[{item.get('type', '')}] {item.get('source_path', '')}",
                border_style="blue",
                expand=False,
            ))

    if result["knowledge"]:
        console.print("\n[bold green]Semantic Memory (wiki/)[/bold green]")
        for item in result["knowledge"]:
            preview = item.get("body_preview", "")[:200]
            if explain and item.get("reasons"):
                preview += "\n\nwhy: " + ", ".join(item["reasons"])
            if item.get("load_command"):
                preview += "\n\n按需加载（尚未执行）：" + item["load_command"]
            console.print(Panel(
                preview,
                title=f"[{item.get('type', '')}] {item.get('title', '')} ({item.get('slug', '')})",
                subtitle=f"score={item.get('score', 0):.2f} relevance={item.get('relevance', 0):.2f}",
                border_style="green",
                expand=False,
            ))

    if result.get("continuation"):
        saved = result["continuation"]
        console.print(f"\n当前任务：{saved['task_id']}（修订 {saved['revision']}）", markup=False)
        console.print("已完成：" + saved['progress'] + "\n下一步：" + saved['next_action'], markup=False)
    task_context = result.get("task_context", {})
    if task_context.get("status") != "not_requested":
        console.print("\n本任务要求：" + str(task_context.get("status")), markup=False)
        for candidate in task_context.get("candidates", []):
            console.print(candidate["title"] + ": " + candidate["summary"], markup=False)
    for item in result.get('team_knowledge', []):
        console.print(Panel(item['body'], title=item['title'], subtitle=item['url'], expand=False))
    if not result["episodic"] and not result["knowledge"] and not result.get('team_knowledge'):
        console.print("[dim]No results from either path.[/dim]")


# --- Offline evaluation --------------------------------------------------

@sources_app.command('link')
def sources_link(path: Path, name: str = typer.Option(..., '--name'),
                 repository: str = typer.Option(..., '--repository'), revision: str = typer.Option('HEAD', '--revision')):
    from .linked_sources import link
    try:
        emit_json(link(instance_root(None), name, path, repository, revision))
    except (OSError, ValueError, KeyError) as exc:
        raise typer.BadParameter(str(exc))


@sources_app.command('list')
def sources_list():
    from .linked_sources import catalog
    emit_json(catalog(instance_root(None)))


@sources_app.command('unlink')
def sources_unlink(name: str):
    from .linked_sources import unlink
    emit_json(unlink(instance_root(None), name))


@fs_app.command('inspect')
def fs_inspect(uri: str, operation: str = typer.Option('ls', '--operation'),
               query: str = typer.Option('', '--query'), offset: int = typer.Option(0), limit: int = typer.Option(20000)):
    """Execute a measured VFS call and retain real stage timings."""
    from .vfs_observation import execute
    try:
        emit_json(execute(instance_root(None), operation, uri, query=query, offset=offset, limit=limit))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))


@eval_app.command('candidates')
def eval_candidates():
    from .evaluation_feedback import candidates
    emit_json(candidates(instance_root(None)))


@eval_app.command('capture')
def eval_capture(enabled: bool = typer.Option(True, '--enabled/--disabled'),
                 retain_query: bool = typer.Option(False, '--retain-query/--hash-query')):
    from .evaluation_feedback import configure
    emit_json(configure(instance_root(None), {'values': {'capture_enabled': enabled, 'retain_query': retain_query}}))


@eval_app.command('review')
def eval_review(identifier: str, query: str = typer.Option(..., '--query'),
                accept: Optional[list[str]] = typer.Option(None, '--accept'),
                reject: Optional[list[str]] = typer.Option(None, '--reject'),
                clear: Optional[list[str]] = typer.Option(None, '--clear'),
                reason: str = typer.Option('', '--reason'), confirm: bool = typer.Option(False, '--confirm'),
                derived_query: bool = typer.Option(False, '--derived-query')):
    """Explicitly accept/reject knowledge for one observed query; missing labels remain unknown."""
    from .evaluation_feedback import review
    try:
        emit_json(review(instance_root(None), {'id': identifier, 'query': query, 'accept': accept or [],
            'reject': reject or [], 'clear': clear or [], 'reason': reason, 'confirm': confirm, 'derived_query': derived_query}))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))


@eval_app.command('export')
def eval_export(name: str = typer.Option(..., '--name'), kind: str = typer.Option('recall', '--kind'),
                case: Optional[list[str]] = typer.Option(None, '--case')):
    from .evaluation_feedback import export
    try:
        emit_json(export(instance_root(None), {'name': name, 'kind': kind, 'ids': case}))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))

@eval_app.command("recall")
def eval_recall(
    dataset: Path = typer.Argument(help="YAML recall dataset"),
    output: Path = typer.Option(..., "--output", "-o", help="Output run JSON"),
    limit: int = typer.Option(5, "--limit", "-n", min=5, help="Retrieved items per case (>=5 keeps recall@5 meaningful)"),
    search_backend: Optional[str] = typer.Option(None, "--search-backend", help="Override recall.yaml (fts5/native/fusion) for ablation"),
    split: Optional[str] = typer.Option(None, "--split", help="v2 dataset split: train, validation or test; required for mixed datasets"),
):
    """Run a read-only Wiki recall evaluation; v2 adds fixture-label audits."""
    from knowledge_studio.evaluation import run_evaluation

    try:
        result = run_evaluation(dataset, output, limit=limit, search_backend=search_backend, split=split)
    except (OSError, ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    summary = {"output": str(output.resolve()), "metrics": result["metrics"]}
    if "evaluation_mode" in result["manifest"]:
        summary.update(evaluation_mode=result["manifest"]["evaluation_mode"], split=result["manifest"]["split"])
    emit_json(summary)


@eval_app.command("compare")
def eval_compare(
    baseline: Path = typer.Argument(help="Baseline run JSON"),
    candidate: Path = typer.Argument(help="Candidate run JSON"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Optional comparison JSON"),
    vary: Optional[list[str]] = typer.Option(None, "--vary", help="Intentional variable: code, backend, settings or parameters; repeat as needed"),
):
    """Compare runs with matching dataset, knowledge and configuration snapshots."""
    from knowledge_studio.evaluation import compare_runs

    try:
        result = compare_runs(baseline, candidate, output, vary=vary or ())
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(result)


# --- Execution traces ---------------------------------------------------

def _parse_json_object(value: str, option: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        console.print(f"[red]{option} must be valid JSON: {e}[/red]")
        raise typer.Exit(2)
    if not isinstance(parsed, dict):
        console.print(f"[red]{option} must be a JSON object[/red]")
        raise typer.Exit(2)
    return parsed


@trace_app.command("start")
def trace_start(
    goal_id: str = typer.Argument(help="Goal identifier"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Stable run identifier"),
):
    """Start an execution trace with a goal event."""
    from knowledge_studio.trace import start_trace

    try:
        result = start_trace(goal_id, run_id)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(result)


@trace_app.command("append")
def trace_append(
    run_id: str = typer.Argument(help="Run identifier"),
    event_type: str = typer.Option(..., "--type", help="Trace event type"),
    actor: str = typer.Option(..., "--actor", help="agent | judge | human | tool | system"),
    payload: str = typer.Option("{}", "--payload", help="JSON object without secrets"),
    evidence: list[str] = typer.Option([], "--evidence", help="Repeatable evidence reference"),
):
    """Append one typed event to a running trace."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, event_type, actor, _parse_json_object(payload, "--payload"), evidence)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(event)


@trace_app.command("judge")
def trace_judge(
    run_id: str = typer.Argument(help="Run identifier"),
    outcome: str = typer.Option(..., "--outcome", help="pass | fail | uncertain"),
    comment: str = typer.Option(..., "--comment", help="Judge rationale"),
):
    """Record an external or deterministic judge result."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "judge_comment", "judge", {"outcome": outcome, "comment": comment})
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(event)


@trace_app.command("feedback")
def trace_feedback(
    run_id: str = typer.Argument(help="Run identifier"),
    outcome: str = typer.Option(..., "--outcome", help="accepted | rejected | needs_changes"),
    comment: str = typer.Option(..., "--comment", help="Human feedback"),
):
    """Record human feedback without changing formal knowledge."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "human_comment", "human", {"outcome": outcome, "comment": comment})
        root = instance_root(None)
        _append_trace_feedback_jsonl(root, run_id, outcome, comment)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(event)


@trace_app.command("blocker")
def trace_blocker(
    run_id: str = typer.Argument(help="Run identifier"),
    reason: str = typer.Option(..., "--reason", help="Why execution cannot continue"),
    needed: str = typer.Option(..., "--needed", help="Condition required to resume"),
):
    """Record a blocker and the exact condition needed to resume."""
    from knowledge_studio.trace import append_event

    try:
        event = append_event(run_id, "blocker", "agent", {"reason": reason, "needed": needed})
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(event)


@trace_app.command("propose")
def trace_propose(
    run_id: str = typer.Argument(help="Run identifier"),
    kind: str = typer.Option(..., "--kind", help="wiki | skill"),
    title: str = typer.Option(..., "--title", help="Proposal title"),
    summary: str = typer.Option(..., "--summary", help="Proposed content summary"),
):
    """Write a review-only proposal under drafts/proposals/."""
    from knowledge_studio.proposals import create_proposal

    try:
        path = create_proposal(run_id, kind, title, summary)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json({"path": str(path), "applied": False})


@trace_app.command("finish")
def trace_finish(
    run_id: str = typer.Argument(help="Run identifier"),
    result: str = typer.Option(..., "--result", help="Final result JSON object"),
):
    """Finish a trace with exactly one final_result event."""
    from knowledge_studio.trace import finish_trace

    try:
        manifest = finish_trace(run_id, _parse_json_object(result, "--result"))
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(manifest)


@trace_app.command("validate")
def trace_validate(
    run_id: str = typer.Argument(help="Run identifier"),
    completed: bool = typer.Option(False, "--completed", help="Require a completed run"),
):
    """Validate event ordering, types, manifest consistency, and secret safety."""
    from knowledge_studio.trace import validate_trace

    try:
        result = validate_trace(run_id, require_completed=completed)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    emit_json(result)
    if not result["valid"]:
        raise typer.Exit(1)


@trace_app.command("show")
def trace_show(run_id: str = typer.Argument(help="Run identifier")):
    """Print a trace and its manifest as JSON."""
    from knowledge_studio.trace import show_trace

    try:
        emit_json(show_trace(run_id))
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


# ── Wiki ─────────────────────────────────────────────────────────

@wiki_app.command("list")
def wiki_list(
    domain: Optional[str] = typer.Option(None, "--domain", "-d"),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t"),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
):
    """List all wiki pages."""
    pages = store.list_wiki_pages()

    if domain:
        pages = [p for p in pages if p.get("area") == domain]
    if type_filter:
        pages = [p for p in pages if p.get("type") == type_filter]
    if status:
        pages = [p for p in pages if p.get("status") == status]

    if not pages:
        console.print("[dim]No wiki pages found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Slug", style="dim", max_width=30)
    table.add_column("Title", max_width=40)
    table.add_column("Type", max_width=12)
    table.add_column("Area", max_width=12)
    table.add_column("Tier", max_width=8)
    table.add_column("Score", justify="right", max_width=8)
    table.add_column("Status", max_width=12)

    for p in pages:
        table.add_row(
            p["slug"],
            p.get("title", p["slug"]),
            p.get("type", ""),
            p.get("area", ""),
            p.get("tier", ""),
            f"{p.get('score', 0):.2f}",
            p.get("status", "active"),
        )

    console.print(table)
    console.print(f"\n[dim]{len(pages)} page(s)[/dim]")


@wiki_app.command("get")
def wiki_get(
    slug: str = typer.Argument(help="Page slug"),
):
    """Get a wiki page by slug."""
    from rich.markdown import Markdown

    page = store.get_wiki_page(slug)
    if not page:
        console.print(f"[red]Page not found: {slug}[/red]")
        raise typer.Exit(1)

    body = page.get("body", "")
    console.print(Panel(
        Markdown(body) if body else "[dim](empty)[/dim]",
        title=f"{page.get('title', slug)}",
        subtitle=f"slug={slug} | type={page.get('type', '')} | area={page.get('area', '')} | "
                 f"score={page.get('score', 0):.2f} | tier={page.get('tier', '')} | "
                 f"status={page.get('status', 'active')}",
        border_style="cyan",
        expand=True,
    ))


@wiki_app.command("domains")
def wiki_domains():
    """List canonical knowledge domain IDs and display labels."""
    from knowledge_studio.knowledge_policy import DOMAIN_LABELS
    for key, label in DOMAIN_LABELS.items():
        typer.echo(f"{key}\t{label}")


@wiki_app.command("create")
def wiki_create(
    title: str = typer.Option(..., "--title", help="Page title"),
    page_type: str = typer.Option("concept", "--type", help="concept/strategy/anti-pattern"),
    area: str = typer.Option(..., "--area", help="Canonical domain ID; see oks wiki domains"),
    importance: float = typer.Option(0.5, "--importance", help="0.0-1.0"),
    content: str = typer.Option("", "--content", help="Page body (or pipe via stdin)"),
):
    """Create a new wiki page."""
    import sys
    if not content and not sys.stdin.isatty():
        content = sys.stdin.read()

    from knowledge_studio.knowledge_policy import validate_classification
    try:
        area, wiki_type = validate_classification(area, page_type)
        path = store.write_wiki_page(
            title=title,
            content=content,
            wiki_type=wiki_type,
            area=area,
            importance=importance,
            enforce_classification=True,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Created:[/green] {path}")


@wiki_app.command("pin")
def wiki_pin(slug: str = typer.Argument(help="Page slug to pin")):
    """Pin a wiki page (exempt from decay)."""
    if store.pin_page(slug):
        console.print(f"[green]Pinned:[/green] {slug}")
    else:
        console.print(f"[red]Not found:[/red] {slug}")
        raise typer.Exit(1)


@wiki_app.command("archive")
def wiki_archive(slug: str = typer.Argument(help="Page slug to archive")):
    """Archive a wiki page."""
    if store.archive_page(slug):
        console.print(f"[green]Archived:[/green] {slug}")
    else:
        console.print(f"[red]Not found:[/red] {slug}")
        raise typer.Exit(1)


@wiki_app.command("unarchive")
def wiki_unarchive(slug: str = typer.Argument(help="Page slug to bring back into recall")):
    """Bring an archived page back — the return path A3 depends on.

    Restores to `provisional`, not `active`: leaving the archive is not a human
    review.
    """
    if store.unarchive_page(slug):
        console.print(f"[green]Unarchived (provisional):[/green] {slug}")
    else:
        console.print(f"[red]Not found:[/red] {slug}")
        raise typer.Exit(1)


def _mark_inject_used(root: Path, slug: str) -> int:
    """Mark the most recent inject.jsonl entry containing slug as used=1.

    Training signal: which injected memories were actually adopted.
    Returns count of entries marked (0 if none found)."""
    from datetime import datetime, timezone
    path = root / "records" / "inject.jsonl"
    if not path.is_file():
        return 0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def update(current: str) -> str | None:
        lines = current.splitlines()
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if slug not in rec.get("slugs", []) or slug in rec.get("used_slugs", []):
                continue
            rec["used"] = True
            rec['used_slugs'] = list(dict.fromkeys([*rec.get('used_slugs', []), slug]))
            rec["used_at"] = ts
            lines[i] = json.dumps(rec, ensure_ascii=False)
            return "\n".join(lines) + "\n"
        return None

    try:
        return int(store._locked_atomic_update(
            path,
            update,
            lock_path=root / ".oks" / "locks" / "inject.lock",
        ))
    except Exception:
        return 0


def _append_trace_feedback_jsonl(root: Path, run_id: str, outcome: str, comment: str) -> None:
    """Append human feedback to records/trace-feedback.jsonl (git-shared)."""
    from datetime import datetime, timezone
    path = root / "records" / "trace-feedback.jsonl"
    rec = {
        "run_id": run_id,
        "outcome": outcome,
        "comment": comment,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        store._append_jsonl(
            path,
            rec,
            lock_path=root / ".oks" / "locks" / "trace-feedback.lock",
        )
    except Exception:
        pass


@app.command('use')
@wiki_app.command("use")
def wiki_use(slug: str = typer.Argument(help="Slug of a page that was actually used/injected"),
             observation: Optional[str] = typer.Option(None, '--observation', help='Exact evaluation observation ID; never inferred')):
    """Record an explicit use of a wiki page — the memory-curve signal.

    Recall and search are read-only: a query does not count as a use. Call
    this when a page is actually injected or applied so that access_count
    reflects real usage, not query frequency. This signal affects ranking only;
    it does not promote a page or change its confidence/status.
    """
    if not store.get_wiki_page(slug):
        console.print(f"[red]Not found:[/red] {slug}")
        raise typer.Exit(1)
    root = instance_root(None)
    from . import evaluation_feedback
    if observation:
        item = evaluation_feedback.candidate(root, observation)
        if slug not in {hit.get('slug') for hit in item['hits']}:
            raise typer.BadParameter('Slug was not returned by this observation')
    store.record_access(slug)
    evaluation_feedback.record_use(root, slug, observation)
    used = _mark_inject_used(root, slug)
    updated = store.get_wiki_page(slug)
    console.print(
        f"[green]Recorded use:[/green] {slug} "
        f"(access_count={updated.get('access_count', 0)}, status={updated.get('status', 'active')})"
    )
    if used:
        console.print(f"[dim]inject trace: marked used=1 for recent injection of {slug}[/dim]")


# ── WorkBuddy ─────────────────────────────────────────────────────

@workbuddy_app.command("doctor")
def workbuddy_doctor(
    kb_root: Optional[Path] = typer.Option(
        None,
        "--kb-root",
        help="Knowledge base root (default: OKS_ROOT or configured knowledge base)",
    ),
    output_format: str = typer.Option("text", "--format", help="text or json"),
):
    """Check that the local WorkBuddy read-only OKS workflow is ready.

    This never calls WorkBuddy and never writes Wiki, configuration, or the
    project Skill.
    """
    from knowledge_studio.workbuddy import inspect_workbuddy_adapter

    output_format = output_format.lower().strip()
    if output_format not in {"text", "json"}:
        console.print("[red]--format must be text or json[/red]")
        raise typer.Exit(2)
    root = kb_root.expanduser().resolve() if kb_root is not None else store.repo_root()
    result = inspect_workbuddy_adapter(root)
    if output_format == "json":
        emit_json(result)
    else:
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Check")
        table.add_column("State")
        table.add_column("Details")
        checks = result["checks"]
        table.add_row("wiki", "ready" if checks["wiki"]["ready"] else "missing", checks["wiki"]["path"])
        skill = checks["project_skill"]
        table.add_row("project Skill", "ready" if skill["ready"] else "not ready", skill["path"])
        reviewed = checks["reviewed_wiki"]
        table.add_row("reviewed Wiki", "ready" if reviewed["ready"] else "not ready", str(reviewed["page_count"]))
        console.print(table)
        if result["issues"]:
            console.print("[yellow]Issues:[/yellow] " + "; ".join(result["issues"]))
    if result["status"] != "ready":
        raise typer.Exit(1)


@wiki_app.command("export")
def wiki_export(
    output: Path = typer.Option(Path("wiki-export"), "--output", "-o", help="Output directory"),
    fmt: str = typer.Option("okf", "--format", "-f", help="okf (open standard) or markdown (Obsidian wikilink)"),
):
    """Export wiki/ to a portable knowledge bundle.

    Two flavors (both pure markdown; difference is link + frontmatter style):

    - ``okf``      — Open Knowledge Format: standard markdown links + OKF frontmatter.
    - ``markdown`` — Obsidian-style ``[[wikilink]]``, original frontmatter kept.

    Snapshot, not two-way sync: edits made outside OKS do not flow back.
    See CONSTITUTION A4 for the four relationships encoded as links.
    """
    import frontmatter

    wd = store.wiki_dir()
    if not wd.exists():
        console.print("[yellow]No wiki/ directory — nothing to export.[/yellow]")
        raise typer.Exit(0)
    if fmt not in ("okf", "markdown"):
        console.print(f"[red]Unknown format:[/red] {fmt} (use okf or markdown)")
        raise typer.Exit(1)

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    by_type: dict[str, list[str]] = {}
    n = 0
    for f in sorted(wd.rglob("*.md")):
        if f.name == "INDEX.md":
            continue
        try:
            post = frontmatter.load(f)
        except Exception:
            continue
        slug = str(post.get("slug") or f.stem)
        wtype = str(post.get("type", "concept"))
        relates_to = post.get("relates_to")
        relationship = post.get("relationship")
        body = post.content
        if relates_to:
            rel = f"{relationship}: {relates_to}" if relationship else f"see also: {relates_to}"
            if fmt == "markdown":
                link_line = f"\n\n---\n\n> {rel}\n\n[[{relates_to}]]"
            else:
                link_line = f"\n\n---\n\n> {rel}\n\n[{relates_to}](./{relates_to})"
            body = body.rstrip() + "\n" + link_line + "\n"
        out_meta = dict(post.metadata)
        out_meta["type"] = wtype
        out_meta["concept-id"] = f"{wtype}/{slug}"
        out_dir = output / wtype
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{slug}.md").write_text(
            frontmatter.dumps(frontmatter.Post(body, **out_meta))
        )
        by_type.setdefault(wtype, []).append(slug)
        n += 1
    if n == 0:
        console.print("[yellow]wiki/ is empty — nothing to export.[/yellow]")
        return
    # Per-type index.md (OKF reserved file)
    for wtype, slugs in by_type.items():
        (output / wtype / "index.md").write_text(
            f"# {wtype}\n\n" + "\n".join(f"- [{s}](./{s})" for s in slugs) + "\n"
        )
    # Top-level index.md + log.md (OKF reserved files)
    lines = [f"# Exported Wiki ({fmt})", "", f"{n} pages exported from `wiki/`.", ""]
    for wtype, slugs in sorted(by_type.items()):
        lines.append(f"## {wtype} ({len(slugs)})")
        lines += [f"- [{s}](./{wtype}/{s})" for s in slugs]
        lines.append("")
    (output / "index.md").write_text("\n".join(lines))
    (output / "log.md").write_text(
        "# Log\n\nOne-way snapshot export. See the source instance's git history for the full change log.\n"
    )
    console.print(
        f"[green]Exported {n} pages to {output}[/green] [dim](format={fmt}; "
        + ", ".join(f"{k}={len(v)}" for k, v in sorted(by_type.items()))
        + ")[/dim]"
    )


# ── Drafts ───────────────────────────────────────────────────────

@drafts_app.command("list")
def drafts_list():
    """List all draft proposals."""
    drafts = store.list_drafts()
    if not drafts:
        console.print("[dim]No drafts found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("Slug", style="dim", max_width=30)
    table.add_column("Title", max_width=40)
    table.add_column("Type", max_width=12)
    table.add_column("Area", max_width=12)
    table.add_column("Drafted", max_width=12)

    for d in drafts:
        # YAML turns an unquoted `drafted_at: 2026-08-09` into a datetime.date,
        # which Rich refuses to render — one dated draft broke the whole list.
        table.add_row(
            str(d["slug"]),
            str(d.get("title", d["slug"])),
            str(d.get("draft_type", "")),
            str(d.get("draft_area", "")),
            str(d.get("drafted_at", "")),
        )

    console.print(table)
    console.print(f"\n[dim]{len(drafts)} draft(s)[/dim]")


@drafts_app.command("get")
def drafts_get(slug: str = typer.Argument(help="Draft slug to read")):
    """Print the exact Candidate Markdown for human review."""
    try:
        typer.echo(store.read_draft(slug), nl=False)
    except FileNotFoundError:
        console.print(f"[red]Draft not found:[/red] {slug}")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@drafts_app.command("promote")
def drafts_promote(
    slug: str = typer.Argument(help="Draft slug to promote"),
    title: Optional[str] = typer.Option(
        None, "--title", help="Override the Wiki title during human review"
    ),
    wiki_type: Optional[str] = typer.Option(
        None, "--type", help="Override Wiki type: concept, strategy, or anti-pattern"
    ),
    area: Optional[str] = typer.Option(
        None, "--area", help="Override the Wiki knowledge area"
    ),
    slug_hint: Optional[str] = typer.Option(
        None, "--slug-hint", help="Stable slug hint for the promoted Wiki page"
    ),
    tags: list[str] = typer.Option(
        [], "--tag", help="Replace Wiki tags; repeat for multiple tags"
    ),
):
    """Promote a draft to a wiki page."""
    try:
        new_slug = store.promote_draft(
            slug,
            title=title,
            wiki_type=wiki_type,
            area=area,
            tags=tags or None,
            slug_hint=slug_hint,
        )
        console.print(f"[green]Promoted:[/green] {slug} → {new_slug}")
    except FileNotFoundError:
        console.print(f"[red]Draft not found:[/red] {slug}")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@drafts_app.command("reject")
def drafts_reject(slug: str = typer.Argument(help="Draft slug to reject")):
    """Reject a draft proposal and preserve an append-only review receipt."""
    try:
        receipt = store.reject_draft(slug)
        console.print(f"[green]Rejected:[/green] {slug}")
        console.print(f"[dim]Review receipt: {receipt}[/dim]")
    except FileNotFoundError:
        console.print(f"[red]Draft not found:[/red] {slug}")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


# ── Maintenance ──────────────────────────────────────────────────

@app.command()
def status():
    """Show knowledge base overview."""
    digest = store.wiki_digest()
    drafts = store.list_drafts()
    root = store.repo_root()

    raw_count = 0
    raw_d = store.raw_dir()
    if raw_d.exists():
        raw_count = sum(1 for f in raw_d.rglob("*") if f.is_file() and f.name != ".gitkeep")

    profiles_dir = root / "profiles"
    profile_count = 0
    if profiles_dir.exists():
        profile_count = sum(1 for f in profiles_dir.rglob("*.md") if f.is_file())

    wiki_d = store.wiki_dir()
    domain_count = 0
    if wiki_d.exists():
        domain_count = sum(1 for d in wiki_d.iterdir() if d.is_dir() and not d.name.startswith("."))

    console.print(Panel.fit(
        f"[bold]Open Knowledge Studio — Status[/bold]\n"
        f"[dim]Root: {root}[/dim]\n\n"
        f"Wiki pages: [cyan]{digest['total']}[/cyan]  "
        f"Domains: [cyan]{domain_count}[/cyan]  "
        f"Drafts: [yellow]{len(drafts)}[/yellow]\n"
        f"Raw files: [cyan]{raw_count}[/cyan]  "
        f"Profiles: [cyan]{profile_count}[/cyan]\n\n"
        f"Tiers: hot={digest['tiers']['hot']} warm={digest['tiers']['warm']} "
        f"cold={digest['tiers']['cold']} evictable={digest['tiers']['evictable']}\n"
        f"Quality avg: {digest['quality_avg']}/100  "
        f"Pinned: {digest['pinned']}\n"
        f"Types: {', '.join(f'{k}={v}' for k, v in digest['types'].items())}",
        border_style="cyan",
    ))


@app.command()
def decay():
    """Apply decay — drop wiki pages below threshold score."""
    dropped = store.apply_decay()
    if dropped:
        console.print(f"[yellow]Dropped {len(dropped)} page(s):[/yellow]")
        for slug in dropped:
            console.print(f"  [dim]- {slug}[/dim]")
    else:
        console.print("[green]No pages dropped.[/green]")


@app.command()
def lint():
    """Run health check on the knowledge base."""
    from knowledge_studio.health import run_health_check
    result = run_health_check()

    if result["errors"]:
        console.print(f"[red]{len(result['errors'])} error(s):[/red]")
        for e in result["errors"]:
            console.print(f"  [red]✗[/red] {e}")

    if result["warnings"]:
        console.print(f"[yellow]{len(result['warnings'])} warning(s):[/yellow]")
        for w in result["warnings"]:
            console.print(f"  [yellow]![/yellow] {w}")

    if not result["errors"] and not result["warnings"]:
        console.print("[green]All checks passed.[/green]")

    s = result["summary"]
    console.print(f"\n[dim]Wiki: {s['total_wiki_pages']} pages "
                  f"(dropped: {s['dropped']}, orphan: {s['orphan']}) | "
                  f"Active coverage: {s['coverage_pct']:.0f}%[/dim]")


def _generate_metrics_html(root: Path) -> str:
    """Generate HTML usage report from inject + trace-feedback + knowledge metrics."""
    import json
    from collections import defaultdict
    from datetime import datetime

    # 读 inject.jsonl
    inject_path = root / "records" / "inject.jsonl"
    injects = []
    if inject_path.is_file():
        for line in inject_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    injects.append(json.loads(line))
                except Exception:
                    continue

    # 按 slug 聚合
    slug_stats = defaultdict(lambda: {"count": 0, "used": 0, "rel_sum": 0.0})
    for rec in injects:
        slugs = rec.get("slugs", [])
        rels = rec.get("rels", [])
        for i, slug in enumerate(slugs):
            s = slug_stats[slug]
            s["count"] += 1
            s["rel_sum"] += rels[i] if i < len(rels) else 0
        if rec.get("used"):
            for slug in slugs:
                slug_stats[slug]["used"] += 1

    total = len(injects)
    accepted = sum(1 for r in injects if r.get("used"))
    rate = (accepted / total * 100) if total else 0

    rows = []
    for slug, s in sorted(slug_stats.items(), key=lambda x: -x[1]["count"])[:20]:
        avg_rel = s["rel_sum"] / s["count"] if s["count"] else 0
        sr = (s["used"] / s["count"] * 100) if s["count"] else 0
        rows.append(
            f"<tr><td>{slug}</td><td>{s['count']}</td><td>{s['used']}</td>"
            f"<td>{avg_rel:.2f}</td><td>{sr:.0f}%</td></tr>"
        )

    fb_path = root / "records" / "trace-feedback.jsonl"
    feedbacks = []
    if fb_path.is_file():
        for line in fb_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    feedbacks.append(json.loads(line))
                except Exception:
                    continue
    fb_rows = []
    for fb in feedbacks[-20:]:
        outcome = fb.get("outcome", "?")
        cls = "accepted" if outcome == "accepted" else ("rejected" if outcome == "rejected" else "")
        fb_rows.append(
            f"<tr><td>{fb.get('run_id', '?')}</td>"
            f"<td class='{cls}'>{outcome}</td>"
            f"<td>{fb.get('comment', '')}</td>"
            f"<td class='muted'>{fb.get('recorded_at', '?')[:19]}</td></tr>"
        )

    from knowledge_studio.metrics import get_knowledge_report
    report = get_knowledge_report()
    k_rows = [
        f"<tr><td>Scale</td><td>Wiki pages</td><td>{report['scale']['total_wiki_pages']}</td></tr>",
        f"<tr><td>Vitality</td><td>Active ratio</td><td>{report['vitality']['active_wiki_ratio']:.0%}</td></tr>",
        f"<tr><td>Value</td><td>Total access</td><td>{report['value']['total_access_count']}</td></tr>",
        f"<tr><td>Credibility</td><td>Avg confidence</td><td>{report['credibility']['avg_confidence']:.2f}</td></tr>",
    ]

    # 调参建议：accepted/rejected rel 分布 + floor + cooldown
    import statistics
    from collections import Counter
    accepted_rels = []
    rejected_rels = []
    for rec in injects:
        used = rec.get("used", False)
        for rel in rec.get("rels", []):
            (accepted_rels if used else rejected_rels).append(rel)
    acc_med = statistics.median(accepted_rels) if accepted_rels else 0
    rej_med = statistics.median(rejected_rels) if rejected_rels else 0
    from knowledge_studio.recall import load_recall_params
    params = load_recall_params(root)
    cur_floor = params["recall_floor"]
    # PostToolUse 注入统计（source=posttool）
    posttool_injects = [r for r in injects if r.get("source") == "posttool"]
    pt_total = len(posttool_injects)
    pt_accepted = sum(1 for r in posttool_injects if r.get("used"))
    pt_rate = (pt_accepted / pt_total * 100) if pt_total else 0
    # 当前生效参数（从 settings/recall.yaml + legacy env override）
    suggested_floor = max(0.7, acc_med - 0.2) if accepted_rels else 0.7
    slug_freq = Counter()
    for rec in injects:
        for slug in rec.get("slugs", []):
            slug_freq[slug] += 1
    top_freq = slug_freq.most_common(3)
    freq_str = ", ".join(f"{s}({c})" for s, c in top_freq) if top_freq else "—"

    ts = datetime.now().isoformat(timespec="seconds")
    inject_table = (
        "<table><tr><th>Slug</th><th>注入次数</th><th>被采纳</th><th>平均 rel</th><th>接受率</th></tr>"
        + "".join(rows) + "</table>"
    ) if rows else "<p class='muted'>无注入记录</p>"
    fb_table = (
        "<table><tr><th>Run</th><th>Outcome</th><th>Comment</th><th>时间</th></tr>"
        + "".join(fb_rows) + "</table>"
    ) if fb_rows else "<p class='muted'>无反馈记录</p>"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>OKS 使用记录</title>
<style>
body {{ font: 14px/1.6 -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #0af; padding-bottom: .3em; }}
h2 {{ color: #0af; margin-top: 2em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f4f4f8; }}
.muted {{ color: #888; }}
.accepted {{ color: #080; font-weight: bold; }}
.rejected {{ color: #c00; font-weight: bold; }}
</style>
</head>
<body>
<h1>OKS 使用记录</h1>
<p class="muted">生成于 {ts} | KB: {root}</p>
<h2>注入统计（inject.jsonl）</h2>
<p>总注入 <b>{total}</b> 次，<b>{accepted}</b> 条被采纳（<b>{rate:.0f}%</b>）</p>
{inject_table}
<h2>Trace 反馈（trace-feedback.jsonl）</h2>
{fb_table}
<h2>调参建议</h2>
<table><tr><th>指标</th><th>当前</th><th>建议</th></tr>
<tr><td>accepted rel 中位数</td><td>{acc_med:.2f}</td><td>—</td></tr>
<tr><td>rejected rel 中位数</td><td>{rej_med:.2f}</td><td>—</td></tr>
<tr><td>recall.floor</td><td>{cur_floor}</td><td>{suggested_floor:.2f}</td></tr>
</table>
<p>频繁注入（cooldown 可能太短）：{freq_str}</p>
<h2>PostToolUse 注入统计</h2>
<p>PostToolUse 注入 <b>{pt_total}</b> 次，<b>{pt_accepted}</b> 条被采纳（<b>{pt_rate:.0f}%</b>）</p>
<h2>当前生效参数（settings/recall.yaml + legacy env override）</h2>
<table><tr><th>参数</th><th>当前值</th></tr>
<tr><td>recall.floor</td><td>{params["recall_floor"]}</td></tr>
<tr><td>recall.topn</td><td>{params["recall_topn"]}</td></tr>
<tr><td>posttool.mode</td><td>{params["posttool_mode"]}</td></tr>
<tr><td>posttool.signal_rel_floor</td><td>{params["posttool_signal_rel_floor"]}</td></tr>
<tr><td>search_backend</td><td>{params["search_backend"]}</td></tr>
</table>
<p class="muted">settings/recall.yaml 是持久配置源；旧环境变量仅作兼容覆盖。临时调参用 oks recall --floor 0.9。</p>
<h2>知识指标</h2>
<table><tr><th>维度</th><th>指标</th><th>值</th></tr>{"".join(k_rows)}</table>
</body>
</html>"""


@app.command()
def metrics(
    html: bool = typer.Option(False, "--html", help="生成 HTML 使用记录并打开"),
):
    """Show 4-dimension knowledge metrics, or --html for usage report."""
    if html:
        root = instance_root(None)
        html_str = _generate_metrics_html(root)
        out_path = root / ".oks" / "metrics.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_str, encoding="utf-8")
        console.print(f"[green]HTML 报告:[/green] {out_path}")
        import subprocess
        subprocess.run(["open", str(out_path)], check=False)
        return
    from knowledge_studio.metrics import get_knowledge_report
    report = get_knowledge_report()

    console.print(Panel.fit(
        f"[bold]Knowledge Report Card[/bold]\n\n"
        f"[cyan]Scale[/cyan]\n"
        f"  Wiki pages: {report['scale']['total_wiki_pages']}\n"
        f"  By type: {report['scale']['wiki_by_type']}\n\n"
        f"[cyan]Vitality[/cyan]\n"
        f"  Wiki last 7d: {report['vitality']['wiki_pages_last_7d']}\n"
        f"  Active ratio: {report['vitality']['active_wiki_ratio']}\n"
        f"  Dropped: {report['vitality']['dropped_count']}\n\n"
        f"[cyan]Value[/cyan]\n"
        f"  With traces: {report['value']['wiki_with_traces']}\n"
        f"  With review: {report['value']['wiki_with_review']}\n"
        f"  Total access: {report['value']['total_access_count']}\n\n"
        f"[cyan]Credibility[/cyan]\n"
        f"  Trace coverage: {report['credibility']['trace_coverage']:.0%}\n"
        f"  Review coverage: {report['credibility']['review_coverage']:.0%}\n"
        f"  Avg confidence: {report['credibility']['avg_confidence']:.2f}\n"
        f"  Avg score: {report['credibility']['avg_score']:.2f}",
        border_style="cyan",
    ))


@app.command()
def distill(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
):
    """Run maintenance cycle: decay + evolve knowledge.

    AI distillation (raw → drafts) is handled by Claude Code /ingest skill.
    This command applies decay and generates draft proposals from page clusters.
    """
    from knowledge_studio.distiller import run_distill_cycle

    if dry_run:
        from knowledge_studio.store import list_wiki_pages
        pages = list_wiki_pages()
        console.print(f"[cyan]Dry run:[/cyan] {len(pages)} wiki pages would be evaluated.")
        console.print("[dim]Use /ingest in Claude Code to triage raw/ files into drafts/.[/dim]")
        return

    result = run_distill_cycle()

    if result["dropped"]:
        console.print(f"[yellow]Dropped {len(result['dropped'])} page(s):[/yellow]")
        for slug in result["dropped"]:
            console.print(f"  [dim]- {slug}[/dim]")
    else:
        console.print("[green]No pages dropped.[/green]")

    if result["drafts"]:
        console.print(f"[green]Generated {result['drafts']} draft proposal(s) in drafts/.[/green]")
    else:
        console.print("[dim]No new draft proposals generated.[/dim]")


# ── Config ───────────────────────────────────────────────────────

@config_app.command("init")
def config_init(
    kb_path: str = typer.Option(None, "--kb-path", help="Knowledge base path"),
):
    """Initialize global config at ~/.oks/config.json."""
    from knowledge_studio.config import init_config

    try:
        path = init_config(kb_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Config created:[/green] {path}")

    from knowledge_studio.config import load_config
    config = load_config()
    console.print(f"  [dim]KB path: {config.get('knowledge_base_path', '')}[/dim]")


@config_app.command("show")
def config_show():
    """Show current global configuration."""
    from knowledge_studio.config import load_config, config_path, VALID_STRATEGIES

    config = load_config()
    strategy = config.get("strategy", "")
    strategy_display = strategy if strategy else "(not set)"

    console.print(f"[dim]Config file: {config_path()}[/dim]\n")
    console.print(Panel.fit(
        f"[bold]Knowledge Base[/bold]\n  {config.get('knowledge_base_path', '(not set)')}\n\n"
        f"[bold]Strategy[/bold]\n  {strategy_display}\n"
        f"  Valid values: {', '.join(sorted(VALID_STRATEGIES))}\n\n"
        f"[dim]The core CLI stores no model credentials or handler configuration.[/dim]",
        border_style="cyan",
    ))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key (normally knowledge_base_path)"),
    value: str = typer.Argument(help="Config value"),
):
    """Set a config value."""
    from knowledge_studio.config import load_config, save_config

    config = load_config()

    keys = key.split(".")
    target = config
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]

    if key == "knowledge_base_path":
        resolved = Path(value).expanduser().resolve()
        if not resolved.is_dir():
            console.print(
                f"[yellow]Warning:[/yellow] directory does not exist: {resolved}"
            )
        value = str(resolved)
        target[keys[-1]] = value
    elif key == "strategy":
        from knowledge_studio.config import set_strategy as _set_strategy
        _set_strategy(value)
        console.print(f"[green]Set:[/green] strategy = {value}")
        return
    elif key in _RECALL_YAML_KEYS:
        # v0.5.12: settings/recall.yaml is the single source of truth for
        # recall params. `oks config set` routes them to yaml, not config.json,
        # so `oks recall` (which reads yaml) actually honors the value.
        from knowledge_studio.recall import set_recall_yaml_param
        from knowledge_studio.store import repo_root
        set_recall_yaml_param(repo_root(), _RECALL_YAML_KEYS[key], value)
        console.print(f"[green]Set:[/green] {key} = {value}  [dim](settings/recall.yaml)[/dim]")
        return
    elif value.lower() in ("true", "false"):
        target[keys[-1]] = value.lower() == "true"
    elif value.isdigit():
        target[keys[-1]] = int(value)
    else:
        target[keys[-1]] = value

    save_config(config)
    console.print(f"[green]Set:[/green] {key} = {value}")


# Map flat CLI keys (oks config set <key>) to (yaml_section, yaml_field)
# in settings/recall.yaml. Anything here is routed to yaml, not config.json,
# so recall (which reads yaml) honors the value. v0.5.12 single-source rule.
_RECALL_YAML_KEYS = {
    "search_backend": (None, "search_backend"),
    "recall_floor": ("recall", "floor"),
    "recall_topn": ("recall", "topn"),
    "recall_minlen": ("recall", "minlen"),
    "recall_cooldown": ("recall", "cooldown"),
    "posttool_mode": ("posttool", "mode"),
    "posttool_signal_rel_floor": ("posttool", "signal_rel_floor"),
    "conflict_window": ("conflict", "window"),
    "mail_topn": (None, "mail_topn"),
}


if __name__ == "__main__":
    app()
