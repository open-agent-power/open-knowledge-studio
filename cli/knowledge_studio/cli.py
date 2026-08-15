"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.markup import escape

from knowledge_studio import store
from knowledge_studio.i18n import t
from knowledge_studio.raw_commit import CommitError as _CommitError
from knowledge_studio.raw_commit import raw_commit as _raw_commit
from knowledge_studio.recall import (
    RECALL_RESPONSE_SCHEMA,
    describe_goal_selection,
    recall,
    recall_episodic,
    recall_knowledge,
)

# ── ingest: connector is a regular PyPI dependency (oks-connector>=0.2.0) ──
from oks_connector.raw_bundle_adapter import (
    build_parser as _connector_parser,
    run_ingest as _connector_run_ingest,
)
_connector_available = True


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


def _emit_json(data) -> None:
    """Write machine-readable JSON without Rich markup or ANSI styling."""
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


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
hook_app = typer.Typer(help="Optional editor hooks (opt-in auto-recall injection).")
mail_app = typer.Typer(help="Agent-to-agent mail (inbox/sent).")
registry_app = typer.Typer(help="Terminal registry (agent+cwd -> profile/goal).")
eval_app = typer.Typer(help="Offline recall evaluation and run comparison.")
trace_app = typer.Typer(help="Append-only execution traces and feedback.")

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
app.add_typer(wiki_app, name="wiki")
app.add_typer(drafts_app, name="drafts")
app.add_typer(config_app, name="config")
app.add_typer(hook_app, name="hook")
app.add_typer(mail_app, name="mail")
app.add_typer(registry_app, name="registry")
app.add_typer(eval_app, name="eval")
app.add_typer(trace_app, name="trace")

app.add_typer(capability_app, name="capability")
app.add_typer(schema_app, name="schema")
app.add_typer(security_app, name="security")
app.add_typer(ingest_app, name="ingest")

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
    _emit_json(example)


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
        _emit_json({"path": str(target), "changed": False, "redaction_count": 0})
        return

    _atomic_write(target, text)
    _emit_json({
        "path": str(target),
        "changed": True,
        "redaction_count": redaction_count,
    })


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


def _connector_install_hint() -> str:
    return ""  # no-op: connector is built into the monorepo


def _connector_command() -> str | None:
    """Connector is the PyPI ``oks-connector`` package (>=0.2.0) — no separate binary needed."""
    return "built-in" if _connector_available else None


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
    connector = _connector_command()
    if connector is None:
        console.print(Panel.fit(
            f"[bold red]{t('connector_missing')}[/bold red]\n\n"
            f"{t('connector_missing_hint')}",
            title=t("action_required"),
            border_style="red",
        ))
        raise typer.Exit(2)

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
    try:
        parsed = _connector_parser().parse_args(cli_args)
    except SystemExit as exc:
        raise typer.Exit(exc.code)
    try:
        exit_code = _connector_run_ingest(parsed)
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
        _emit_json({"status": "rejected", "error": error})
        raise typer.Exit(1)

    _emit_json(result)


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
):
    """Two-path recall: episodic (raw/) + knowledge (wiki/).

    `--knowledge-only` drops the episodic path for a wiki-only view; `--type`
    narrows the knowledge path to one wiki type before ranking and `--limit`.
    """
    output_format = _validate_output_format(output_format)
    try:
        result = recall(
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
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    if output_format == "json":
        _emit_json(result)
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
            console.print(Panel(
                preview,
                title=f"[{item.get('type', '')}] {item.get('title', '')} ({item.get('slug', '')})",
                subtitle=f"score={item.get('score', 0):.2f} relevance={item.get('relevance', 0):.2f}",
                border_style="green",
                expand=False,
            ))

    if not result["episodic"] and not result["knowledge"]:
        console.print("[dim]No results from either path.[/dim]")


# --- Offline evaluation --------------------------------------------------

@eval_app.command("recall")
def eval_recall(
    dataset: Path = typer.Argument(help="YAML recall dataset"),
    output: Path = typer.Option(..., "--output", "-o", help="Output run JSON"),
    limit: int = typer.Option(5, "--limit", "-n", min=5, help="Retrieved items per case (>=5 keeps recall@5 meaningful)"),
):
    """Run a deterministic, read-only recall evaluation."""
    from knowledge_studio.evaluation import run_evaluation

    try:
        result = run_evaluation(dataset, output, limit=limit)
    except (OSError, ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json({"output": str(output.resolve()), "metrics": result["metrics"]})


@eval_app.command("compare")
def eval_compare(
    baseline: Path = typer.Argument(help="Baseline run JSON"),
    candidate: Path = typer.Argument(help="Candidate run JSON"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Optional comparison JSON"),
):
    """Compare two runs produced from the same dataset snapshot."""
    from knowledge_studio.evaluation import compare_runs

    try:
        result = compare_runs(baseline, candidate, output)
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(result)


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
    _emit_json(result)


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
    _emit_json(event)


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
    _emit_json(event)


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
        root = _instance_root(None)
        _append_trace_feedback_jsonl(root, run_id, outcome, comment)
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    _emit_json(event)


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
    _emit_json(event)


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
    _emit_json({"path": str(path), "applied": False})


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
    _emit_json(manifest)


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
    _emit_json(result)
    if not result["valid"]:
        raise typer.Exit(1)


@trace_app.command("show")
def trace_show(run_id: str = typer.Argument(help="Run identifier")):
    """Print a trace and its manifest as JSON."""
    from knowledge_studio.trace import show_trace

    try:
        _emit_json(show_trace(run_id))
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


@wiki_app.command("create")
def wiki_create(
    title: str = typer.Option(..., "--title", help="Page title"),
    page_type: str = typer.Option("concept", "--type", help="concept/strategy/anti-pattern"),
    area: str = typer.Option("computing", "--area", help="Knowledge domain"),
    importance: float = typer.Option(0.5, "--importance", help="0.0-1.0"),
    content: str = typer.Option("", "--content", help="Page body (or pipe via stdin)"),
):
    """Create a new wiki page."""
    import sys
    if not content and not sys.stdin.isatty():
        content = sys.stdin.read()

    type_map = {
        "concept": "concepts", "concepts": "concepts",
        "strategy": "strategies", "strategies": "strategies",
        "anti-pattern": "anti-patterns", "anti-patterns": "anti-patterns",
    }
    wiki_type = type_map.get(page_type)
    if wiki_type is None:
        console.print(
            f"[yellow]Unknown --type '{page_type}' — using 'concept'. "
            f"Valid: concept, strategy, anti-pattern.[/yellow]"
        )
        wiki_type = "concepts"

    try:
        path = store.write_wiki_page(
            title=title,
            content=content,
            wiki_type=wiki_type,
            area=area,
            importance=importance,
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
    import json
    from datetime import datetime, timezone
    path = root / "records" / "inject.jsonl"
    if not path.is_file():
        return 0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = path.read_text(encoding="utf-8").splitlines()
    target_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if slug in rec.get("slugs", []) and not rec.get("used"):
                target_idx = i
                break
        except Exception:
            continue
    if target_idx < 0:
        return 0
    try:
        rec = json.loads(lines[target_idx])
        rec["used"] = True
        rec["used_at"] = ts
        lines[target_idx] = json.dumps(rec, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    except Exception:
        return 0


def _append_trace_feedback_jsonl(root: Path, run_id: str, outcome: str, comment: str) -> None:
    """Append human feedback to records/trace-feedback.jsonl (git-shared)."""
    import json
    from datetime import datetime, timezone
    path = root / "records" / "trace-feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "run_id": run_id,
        "outcome": outcome,
        "comment": comment,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


@wiki_app.command("use")
def wiki_use(slug: str = typer.Argument(help="Slug of a page that was actually used/injected")):
    """Record an explicit use of a wiki page — the memory-curve signal.

    Recall and search are read-only: a query does not count as a use. Call
    this when a page is actually injected or applied so that access_count
    reflects real usage, not query frequency. Recording also promotes a
    provisional page to active once it has been used 3+ times.
    """
    if not store.get_wiki_page(slug):
        console.print(f"[red]Not found:[/red] {slug}")
        raise typer.Exit(1)
    store.record_access(slug)
    root = _instance_root(None)
    used = _mark_inject_used(root, slug)
    updated = store.get_wiki_page(slug)
    console.print(
        f"[green]Recorded use:[/green] {slug} "
        f"(access_count={updated.get('access_count', 0)}, status={updated.get('status', 'active')})"
    )
    if used:
        console.print(f"[dim]inject trace: marked used=1 for recent injection of {slug}[/dim]")


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


@drafts_app.command("promote")
def drafts_promote(slug: str = typer.Argument(help="Draft slug to promote")):
    """Promote a draft to a wiki page."""
    try:
        new_slug = store.promote_draft(slug)
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
    import os as _os
    cur_floor = _os.environ.get("OKS_RECALL_FLOOR", "0.7")
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
<tr><td>OKS_RECALL_FLOOR</td><td>{cur_floor}</td><td>{suggested_floor:.2f}</td></tr>
</table>
<p>频繁注入（cooldown 可能太短）：{freq_str}</p>
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
        root = _instance_root(None)
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
    elif value.lower() in ("true", "false"):
        target[keys[-1]] = value.lower() == "true"
    elif value.isdigit():
        target[keys[-1]] = int(value)
    else:
        target[keys[-1]] = value

    save_config(config)
    console.print(f"[green]Set:[/green] {key} = {value}")


# ── Instance scaffolding ─────────────────────────────────────────

_INSTANCE_DIRS = [
    "profiles/users",
    "profiles/projects",
    "profiles/recipes",
    "profiles/goals",
    "raw",
    "wiki",
    "drafts",
    "mail/inbox",
    "mail/sent",
]

_INSTANCE_GITIGNORE = """\
# Python
__pycache__/
*.py[cod]
*.egg-info/

# Virtual env
.venv/
venv/
env/

# IDE / OS
.idea/
.vscode/
.DS_Store
Thumbs.db

# OKS local per-machine state (access counts, fingerprints) — NOT synced
.oks/

# Trace append locks (runtime state, not trace content)
raw/executions/*/.append.lock

# NOTE: wiki/, drafts/, profiles/ are intentionally TRACKED — they ARE your
# memory. Unlike the open-knowledge-studio code repo (which ignores wiki/ &
# drafts/ so it ships clean), an instance commits its knowledge to git.
"""


_SHARED_ASSETS = ("templates", "_meta", "settings", "profiles")

# How each agent ecosystem's directory is assembled from the single-source
# components under assets/. Supporting another agent is one line here.
_AGENT_TARGETS = {
    ".claude": {"config": "claude", "skills": True, "hooks": True, "rules": True},
    ".codex": {"config": "codex", "skills": False, "hooks": True, "rules": False},
    ".agents": {"config": None, "skills": True, "hooks": False, "rules": False},
}


def _asset_source() -> Path | None:
    """Locate the instance-template tree.

    A source checkout is authoritative during development; `_assets/` may be a
    stale build artifact. Installed wheels have no repo root and use `_assets/`,
    which is a verbatim copy of `assets/` — so both share one layout.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and (parent / "assets").is_dir():
            return parent / "assets"
    packaged = Path(__file__).resolve().parent / "_assets"
    if packaged.is_dir() and any(packaged.iterdir()):
        return packaged
    return None


def _materialize_assets(root: Path, base: Path, overwrite: bool) -> list[str]:
    """Assemble instance directories from the single-source asset tree."""
    import shutil

    def copy_into(src: Path, dest: Path) -> bool:
        """Merge per file: never clobber what the user changed unless upgrading.

        A directory-level check would skip whole trees, because `init` creates
        the bucket directories (profiles/...) before assets are materialized.
        """
        wrote = False
        for item in sorted(src.rglob("*")):
            target = dest / item.relative_to(src)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            wrote = True
        return wrote

    done: list[str] = []
    for name in _SHARED_ASSETS:
        src = base / name
        if src.is_dir() and copy_into(src, root / name):
            done.append(name)

    for dest_name, spec in _AGENT_TARGETS.items():
        dest = root / dest_name
        wrote = False
        if spec["config"]:
            config_dir = base / "agent-config" / spec["config"]
            if config_dir.is_dir():
                wrote |= copy_into(config_dir, dest)
        for component in ("skills", "hooks", "rules"):
            src = base / component
            if spec[component] and src.is_dir():
                wrote |= copy_into(src, dest / component)
        if wrote:
            done.append(dest_name)
    return done


@app.command()
def init(
    path: str = typer.Argument(..., help="Target directory for the new knowledge instance"),
    set_default: Optional[bool] = typer.Option(
        None, "--set-default/--no-set-default",
        help=(
            "Register this folder as the active KB in ~/.oks/config.json. "
            "Default: only when no active KB is registered yet"
        ),
    ),
    git: bool = typer.Option(
        True, "--git/--no-git", help="Run `git init` in the instance folder",
    ),
    upgrade: bool = typer.Option(
        False, "--upgrade",
        help="Re-copy bundled assets (skills/templates/_meta/settings), overwriting them; your memory (wiki/drafts/profiles) is untouched",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Scaffold into a non-empty directory that is not already a knowledge base",
    ),
):
    """Scaffold a new knowledge INSTANCE folder (e.g. your personal artboy-knowledge-studio).

    Creates the bucket structure and a .gitignore that TRACKS your memory
    (wiki/, drafts/, profiles/) while ignoring only per-machine state (.oks/).
    Points ~/.oks/config.json at the new folder only when no active KB is
    registered yet; pass --set-default to switch an existing one.
    """
    root = Path(path).expanduser().resolve()

    # Refuse to scaffold into an existing non-empty directory that is not
    # already a KB (missing wiki/) — protects arbitrary folders from being
    # hijacked. Re-running on an existing KB is idempotent and allowed.
    if (
        root.is_dir()
        and any(root.iterdir())
        and not (root / "wiki").is_dir()
        and not force
    ):
        console.print(
            f"[red]Refusing to scaffold into non-empty directory:[/red] {root}\n"
            f"It does not look like a knowledge base (no wiki/). Init would create:\n"
            + "\n".join(f"  - {d}/" for d in _INSTANCE_DIRS)
            + "\n  - .claude/ templates/ _meta/ settings/ (bundled assets)"
            + "\n  - .gitignore"
            + "\n\nRe-run with [bold]--force[/bold] to proceed anyway."
        )
        raise typer.Exit(1)

    root.mkdir(parents=True, exist_ok=True)

    for d in _INSTANCE_DIRS:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        (p / ".gitkeep").touch()

    base = _asset_source()
    if base is None:
        console.print(
            "[yellow]No bundled assets found — skills/templates not materialized.[/yellow]\n"
            "  Reinstall the canonical main source with pipx, then retry:\n"
            "  pipx upgrade open-knowledge-studio\n"
            "  or run python cli/scripts/bundle_assets.py in the repo before installing."
        )
    else:
        copied = _materialize_assets(root, base, overwrite=upgrade)
        if copied:
            console.print(f"[green]Materialized assets:[/green] {', '.join(copied)}")
        else:
            console.print("[dim]Assets already present (use --upgrade to refresh).[/dim]")

    gitignore = root / ".gitignore"
    if gitignore.exists():
        console.print(f"[yellow]Kept existing[/yellow] .gitignore ({gitignore})")
    else:
        gitignore.write_text(_INSTANCE_GITIGNORE, encoding="utf-8")
        console.print(f"[green]Wrote[/green] {gitignore}")

    if git and not (root / ".git").exists():
        import subprocess
        try:
            subprocess.run(
                ["git", "init"], cwd=str(root),
                check=True, capture_output=True, text=True,
            )
            console.print(f"[green]git init[/green] {root}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            console.print(f"[yellow]Skipped git init:[/yellow] {e}")

    if set_default is not False:
        from knowledge_studio.config import init_config, load_config

        current = load_config().get("knowledge_base_path")
        adopting = set_default is True or not current
        if adopting:
            init_config(str(root))
            console.print(f"[green]Active KB set:[/green] {root}")
        elif Path(current).resolve() != root:
            # Replacing this silently loses the old path for good, and every
            # later `oks ingest` / `oks wiki create` would write here instead.
            console.print(
                f"[yellow]Active KB left unchanged:[/yellow] {current}\n"
                f"  to switch: [bold]oks init {root} --set-default[/bold]"
            )

    console.print(
        f"\n[bold]{t('init_ready')}[/bold]\n"
        f"{t('init_step_install')}\n"
        f"{t('init_step_ingest')}\n"
        f"{t('init_step_status')}\n"
        f"\n[dim]{t('init_capabilities')}[/dim]\n"
        f"  [dim]watch    - 视频/音频 (faster-whisper + yt-dlp + RapidOCR)[/dim]\n"
        f"  [dim]document - Office/HTML/文本 (markitdown)[/dim]\n"
        f"  [dim]pdf      - PDF (MinerU)[/dim]\n"
        f"  [dim]formula  - 公式 OCR (PaddleOCR)[/dim]"
    )


# ── Optional editor hooks (opt-in auto-recall) ───────────────────

# Hook commands are written as absolute paths (see hook_install). Old
# installs wired the relative path below; matching is done by script name
# so both forms are recognized.
_RECALL_HOOK_SCRIPT_NAME = "user-prompt-recall.sh"
_RECALL_HOOK_SCRIPTS = ("user-prompt-recall.py", "user-prompt-recall.sh", "post-tool-edit.py", "post-tool-edit.sh")
_POST_TOOL_SCRIPT_NAME = "post-tool-edit.sh"
_HOOK_EDITORS = {
    "claude": ".claude/settings.json",
    "qoder": ".qoder/settings.json",
}


@app.command(name="skills-install")
def skills_install(
    force: bool = typer.Option(False, "--force", help="Overwrite existing skills"),
) -> None:
    """Materialize bundled skills into .claude/skills/ + .agents/skills/ (current KB).

    Use after upgrading oks to refresh skills (e.g. /assess replacing /start),
    without re-running full `oks init`.
    """
    root = Path.cwd()
    if not (root / "wiki").is_dir():
        console.print("[red]Not in a knowledge base directory (no wiki/).[/red]")
        raise typer.Exit(1)
    base = _asset_source()
    if base is None:
        console.print("[red]No bundled assets found. Reinstall: pipx upgrade open-knowledge-studio[/red]")
        raise typer.Exit(1)
    import shutil
    done: list[str] = []
    for dest_name, spec in _AGENT_TARGETS.items():
        if not spec.get("skills"):
            continue
        dest = root / dest_name / "skills"
        if force and dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        wrote = False
        src = base / "skills"
        if src.is_dir():
            for item in sorted(src.rglob("*")):
                target = dest / item.relative_to(src)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists() and not force:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                wrote = True
        if wrote:
            done.append(dest_name)
    if done:
        skill_names = sorted(p.name for p in (base / "skills").iterdir() if p.is_dir()) if (base / "skills").is_dir() else []
        console.print(f"[green]Installed skills into:[/green] {', '.join(done)}")
        console.print(f"[dim]Skills: {', '.join(skill_names)}[/dim]")
    else:
        console.print("[dim]Skills already present (use --force to refresh).[/dim]")


def _instance_root(path: str | None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    from knowledge_studio.config import get_kb_root
    return get_kb_root()


@mail_app.command("send")
def mail_send(
    body: str = typer.Option(..., "--body", "-b", help="Mail body text"),
    to: str = typer.Option("@all", "--to", help="Recipient (@all or @agent-id)"),
    type: str = typer.Option("message", "--type", help="message | conflict | handoff"),
    title: str = typer.Option("", "--title", "-t", help="Mail title"),
    priority: str = typer.Option("normal", "--priority", help="normal | urgent"),
) -> None:
    """Send a mail to inbox/ (Agent-to-agent communication)."""
    from datetime import datetime
    import os as _os
    root = _instance_root(None)
    inbox = root / "mail" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ts = now.strftime("%Y%m%dT%H%M%S")
    from_id = _os.environ.get("OKS_AGENT_ID", "human")
    to_field = to if to.startswith("@") else f"@{to}"
    title_line = title or "(no title)"
    content = (
        "---\n"
        f"from: {from_id}\n"
        f"to: {to_field}\n"
        f"timestamp: {now.isoformat()}\n"
        "read: false\n"
        f"type: {type}\n"
        f"priority: {priority}\n"
        "action: none\n"
        "---\n\n"
        f"# {title_line}\n\n"
        f"{body}\n"
    )
    slug = f"{ts}-{from_id}"
    (inbox / f"{slug}.md").write_text(content, encoding="utf-8")
    console.print(f"[green]Sent mail:[/green] {slug} -> {to_field}")


@mail_app.command("inbox")
def mail_inbox() -> None:
    """List unread mail."""
    root = _instance_root(None)
    inbox = root / "mail" / "inbox"
    if not inbox.is_dir():
        console.print("[dim]No mail inbox.[/dim]")
        return
    unread = []
    for f in sorted(inbox.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            parts = text.split("---")
            if len(parts) >= 2 and "read: false" in parts[1]:
                title = ""
                for line in parts[2].split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                unread.append((f.stem, title))
        except Exception:
            continue
    if not unread:
        console.print("[dim]No unread mail.[/dim]")
        return
    console.print(f"[bold]Unread mail ({len(unread)}):[/bold]")
    for slug, title in unread:
        console.print(f"  - [cyan]{slug}[/cyan]  {title}")


@mail_app.command("read")
def mail_read(
    id: str = typer.Argument(..., help="Mail slug (timestamp-from)"),
) -> None:
    """Mark a mail as read."""
    root = _instance_root(None)
    f = root / "mail" / "inbox" / f"{id}.md"
    if not f.exists():
        console.print(f"[red]Mail not found:[/red] {id}")
        raise typer.Exit(1)
    content = f.read_text(encoding="utf-8")
    content = content.replace("read: false", "read: true", 1)
    f.write_text(content, encoding="utf-8")
    console.print(f"[green]Marked read:[/green] {id}")


@mail_app.command("count")
def mail_count() -> None:
    """Count unread mail (for hook use; prints number to stdout)."""
    root = _instance_root(None)
    inbox = root / "mail" / "inbox"
    if not inbox.is_dir():
        print("0")
        return
    n = 0
    for f in inbox.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
            parts = text.split("---")
            if len(parts) >= 2 and "read: false" in parts[1]:
                n += 1
        except Exception:
            continue
    print(n)


@registry_app.command("list")
def registry_list() -> None:
    """List terminal registry entries (agent+cwd -> profile/goal)."""
    import json
    root = _instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    if not path.is_file():
        console.print("[dim]No registry entries.[/dim]")
        return
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    if not entries:
        console.print("[dim]No registry entries.[/dim]")
        return
    console.print(f"[bold]Terminal registry ({len(entries)} entries):[/bold]")
    for e in entries:
        agent = e.get("agent_id", "?")
        cwd = e.get("cwd", "?")
        profile = e.get("profile_slug", "-")
        goals = ", ".join(e.get("goal_slugs", [])) or "-"
        scope = ", ".join(e.get("scope", [])) or "-"
        last = str(e.get("last_active", "?"))[:19]
        console.print(
            f"  [cyan]{agent}[/cyan] @ [dim]{cwd}[/dim]\n"
            f"    profile: {profile}  goals: {goals}  scope: {scope}  last: {last}"
        )


@registry_app.command("bind")
def registry_bind(
    agent_id: str = typer.Option(..., "--agent-id", help="Agent identity"),
    cwd: str = typer.Option(..., "--cwd", help="Terminal working directory"),
    profile: str = typer.Option("", "--profile", help="Profile slug (profiles/users/)"),
    goals: str = typer.Option("", "--goals", help="Comma-separated goal slugs"),
    scope: str = typer.Option("", "--scope", help="Comma-separated wiki areas to narrow recall (empty = all)"),
) -> None:
    """Bind an agent+cwd to a profile + goals (creates or updates entry)."""
    import json
    from datetime import datetime, timezone
    root = _instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                    if profile:
                        rec["profile_slug"] = profile
                    if goals:
                        rec["goal_slugs"] = [g.strip() for g in goals.split(",") if g.strip()]
                    if scope:
                        rec["scope"] = [s.strip() for s in scope.split(",") if s.strip()]
                    rec["last_active"] = ts
                    found = True
                    lines.append(json.dumps(rec, ensure_ascii=False))
                else:
                    lines.append(line)
            except Exception:
                lines.append(line)
    if not found:
        rec = {
            "agent_id": agent_id,
            "cwd": cwd,
            "profile_slug": profile,
            "goal_slugs": [g.strip() for g in goals.split(",") if g.strip()],
            "first_seen": ts,
            "last_active": ts,
            "status": "active",
        }
        if scope:
            rec["scope"] = [s.strip() for s in scope.split(",") if s.strip()]
        lines.append(json.dumps(rec, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(
        f"[green]Bound[/green] {agent_id} @ {cwd}\n"
        f"  profile: {profile or '-'}  goals: {goals or '-'}  scope: {scope or '-'}"
    )


@registry_app.command("remove")
def registry_remove(
    agent_id: str = typer.Option(..., "--agent-id", help="Agent identity"),
    cwd: str = typer.Option(..., "--cwd", help="Terminal working directory"),
) -> None:
    """Remove a registry entry."""
    import json
    root = _instance_root(None)
    path = root / "profiles" / "agents" / "registry.jsonl"
    if not path.is_file():
        console.print("[dim]No registry.[/dim]")
        return
    lines = []
    removed = False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("agent_id") == agent_id and rec.get("cwd") == cwd:
                removed = True
                continue
            lines.append(line)
        except Exception:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if removed:
        console.print(f"[green]Removed[/green] {agent_id} @ {cwd}")
    else:
        console.print(f"[yellow]Not found[/yellow] {agent_id} @ {cwd}")


def _ensure_recall_scripts(root: Path) -> list[str]:
    """Copy/refresh the recall hook scripts in <root>/.claude/hooks/.

    The .sh wrapper gets the current interpreter baked into its OKS_PYTHON
    fallback. If an existing .sh lacks the current bake (fresh copy still on
    `python3`, or baked against a stale interpreter), it is re-copied from
    the asset source and re-baked. The .py engine is only copied if missing.
    """
    import shutil
    import stat
    import sys

    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    base = _asset_source()
    src_dir = None
    if base is not None:
        src_dir = base / "hooks"

    baked = f'"${{OKS_PYTHON:-{sys.executable}}}"'
    created: list[str] = []
    for name in _RECALL_HOOK_SCRIPTS:
        dest = hooks_dir / name
        if dest.exists():
            if not name.endswith(".sh"):
                continue
            try:
                if baked in dest.read_text(encoding="utf-8"):
                    continue
            except OSError:
                pass
            # Stale interpreter bake — fall through to re-copy + re-bake.
        if src_dir is None or not (src_dir / name).is_file():
            raise FileNotFoundError(
                f"bundled hook script not found: {name} (asset source: {src_dir})"
            )
        shutil.copy2(src_dir / name, dest)
        if name.endswith(".sh"):
            text = dest.read_text(encoding="utf-8").replace(
                '"${OKS_PYTHON:-python3}"', baked
            )
            dest.write_text(text, encoding="utf-8")
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        created.append(name)
    return created


def _wire_userpromptsubmit(settings_path: Path, command: str) -> str:
    """Idempotently add a UserPromptSubmit command hook. Returns 'wired'|'exists'.

    Recognizes previously wired entries (old relative or stale absolute
    paths) by script name and rewrites them in place instead of duplicating.
    """
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    ups = hooks.setdefault("UserPromptSubmit", [])
    stale: dict | None = None
    for group in ups:
        for h in group.get("hooks", []):
            cmd = h.get("command", "")
            if cmd == command:
                return "exists"
            if cmd.endswith(_RECALL_HOOK_SCRIPT_NAME):
                stale = h
    if stale is not None:
        stale["command"] = command
    else:
        ups.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    # This file belongs to the user's editor and holds permissions, other hooks
    # and MCP servers. Keep a backup and write atomically (CONSTITUTION P2/A5)
    # so a torn write can never destroy configuration we do not own.
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return "wired"


def _wire_posttooluse(settings_path: Path, command: str) -> str:
    """Idempotently add a PostToolUse command hook (file conflict detection)."""
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    ptu = hooks.setdefault("PostToolUse", [])
    stale: dict | None = None
    for group in ptu:
        for h in group.get("hooks", []):
            cmd = h.get("command", "")
            if cmd == command:
                return "exists"
            if cmd.endswith(_POST_TOOL_SCRIPT_NAME):
                stale = h
    if stale is not None:
        stale["command"] = command
    else:
        ptu.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return "wired"


def _hook_is_wired(settings_path: Path) -> bool:
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return False
    for group in data.get("hooks", {}).get("UserPromptSubmit", []):
        for h in group.get("hooks", []):
            if h.get("command", "").endswith(_RECALL_HOOK_SCRIPT_NAME):
                return True
    return False


@hook_app.command("install")
def hook_install(
    editor: str = typer.Option(
        "both", "--editor", "-e", help="Which editor(s) to wire: claude | qoder | both"
    ),
    path: Optional[str] = typer.Option(
        None, "--path", help="Instance root (default: active KB from ~/.oks/config.json)"
    ),
):
    """Wire the auto-recall UserPromptSubmit hook into your editor settings (opt-in).

    Copies the recall hook script into .claude/hooks/ (if missing) and adds a
    UserPromptSubmit entry to the chosen editor's settings. Idempotent and
    non-destructive: existing settings and hooks are preserved.
    """
    editor = editor.lower().strip()
    if editor not in ("claude", "qoder", "both"):
        console.print("[red]--editor must be one of: claude, qoder, both[/red]")
        raise typer.Exit(1)

    import platform
    if platform.system() == "Windows":
        console.print(
            "[yellow]Warning: hooks are bash scripts and will not run on native Windows.[/yellow]\n"
            "  Use WSL (or Git Bash configured as the hook shell) for auto-recall to work."
        )

    root = _instance_root(path)
    if not root.is_dir():
        console.print(f"[red]Instance root not found:[/red] {root}")
        raise typer.Exit(1)

    try:
        created = _ensure_recall_scripts(root)
    except FileNotFoundError as e:
        console.print(
            f"[red]Cannot install hook — bundled assets missing.[/red]\n"
            f"  {e}\n"
            f"  This happens when oks was installed from source without the asset bundle.\n"
            f"  Fix: [bold]pipx upgrade open-knowledge-studio[/bold],\n"
            f"  or run [bold]python cli/scripts/bundle_assets.py[/bold] in the repo before installing."
        )
        raise typer.Exit(1)
    if created:
        console.print(f"[green]Installed hook script:[/green] {', '.join(created)}")

    hook_cmd = (root / ".claude" / "hooks" / _RECALL_HOOK_SCRIPT_NAME).resolve().as_posix()
    post_cmd = (root / ".claude" / "hooks" / _POST_TOOL_SCRIPT_NAME).resolve().as_posix()
    editors = ("claude", "qoder") if editor == "both" else (editor,)
    for name in editors:
        settings_path = root / _HOOK_EDITORS[name]
        result = _wire_userpromptsubmit(settings_path, hook_cmd)
        post_result = _wire_posttooluse(settings_path, post_cmd)
        label = "[green]wired[/green]" if result == "wired" else "[dim]already wired[/dim]"
        post_label = "[green]+conflict[/green]" if post_result == "wired" else "[dim]+conflict (exists)[/dim]"
        console.print(f"  {name}: {label} {post_label} → {settings_path}")

    console.print(
        "\n[bold]Auto-recall + conflict detection enabled.[/bold]\n"
        "New prompts inject relevant memory; file edits across agents trigger conflict mail.\n"
        "Tune via env: OKS_RECALL_FLOOR (0.7), OKS_RECALL_TOPN (3), OKS_RECALL_MINLEN (6),\n"
        "  OKS_CONFLICT_WINDOW (300s)."
    )


@hook_app.command("status")
def hook_status(
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
):
    """Show whether the auto-recall hook is installed for each editor."""
    root = _instance_root(path)
    script = root / ".claude" / "hooks" / "user-prompt-recall.sh"
    console.print(f"[bold]Instance:[/bold] {root}")
    console.print(f"  script: {'present' if script.is_file() else 'missing'} ({script})")
    if script.is_file():
        import os
        import re
        import subprocess
        m = re.search(r"\$\{OKS_PYTHON:-([^}]+)\}", script.read_text(encoding="utf-8"))
        py = os.environ.get("OKS_PYTHON") or (m.group(1) if m else "python3")
        try:
            ok = subprocess.run(
                [py, "-c", "import knowledge_studio"],
                capture_output=True, timeout=15,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        state = ("[green]importable[/green]" if ok
                 else "[red]hook script has stale interpreter — "
                      "run `oks hook install` to re-bake[/red]")
        console.print(f"  engine: {state} (python: {py})")
    for name, rel in _HOOK_EDITORS.items():
        settings_path = root / rel
        wired = _hook_is_wired(settings_path)
        state = "[green]wired[/green]" if wired else "[dim]not wired[/dim]"
        console.print(f"  {name}: {state}")


if __name__ == "__main__":
    app()
