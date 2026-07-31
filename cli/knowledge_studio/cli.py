"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
from knowledge_studio.recall import (
    RECALL_RESPONSE_SCHEMA,
    SEARCH_RESPONSE_SCHEMA,
    describe_goal_selection,
    recall,
    recall_episodic,
    recall_knowledge,
)

# ── ingest: connector lives in the oks_connector package once installed,
# or under ../scripts in a source checkout ───────────────────────────
_connector_available = False
try:
    from oks_connector.raw_bundle_adapter import (
        build_parser as _connector_parser,
        run_ingest as _connector_run_ingest,
    )
    _connector_available = True
except ImportError:
    _SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    try:
        from raw_bundle_adapter import (
            build_parser as _connector_parser,
            run_ingest as _connector_run_ingest,
        )
        _connector_available = True
    except ImportError:
        pass


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
eval_app = typer.Typer(help="Offline recall evaluation and run comparison.")
trace_app = typer.Typer(help="Append-only execution traces and feedback.")
feishu_app = typer.Typer(help="Optional Feishu Base intake, review, and event-listening extension.")
capability_app = typer.Typer(help="Optional modality capabilities; core dependencies stay lightweight.")
app.add_typer(wiki_app, name="wiki")
app.add_typer(drafts_app, name="drafts")
app.add_typer(config_app, name="config")
app.add_typer(hook_app, name="hook")
app.add_typer(eval_app, name="eval")
app.add_typer(trace_app, name="trace")
app.add_typer(feishu_app, name="feishu")
app.add_typer(capability_app, name="capability")

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
    "feishu": {
        "purpose": "Private Base, form, bot review, and bounded listening",
        "deps": ["requests==2.34.2", "trafilatura==2.1.0"],
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
        install = "user-managed lark-cli" if name == "feishu" else f"oks capability install {name}"
        table.add_row(name, info["purpose"], install)
    console.print(table)


def _capability_already_installed(name: str) -> bool:
    """Check whether a capability is available (delegates to shared module)."""
    from capability_check import is_capability_available
    ok, _ = is_capability_available(name)
    return ok


@capability_app.command("install")
def capability_install(
    name: str = typer.Argument(..., help="watch, document, pdf, formula, or feishu"),
    yes: bool = typer.Option(False, "--yes", help="Execute the displayed installation command"),
):
    """Show or explicitly install one optional capability (heavy dependencies)."""
    info = _CAPABILITIES.get(name)
    if info is None:
        raise typer.BadParameter(f"unknown capability: {name}; run `oks capability list`")
    purpose = info["purpose"]

    if name == "feishu":
        deps = info["deps"]
        cmd = [sys.executable, "-m", "pip", "install"] + deps
        message = (
            f"[bold]{t('feishu_private')}[/bold]\n\n"
            f"Web intake dependencies:\n{' '.join(cmd)}"
        )
        if not yes:
            console.print(Panel.fit(
                f"{message}\n\nRe-run with --yes to install the web intake dependencies.",
                title=t("user_managed_capability"), border_style="cyan",
            ))
            return
        console.print(f"[yellow]{t('capability_installing', name=name)}[/yellow]")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            console.print(f"[bold red]{t('capability_failed', name=name, code=result.returncode)}[/bold red]")
            raise typer.Exit(result.returncode)
        console.print(f"[green]{t('capability_installed', name=name)}[/green]")
        console.print(Panel.fit(message, title=t("user_managed_capability"), border_style="cyan"))
        return

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


def _connector_install_hint() -> str:
    return ""  # no-op: connector is built into the monorepo


def _connector_command() -> str | None:
    """Connector is bundled as ``scripts/raw_bundle_adapter`` — no separate binary needed."""
    return "built-in" if _connector_available else None


def _recommended_capability(source: str) -> str:
    suffix = Path(source.split("?", 1)[0]).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".csv"}:
        return "document"
    return "watch"  # video, audio, and platform URLs all route to watch


@app.command()
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

    cli_args = ["ingest", source, "--mode", mode]
    if timeout_seconds is not None:
        cli_args.extend(["--timeout-seconds", str(timeout_seconds)])
    if progress:
        cli_args.append("--progress")
    if formula_secondary and needed == "pdf":
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


def _extractor_env_for(capability: str) -> str:
    return {"watch": "OKS_WATCH_PYTHON", "document": "OKS_DOCUMENT_PYTHON",
            "pdf": "OKS_MINERU_PYTHON", "formula": "OKS_FORMULA_PYTHON"}.get(capability, "")


def _feishu_worker_path() -> Path | None:
    configured = __import__("os").environ.get("OKS_FEISHU_WORKER")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(Path(__file__).resolve().parent / "_assets" / "scripts" / "feishu_base_worker.py")
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "scripts" / "feishu_base_worker.py")
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _run_feishu_worker(command: str, extra: list[str]) -> None:
    worker = _feishu_worker_path()
    if worker is None:
        console.print(Panel.fit(
            "[bold red]Feishu extension worker is not installed[/bold red]\n\n"
            "Set OKS_FEISHU_WORKER to the reviewed feishu_base_worker.py path. "
            "This extension deliberately does not create a hidden Feishu client or bypass login.",
            title="Action required",
            border_style="red",
        ))
        raise typer.Exit(2)
    raise typer.Exit(subprocess.run([sys.executable, str(worker), command, *extra]).returncode)


def _resolve_lark_cli() -> str | None:
    """Reuse the connector's shared resolver (LARK_CLI_EXE, Windows .cmd, npm)."""
    try:
        from oks_connector._lark_cli import resolve_lark_cli
    except ImportError:
        try:
            from _lark_cli import resolve_lark_cli
        except ImportError:
            return shutil.which("lark-cli") or shutil.which("lark-cli.exe")
    try:
        return str(resolve_lark_cli())
    except RuntimeError:
        return None


@feishu_app.command("auth")
def feishu_auth():
    """Show the configured Lark CLI authentication state; login remains user-controlled."""
    lark = _resolve_lark_cli()
    if lark is None:
        console.print("[bold red]lark-cli is not installed.[/bold red] Install and authenticate it before Feishu actions.")
        raise typer.Exit(2)
    raise typer.Exit(subprocess.run([lark, "auth", "status"]).returncode)


@feishu_app.command("form")
def feishu_form(url: str = typer.Option(..., "--url", help="Feishu Base form URL to open in your browser")):
    """Display the human submission form; authentication and submission stay in the user session."""
    console.print(Panel.fit(f"[bold]Feishu intake form[/bold]\n{url}\n\nOpen it in your authenticated browser to submit a capture.", border_style="cyan"))


@feishu_app.command("submit")
def feishu_submit(
    content: str = typer.Argument(..., help="Capture text or URL"),
    thought: str = typer.Option("", "--thought", help="Optional user context"),
    rating: Optional[str] = typer.Option(None, "--rating", help="Optional A/B/C rating"),
):
    """Submit one capture to an authenticated Feishu Base without opening the form."""
    if rating is not None and rating not in {"A", "B", "C"}:
        raise typer.BadParameter("--rating must be A, B, or C")
    extra = [content, "--thought", thought]
    if rating is not None:
        extra.extend(["--rating", rating])
    _run_feishu_worker("enqueue", extra)


@feishu_app.command("run-once")
def feishu_run_once(limit: int = typer.Option(100, "--limit")):
    """Process one pending Feishu Base capture through Raw and review states."""
    _run_feishu_worker("run-once", ["--limit", str(limit)])


@feishu_app.command("publish-candidate")
def feishu_publish_candidate(
    record_id: str = typer.Option(..., "--record-id", help="Feishu Base record ID"),
    candidate_file: str = typer.Option(..., "--candidate-file", help="Agent-authored candidate Markdown file"),
):
    """Publish a Candidate to one processed Base record for human review."""
    _run_feishu_worker("publish-candidate", ["--record-id", record_id, "--candidate-file", candidate_file])


@feishu_app.command("review-once")
def feishu_review_once(limit: int = typer.Option(100, "--limit")):
    """Apply one bounded Base review action and promote approved Candidate content."""
    _run_feishu_worker("review-once", ["--limit", str(limit)])


@feishu_app.command("reconcile-review")
def feishu_reconcile_review(
    prompt_message_id: str = typer.Option(..., "--prompt-message-id", help="Candidate review prompt message ID"),
    reply_message_id: str = typer.Option(..., "--reply-message-id", help="Human review reply message ID"),
):
    """Recover one review reply that was missed by the bounded event listener."""
    _run_feishu_worker(
        "reconcile-review",
        ["--prompt-message-id", prompt_message_id, "--reply-message-id", reply_message_id],
    )


@feishu_app.command("listen")
def feishu_listen(max_events: int = typer.Option(1, "--max-events"), timeout: str = typer.Option("5m", "--timeout")):
    """Consume bounded Feishu review replies; use an external scheduler for continuous service."""
    _run_feishu_worker("listen-reviews", ["--max-events", str(max_events), "--timeout", timeout])


@feishu_app.command("setup")
def feishu_setup(
    base_token: Optional[str] = typer.Option(None, "--base-token", help="已有 Base token（跳过创建）"),
    base_name: str = typer.Option("Open Knowledge Studio", "--base-name"),
    table_name: str = typer.Option("每日知识采集", "--table-name"),
    show_credentials: bool = typer.Option(False, "--show-credentials", help="显示完整 Base token（仅限受控终端）"),
):
    """自动创建飞书 Base、采集表和表单。需要 lark-cli 已认证。"""
    lark = _resolve_lark_cli()
    if lark is None:
        console.print("[bold red]lark-cli 未安装。[/bold red]")
        raise typer.Exit(2)
    worker = _feishu_worker_path()
    if worker is None:
        console.print("[bold red]找不到 worker 脚本。[/bold red]")
        raise typer.Exit(2)
    setup_script = worker.parent / "feishu_setup.py"
    if not setup_script.is_file():
        module = importlib.util.find_spec("feishu_setup")
        if module and module.origin:
            setup_script = Path(module.origin)
    if not setup_script.is_file():
        console.print(f"[bold red]找不到: {setup_script}[/bold red]")
        raise typer.Exit(2)
    cmd = [sys.executable, str(setup_script)]
    if base_token:
        cmd.extend(["--base-token", base_token])
    cmd.extend(["--base-name", base_name, "--table-name", table_name])
    if show_credentials:
        cmd.append("--show-credentials")
    raise typer.Exit(subprocess.run(cmd).returncode)


# ── Search / Recall ──────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    scope: Optional[str] = typer.Option(None, "--scope", "--domain", "-d", help="Soft scope: narrow to one area (opt-in, not a hard partition)"),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
    goal: str = typer.Option("active", "--goal", help="Goal mode: active | none | <goal-slug>"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
    explain: bool = typer.Option(False, "--explain", help="Include score components and match reasons"),
):
    """Search wiki pages using the 6+1-factor recall engine (read-only)."""
    output_format = _validate_output_format(output_format)
    try:
        results = recall_knowledge(
            query=query,
            limit=limit,
            scope=scope,
            goal=goal,
            explain=explain,
            type_filter=type_filter,
        )
        goal_context = describe_goal_selection(goal)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    if output_format == "json":
        _emit_json({
            "schema_version": SEARCH_RESPONSE_SCHEMA,
            "query": query,
            "scope": scope,
            "limit": limit,
            "type_filter": type_filter,
            "goal": goal_context,
            "result_count": len(results),
            "knowledge": results,
        })
        return

    if not results:
        console.print("[dim]No results found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Slug", style="dim", max_width=30)
    table.add_column("Title", max_width=40)
    table.add_column("Type", max_width=12)
    table.add_column("Area", max_width=12)
    table.add_column("Score", justify="right", max_width=8)
    table.add_column("Relevance", justify="right", max_width=10)
    if explain:
        table.add_column("Why", max_width=50)

    for r in results:
        row = [
            r["slug"],
            r["title"],
            r.get("type", ""),
            r.get("area", ""),
            f"{r.get('score', 0):.2f}",
            f"{r.get('relevance', 0):.2f}",
        ]
        if explain:
            row.append(", ".join(r.get("reasons", [])))
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]{len(results)} result(s) from wiki/[/dim]")


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
):
    """Two-path recall: episodic (raw/) + knowledge (wiki/)."""
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

    path = store.write_wiki_page(
        title=title,
        content=content,
        wiki_type=wiki_type,
        area=area,
        importance=importance,
    )
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
    updated = store.get_wiki_page(slug)
    console.print(
        f"[green]Recorded use:[/green] {slug} "
        f"(access_count={updated.get('access_count', 0)}, status={updated.get('status', 'active')})"
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
        drafted = d.get("drafted_at", "")
        if not isinstance(drafted, str):
            drafted = str(drafted)
        table.add_row(
            d["slug"],
            d.get("title", d["slug"]),
            d.get("draft_type", ""),
            d.get("draft_area", ""),
            drafted,
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


@drafts_app.command("reject")
def drafts_reject(slug: str = typer.Argument(help="Draft slug to reject")):
    """Delete a draft proposal."""
    try:
        store.reject_draft(slug)
        console.print(f"[green]Rejected:[/green] {slug}")
    except FileNotFoundError:
        console.print(f"[red]Draft not found:[/red] {slug}")
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


@app.command()
def metrics():
    """Show 4-dimension knowledge metrics."""
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
    from knowledge_studio.config import load_config, config_path

    config = load_config()
    console.print(f"[dim]Config file: {config_path()}[/dim]\n")
    console.print(Panel.fit(
        f"[bold]Knowledge Base[/bold]\n  {config.get('knowledge_base_path', '(not set)')}\n\n"
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


_ASSET_MAP = [
    ("claude", ".claude"),
    ("codex", ".codex"),
    ("agents", ".agents"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]

# Maintainer-only skills. Kept in the repo for development, never installed into
# a user's knowledge base. Must match setup.py / bundle_assets.py — a source
# checkout copies from the repo root, so the build-time exclusion is not enough.
_DEV_ONLY_ASSET_NAMES = ("review-upstream-pr", "upstream-pr-remediation")


def _asset_source() -> tuple[Path | None, bool]:
    """Locate the shareable asset layer. Returns (base, is_packaged).

    A source checkout is authoritative during development; `_assets/` may be a
    stale build artifact. Installed wheels have no repo root and use `_assets/`.
    """
    for parent in Path(__file__).resolve().parents:
        if (
            (parent / ".git").exists()
            and (parent / ".claude").is_dir()
            and (parent / "templates").is_dir()
            and (parent / "_meta").is_dir()
        ):
            return parent, False
    packaged = Path(__file__).resolve().parent / "_assets"
    if packaged.is_dir() and any(packaged.iterdir()):
        return packaged, True
    return None, False


def _materialize_assets(root: Path, base: Path, is_packaged: bool, overwrite: bool) -> list[str]:
    import shutil

    ignore = shutil.ignore_patterns(*_DEV_ONLY_ASSET_NAMES)
    done: list[str] = []
    for pkg_name, dest_name in _ASSET_MAP:
        src = base / (pkg_name if is_packaged else dest_name)
        if not src.is_dir():
            continue
        dest = root / dest_name
        if dest.exists() and not overwrite:
            continue
        # Merge-copy: refresh bundled files in place, keep user-owned files.
        shutil.copytree(src, dest, dirs_exist_ok=True, ignore=ignore)
        done.append(dest_name)
    return done


@app.command()
def init(
    path: str = typer.Argument(..., help="Target directory for the new knowledge instance"),
    set_default: bool = typer.Option(
        True, "--set-default/--no-set-default",
        help="Register this folder as the active KB in ~/.oks/config.json",
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
    By default points ~/.oks/config.json at the new folder so `oks` targets it
    from anywhere.
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

    base, is_packaged = _asset_source()
    if base is None:
        console.print(
            "[yellow]No bundled assets found — skills/templates not materialized.[/yellow]\n"
            "  Source installs lack the asset bundle. Fix: pip install open-knowledge-studio,\n"
            "  or run python cli/scripts/bundle_assets.py in the repo before installing."
        )
    else:
        copied = _materialize_assets(root, base, is_packaged, overwrite=upgrade)
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

    if set_default:
        from knowledge_studio.config import init_config
        init_config(str(root))
        console.print(f"[green]Active KB set:[/green] {root}")

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
_RECALL_HOOK_SCRIPTS = ("user-prompt-recall.py", "user-prompt-recall.sh")
_HOOK_EDITORS = {
    "claude": ".claude/settings.json",
    "qoder": ".qoder/settings.json",
}


def _instance_root(path: str | None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    from knowledge_studio.config import get_kb_root
    return get_kb_root()


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

    base, is_packaged = _asset_source()
    src_dir = None
    if base is not None:
        src_dir = base / ("claude/hooks" if is_packaged else ".claude/hooks")

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
            f"  Fix: [bold]pip install open-knowledge-studio[/bold] (PyPI wheel includes assets),\n"
            f"  or run [bold]python cli/scripts/bundle_assets.py[/bold] in the repo before installing."
        )
        raise typer.Exit(1)
    if created:
        console.print(f"[green]Installed hook script:[/green] {', '.join(created)}")

    hook_cmd = (root / ".claude" / "hooks" / _RECALL_HOOK_SCRIPT_NAME).resolve().as_posix()
    editors = ("claude", "qoder") if editor == "both" else (editor,)
    for name in editors:
        settings_path = root / _HOOK_EDITORS[name]
        result = _wire_userpromptsubmit(settings_path, hook_cmd)
        label = "[green]wired[/green]" if result == "wired" else "[dim]already wired[/dim]"
        console.print(f"  {name}: {label} → {settings_path}")

    console.print(
        "\n[bold]Auto-recall enabled.[/bold] New prompts will inject relevant memory.\n"
        "Tune via env: OKS_RECALL_FLOOR (0.7), OKS_RECALL_TOPN (3), OKS_RECALL_MINLEN (6)."
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
