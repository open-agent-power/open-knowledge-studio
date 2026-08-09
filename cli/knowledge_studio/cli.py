"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.markup import escape

from knowledge_studio import store
from knowledge_studio.config import get_kb_root
from knowledge_studio.i18n import t
from knowledge_studio.recall import (
    RECALL_RESPONSE_SCHEMA,
    SEARCH_RESPONSE_SCHEMA,
    describe_goal_selection,
    recall,
    recall_episodic,
    recall_knowledge,
)

# ── The legacy connector (oks_connector) was permanently removed in v0.4.0.
# Agent-native ingest via /ingest skill is the only path.
# Git tag v0.4.0-legacy-final preserves the old pipeline.
# Two essential stdlib-only utilities (capability_check, _lark_cli) were
# inlined into knowledge_studio/ — they are the sole survivors.


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
ingest_app = typer.Typer(
    help="Agent-native ingestion preparation and execution.",
    no_args_is_help=True,
)
security_app = typer.Typer(
    help="Credential redaction and security utilities.",
    no_args_is_help=True,
)
schema_app = typer.Typer(
    help="Protocol schema reference — list, show, and generate examples.",
    no_args_is_help=True,
)
app.add_typer(capability_app, name="capability")
app.add_typer(ingest_app, name="ingest")
app.add_typer(security_app, name="security")
app.add_typer(schema_app, name="schema")

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
    try:
        from knowledge_studio.capability_check import is_capability_available
    except ImportError:
        return False
    ok, _ = is_capability_available(name)
    return ok


def _managed_capability_python(name: str) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    configured = os.environ.get("OKS_CAPABILITY_ROOT")
    root = Path(configured).expanduser() if configured else Path.home() / ".oks" / "capabilities"
    return root / name / "venv" / relative


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
    capability_python = _managed_capability_python(name)
    environment = capability_python.parent.parent
    create_cmd = [sys.executable, "-m", "venv", str(environment)]
    cmd = [str(capability_python), "-m", "pip", "install"] + deps

    if not yes:
        console.print(Panel.fit(
            f"[bold]{name}[/bold]: {purpose}\n\n"
            f"Managed environment: {environment}\n"
            f"Create: {' '.join(create_cmd)}\n"
            f"{t('capability_install_prompt', n=len(deps), cmd=' '.join(cmd))}",
            title=t("optional_install"), border_style="yellow",
        ))
        return

    console.print(f"[yellow]{t('capability_installing', name=name)}[/yellow]")
    if not capability_python.is_file():
        created = subprocess.run(create_cmd)
        if created.returncode != 0:
            console.print(f"[bold red]{t('capability_failed', name=name, code=created.returncode)}[/bold red]")
            raise typer.Exit(created.returncode)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        console.print(f"[bold red]{t('capability_failed', name=name, code=result.returncode)}[/bold red]")
        raise typer.Exit(result.returncode)
    console.print(f"[green]{t('capability_installed', name=name)}[/green]")


def _connector_install_hint() -> str:
    return "Agent-native ingest is the default path — use /ingest skill in Claude Code"


def _connector_command() -> str | None:
    """Legacy connector was permanently deleted in v0.4.0."""
    return None


def _recommended_capability(source: str, *, pdf_engine: str = "pdf-lite") -> str:
    suffix = Path(source.split("?", 1)[0]).suffix.lower()
    if suffix == ".pdf":
        return "pdf" if pdf_engine == "mineru" else "pdf-lite"
    if suffix in {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".csv"}:
        return "document"
    return "watch"  # video, audio, and platform URLs all route to watch


@ingest_app.command("prepare")
def ingest_prepare(
    source: str = typer.Argument(..., help="Local file or URL to prepare for ingestion"),
    kb_root: Optional[str] = typer.Option(
        None, "--kb-root", help="Knowledge base root (default: from OKS_ROOT or config)",
    ),
    json_output: bool = typer.Option(
        True, "--json/--text", help="Output as JSON",
    ),
):
    """Prepare a source for Agent ingestion — generate protocol skeleton.

    Creates a run workspace under .oks/runs/ and generates
    source-envelope.json, evidence-manifest.json, and evidence fragments
    with all deterministic fields pre-filled.  The Agent only needs to
    supply evidence content — no hand-crafted protocol JSON required.

    For text sources (Markdown, plain text, CSV) the evidence skeleton
    is pre-filled and ready to commit.
    """
    from knowledge_studio.ingest_prepare import prepare_ingest

    root = Path(kb_root).expanduser().resolve() if kb_root else None
    result = prepare_ingest(source, kb_root=root)

    if json_output:
        import json as _json
        print(_json.dumps(result, ensure_ascii=False, indent=2))
    else:
        console.print(Panel.fit(
            f"[bold]Source:[/bold] {source}\n"
            f"[bold]Modality:[/bold] {result['modality']}\n"
            f"[bold]Run ID:[/bold] {result['run_id']}\n"
            f"[bold]Manifest dir:[/bold] {result['manifest_dir']}\n\n"
            + "\n".join(f"  [green]+[/green] {f}" for f in result["files_generated"])
            + f"\n\n[bold cyan]{result['next_step']}[/bold cyan]",
            title="Ingest Prepared",
            border_style="green" if result.get("text_ready") else "yellow",
        ))


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
    worker_command = [
        sys.executable,
        str(worker),
        "--knowledge-root",
        str(get_kb_root()),
        command,
        *extra,
    ]
    worker_env = os.environ.copy()
    worker_env["OKS_KNOWLEDGE_ROOT"] = str(get_kb_root())
    raise typer.Exit(subprocess.run(worker_command, env=worker_env).returncode)


def _resolve_lark_cli() -> str | None:
    """Reuse the connector's shared resolver (LARK_CLI_EXE, Windows .cmd, npm)."""
    try:
        from knowledge_studio._lark_cli import resolve_lark_cli
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
def feishu_form(
    url: str = typer.Option(None, "--url", help="Custom form URL to display"),
    share_token: str = typer.Option(None, "--share-token", help="Feishu form share token (shrcnXXX) to construct a fillable URL"),
):
    """Display the fillable form URL. Use --share-token with the token from Base UI → Share."""
    if share_token:
        # Construct the correct fillable form URL
        brand = os.environ.get("LARK_BRAND", "feishu")
        domain = "feishu.cn" if brand == "feishu" else "larkoffice.com"
        form_url = f"https://{domain}/share/base/form/{share_token}"
        console.print(Panel.fit(
            f"[bold]📋 填写表单链接[/bold]\n{form_url}\n\n"
            "把这个链接发给用户即可填写，不需要登录 Base 编辑界面。",
            border_style="green",
        ))
        return
    if url:
        console.print(Panel.fit(
            f"[bold]Feishu intake form[/bold]\n{url}\n\n"
            "Open it in your authenticated browser to submit a capture.",
            border_style="cyan",
        ))
        return
    # No URL or share token — show how to get the form share link
    console.print(Panel.fit(
        "[bold]获取填写表单链接[/bold]\n\n"
        "1. 打开 Base → 左侧找到 \"OKS Daily Knowledge Intake\" 表单\n"
        "2. 点表单右边的 ··· → 分享 → 复制链接\n"
        "3. 然后运行: oks feishu form --share-token shrcnXXX\n\n"
        "⚠️ 注意：不要用 table/view 链接，那个是编辑界面，填不了表单。",
        border_style="yellow",
    ))


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


@feishu_app.command("pending")
def feishu_pending(
    limit: int = typer.Option(200, "--limit"),
):
    """List pending Inbox records from Feishu Base (Pull-mode entry point).

    Returns JSON with record_id, content, thought, status, created,
    and metadata for each pending record. The Agent filters records
    by date as needed (e.g., "today's") client-side.

    No daemon, no WebSocket, no background service needed.
    """
    _run_feishu_worker("pending", ["--limit", str(limit)])


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
    table_id: Optional[str] = typer.Option(None, "--table-id", help="指定已有采集表 ID"),
    base_name: str = typer.Option("Open Knowledge Studio", "--base-name"),
    table_name: Optional[str] = typer.Option(None, "--table-name", help="采集表名称"),
    repair_schema: bool = typer.Option(False, "--repair-schema", help="修复安全的字段 schema drift"),
    yes: bool = typer.Option(False, "--yes", help="确认 schema 高风险字段写入"),
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
    if table_id:
        cmd.extend(["--table-id", table_id])
    cmd.extend(["--base-name", base_name])
    if table_name:
        cmd.extend(["--table-name", table_name])
    if repair_schema:
        cmd.append("--repair-schema")
    if yes:
        cmd.append("--yes")
    if show_credentials:
        cmd.append("--show-credentials")
    raise typer.Exit(subprocess.run(cmd).returncode)


@capability_app.command("catalog")
def capability_catalog_cmd(
    json_output: bool = typer.Option(False, "--json/--text", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full provider details"),
):
    """List available capability actions and their providers."""
    from knowledge_studio.capability_commands import capability_list

    result = capability_list()
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif verbose:
        for p in result["providers"]:
            console.print(f"[bold]{p['id']}[/bold] ({p['execution']})")
            for action in p.get("actions", []):
                console.print(f"  - {action}")
            console.print()
    else:
        # User-facing summary: group by common capabilities
        summary: dict[str, list[str]] = {}
        for p in result["providers"]:
            for action in p.get("actions", []):
                if action not in summary:
                    summary[action] = []
                summary[action].append(p["id"])
        table = Table(title="Capability → Provider")
        table.add_column("Capability")
        table.add_column("Providers")
        for action in sorted(summary):
            providers = ", ".join(summary[action])
            table.add_row(action, providers)
        console.print(table)


@capability_app.command("status")
def capability_status_cmd(
    json_output: bool = typer.Option(True, "--json/--text", help="Output as JSON"),
):
    """Combined capability catalog + availability for Agent decision-making.

    Returns what actions exist, which providers supply them, AND whether
    each provider is currently available.  The Agent calls this once to
    get a complete environmental facts picture before selecting providers.
    """
    from knowledge_studio.capability_commands import capability_status

    result = capability_status()
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Text output: group by capability for human scanning
        console.print(f"[bold]Overall:[/bold] {result['overall']}\n")
        for action_name, action_info in sorted(result["actions"].items()):
            providers = result["by_action"].get(action_name, [])
            provider_strs = []
            for pid in providers:
                p = next((pp for pp in result["providers"] if pp["id"] == pid), None)
                if p is None:
                    continue
                icon = {"ready": "✓", "not_configured": "○", "unavailable": "✗",
                        "runtime_only": "?", "blocked": "—"}.get(p["status"], "?")
                provider_strs.append(f"{icon} {p['label']}")
            console.print(f"[cyan]{action_info['label']}[/cyan] ({action_name})")
            console.print(f"  {', '.join(provider_strs) if provider_strs else '[dim]no provider[/dim]'}")
        console.print(f"\n[dim]Use --json for machine-readable output.[/dim]")


@capability_app.command("doctor")
def capability_doctor_cmd(
    json_output: bool = typer.Option(False, "--json/--text", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all checks and details"),
):
    """Diagnose local environment — commands, env vars, Python packages."""
    from knowledge_studio.capability_commands import capability_doctor

    result = capability_doctor()
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Group providers by category for human-friendly output
    categories: dict[str, list[dict]] = {}
    for p in result["providers"]:
        exec_type = p.get("execution", "unknown")
        cat = {"managed": "Local", "agent_native": "Built-in", "external": "Remote", "human": "Manual"}.get(exec_type, "Other")
        categories.setdefault(cat, []).append(p)

    for cat_name in ("Built-in", "Local", "Remote", "Manual", "Other"):
        providers = categories.get(cat_name, [])
        if not providers:
            continue
        console.print(f"\n[bold underline]{cat_name}[/bold underline]")
        for p in sorted(providers, key=lambda x: x["id"]):
            label = p.get("label", p["id"])
            healthy = p.get("healthy", False)

            # Determine readiness
            checks = p.get("checks", [])
            failures = [c for c in checks if c.get("available") is False and c.get("type") not in ("note",)]
            warnings = [c for c in checks if c.get("type") == "note" and c.get("available") is False]
            ready = not failures

            if ready:
                icon = "[green]Ready[/green]"
            elif any(c.get("required") is not False for c in failures):
                icon = "[red]Missing[/red]"
            else:
                icon = "[yellow]Partial[/yellow]"

            # Summary line
            cap_summary = ""
            if verbose and p["id"] in {"pdf-lite", "rapidocr", "ffmpeg", "yt-dlp", "firecrawl", "agentkey"}:
                extra_parts = []
                for c in checks:
                    if c.get("type") == "command" and c.get("available"):
                        extra_parts.append(c["name"])
                    elif c.get("type") == "env_var" and c.get("available"):
                        extra_parts.append(c["name"] + " set")
                if extra_parts:
                    cap_summary = ": " + ", ".join(extra_parts)

            console.print(f"  {icon} {label} ({p['id']}){cap_summary}")

            if verbose:
                for c in checks:
                    if c.get("type") == "note":
                        console.print(f"      [dim]i {c.get('message', '')}[/dim]")
                    elif c.get("available") is False:
                        req = " (optional)" if c.get("required") is False else ""
                        console.print(f"      [red]x[/red] {c['name']}{req}: {c.get('suggestion', 'missing')}")
                    elif c.get("available") is True:
                        detail = c.get("path") or c.get("value") or ""
                        console.print(f"      [green]✓[/green] {c['name']} {detail}")

    # Overall
    all_healthy = all(p.get("healthy", False) for p in result["providers"])
    console.print(f"\n[bold]Overall: {'[green]all providers healthy[/green]' if all_healthy else '[yellow]some issues found[/yellow]'}[/bold]")


@capability_app.command("guide")
def capability_guide(
    provider: str = typer.Argument(..., help="Provider id (e.g. pdf-lite, firecrawl, yt-dlp)"),
):
    """Return the canonical Provider execution guide (SKILL.md) for an Agent.

    Reads from the installed package resource — no local providers/
    directory needed.  The Agent calls this after selecting a Provider
    to get Provider-specific execution instructions (tool invocation,
    evidence construction, normalization).

    Only for Agent use; not part of the default user happy path.
    """
    from importlib.resources import files

    skill_path = files("knowledge_studio.providers").joinpath(provider, "SKILL.md")
    if not skill_path.is_file():
        console.print(f"[red]No guide found for provider: {provider}[/red]")
        known = []
        for entry in sorted(files("knowledge_studio.providers").iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                known.append(entry.name)
        if known:
            console.print(f"[dim]Available: {', '.join(known)}[/dim]")
        raise typer.Exit(1)
    print(skill_path.read_text(encoding="utf-8"))


# ── Schema ─────────────────────────────────────────────────────────

def _resolve_schema_name(name: str) -> tuple[str, Path] | None:
    """Resolve a short schema name to (canonical_name, path)."""
    from importlib.resources import files

    schemas_dir = files("knowledge_studio.schemas")
    # Build lookup: short-name → full filename
    # e.g. "evidence-manifest" → "evidence-manifest-v0.1.schema.json"
    candidates: list[tuple[str, Path]] = []
    for entry in sorted(schemas_dir.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".schema.json"):
            continue
        short = entry.name.replace(".schema.json", "")
        candidates.append((short, entry))

    # Exact match on short name
    for short, path in candidates:
        if short == name:
            return (short, path)
    # Prefix match
    matches = [(s, p) for s, p in candidates if s.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None  # ambiguous
    # Substring match (last resort)
    matches = [(s, p) for s, p in candidates if name in s]
    if len(matches) == 1:
        return matches[0]
    return None


@schema_app.command("list")
def schema_list(
    json_output: bool = typer.Option(False, "--json/--text", help="Output as JSON"),
):
    """List all available protocol schemas (dynamic scan)."""
    from importlib.resources import files

    schemas_dir = files("knowledge_studio.schemas")
    names: list[dict[str, str]] = []
    for entry in sorted(schemas_dir.iterdir()):
        if entry.is_file() and entry.name.endswith(".schema.json"):
            short = entry.name.replace(".schema.json", "")
            size = entry.stat().st_size
            names.append({"name": short, "file": entry.name, "size_bytes": size})

    if json_output:
        import json as _json
        print(_json.dumps({"schemas": names}, ensure_ascii=False, indent=2))
    else:
        table = Table(title="Protocol Schemas")
        table.add_column("Name", style="cyan")
        table.add_column("File")
        table.add_column("Size", justify="right")
        for entry in names:
            table.add_row(entry["name"], entry["file"], str(entry["size_bytes"]))
        console.print(table)


@schema_app.command("show")
def schema_show(
    name: str = typer.Argument(..., help="Schema short name (e.g. evidence-manifest)"),
):
    """Show the full JSON Schema for a protocol document type."""
    resolved = _resolve_schema_name(name)
    if resolved is None:
        console.print(f"[red]Schema not found: {name}[/red]")
        console.print("[dim]Run `oks schema list` to see available schemas.[/dim]")
        raise typer.Exit(1)
    _, path = resolved
    print(path.read_text(encoding="utf-8"))


@schema_app.command("example")
def schema_example(
    name: str = typer.Argument(..., help="Schema short name (e.g. evidence-manifest)"),
):
    """Show a minimal valid example for a protocol document type."""
    from knowledge_studio.schema_examples import get_example

    example = get_example(name)
    if example is not None:
        import json as _json
        print(_json.dumps(example, ensure_ascii=False, indent=2))
        return
    # Fallback: show the schema as reference
    resolved = _resolve_schema_name(name)
    if resolved is None:
        console.print(f"[red]No example or schema found for: {name}[/red]")
        console.print("[dim]Run `oks schema list` to see available schemas.[/dim]")
        raise typer.Exit(1)
    console.print(f"[yellow]No pre-built example for '{name}'.[/yellow]")
    console.print(f"[dim]Showing schema instead — use required fields to build your own.[/dim]")
    schema_show(name)


# ── Security ────────────────────────────────────────────────────────


@security_app.command("sanitize")
def security_sanitize(
    file: str = typer.Argument(..., help="File to sanitize in-place"),
    content_type: str = typer.Option(
        "application/json", "--content-type", "-t",
        help="MIME type hint: application/json, text/plain, text/html",
    ),
):
    """Strip credentials from a remote artifact in-place.

    Removes API keys, bearer tokens, session cookies, OAuth secrets,
    and internal IP addresses.  Safe to run on any file — binary files
    are returned unchanged.
    """
    from knowledge_studio.security.redaction import sanitize_remote_artifact

    fp = Path(file).expanduser().resolve()
    if not fp.is_file():
        console.print(f"[red]File not found: {fp}[/red]")
        raise typer.Exit(1)

    raw = fp.read_bytes()
    sanitized = sanitize_remote_artifact(raw, content_type=content_type)
    fp.write_bytes(sanitized)
    console.print(f"[green]Sanitized:[/green] {fp}")


# ── Skills Install ──────────────────────────────────────────────

def _install_skills(target_root: Path, force: bool) -> tuple[list[str], list[str]]:
    """Install OKS skills from the canonical ``skill_templates/`` source.

    Reads from ``importlib.resources("knowledge_studio.skill_templates")``
    — the single published skill source — and copies into
    ``<target_root>/.claude/skills/`` and ``<target_root>/.agents/skills/``.

    Returns ``(installed, skipped)`` lists of human-readable labels.
    """
    from importlib.resources import files

    templates_root = files("knowledge_studio.skill_templates")
    installed: list[str] = []
    skipped: list[str] = []

    for host in ("claude", "agents"):
        template_dir = templates_root / host / "skills"
        if not template_dir.is_dir():
            continue
        target_dir = target_root / f".{host}" / "skills"
        for child in sorted(template_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_name = child.name
            target_skill_dir = target_dir / skill_name
            if target_skill_dir.is_dir() and not force:
                skipped.append(f".{host}/skills/{skill_name}")
                continue
            target_skill_dir.mkdir(parents=True, exist_ok=True)
            for item in child.rglob("*"):
                if item.is_file():
                    if "__pycache__" in item.parts or item.suffix == ".pyc":
                        continue
                    rel = item.relative_to(child)
                    dest = target_skill_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(item.read_bytes())
            installed.append(f".{host}/skills/{skill_name}")

    return installed, skipped


@app.command()
def skills_install(
    force: bool = typer.Option(False, "--force", help="Overwrite user-modified skills"),
):
    """Install OKS Agent skills into the user workspace.

    Copies skill templates from the installed package to
    ``<OKS_ROOT>/.claude/skills/`` and ``<OKS_ROOT>/.agents/skills/``.
    Safe to run repeatedly (idempotent).  Use ``--force`` to overwrite
    local modifications.
    """
    kb_root = Path(get_kb_root())
    installed, skipped = _install_skills(kb_root, force)

    if installed:
        console.print("[green]Installed skills:[/green]")
        for s in installed:
            console.print(f"  + {s}")
    if skipped:
        console.print("[yellow]Skipped (use --force to overwrite):[/yellow]")
        for s in skipped:
            console.print(f"  ~ {s}")
    if not installed and not skipped:
        console.print("[dim]No skill templates found in package.[/dim]")


# ── Raw Commit ───────────────────────────────────────────────────

@app.command(name="raw-commit")
def raw_commit(
    manifest_dir: str = typer.Argument(..., help="Path to manifest directory containing source-envelope.json, evidence-manifest.json, and artifacts/"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Target Raw Bundle directory (default: auto-generated under raw/)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace existing bundle directory"),
    json_output: bool = typer.Option(True, "--json/--text", help="Output as JSON"),
):
    """Commit an Agent-submitted evidence bundle to OKS.

    The Agent submits a directory containing source-envelope.json,
    evidence-manifest.json, fragments/ (optional), and artifacts/ (all
    evidence files).  ``oks raw-commit`` validates structural integrity,
    artifact existence + hash matching, and evidence locator legality,
    then assembles a Raw Bundle v0.2.

    Returns structured JSON on success or a CommitError on failure.
    """
    from knowledge_studio.raw_commit import raw_commit as _commit, CommitError

    try:
        result = _commit(manifest_dir, output=output, overwrite=overwrite)
        if json_output:
            import json as _json
            print(_json.dumps(result, ensure_ascii=False, indent=2))
        else:
            console.print(f"[green]Committed:[/green] {result['bundle_path']}")
            console.print(f"  bundle_id: {result['bundle_id']}")
            console.print(f"  evidence: {result['evidence_count']} records")
            console.print(f"  artifacts: {result['artifact_count']}")
    except CommitError as exc:
        if json_output:
            import json as _json
            error_out: dict[str, Any] = {
                "status": "rejected",
                "error_code": exc.code,
                "message": exc.message,
            }
            if exc.details:
                error_out["details"] = exc.details
            print(_json.dumps(error_out, ensure_ascii=False, indent=2))
        else:
            console.print(f"[red]Rejected ({exc.code}):[/red] {exc.message}")
            # Show individual errors when batch-collected
            batch = (exc.details or {}).get("errors", [])
            for i, err in enumerate(batch, 1):
                detail_info = err.get("details", {})
                json_path = detail_info.get("json_path", "") if isinstance(detail_info, dict) else ""
                loc = f" [dim]{json_path}[/dim]" if json_path else ""
                console.print(
                    f"  {i}. [yellow]{err.get('code', '')}[/yellow]{loc}"
                )
        raise typer.Exit(1)


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

# Maintainer-only and dev-only assets. Kept in the repo for development, never
# installed into a user's knowledge base. Must stay in sync with setup.py.
_DEV_ONLY_ASSET_NAMES = (
    "review-upstream-pr",
    "upstream-pr-remediation",
    "triad-engineering-closure",
    "claude-code-vision-skill",
    "settings.local.json",
)


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
        # ── Skills live in skill_templates/, never in the asset tree ──
        # _install_skills() is the sole canonical skill source.  Stripping
        # here ensures that stale repo-root skill copies don't shadow the
        # template versions, even in dev-mode (repo-root) installs.
        skills_dir = dest / "skills"
        if skills_dir.is_dir():
            import stat as _stat
            def _rm_readonly(_fn, _p, _e):
                Path(_p).chmod(_stat.S_IWRITE)
                _fn(_p)
            shutil.rmtree(skills_dir, onexc=_rm_readonly)
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
            "  Reinstall the canonical main source with pipx, then retry:\n"
            "  pipx install --force \"git+https://github.com/1263-ux/claude-code-knowledge-studios.git@main#subdirectory=cli\"\n"
            "  or run python cli/scripts/bundle_assets.py in the repo before installing."
        )
    else:
        copied = _materialize_assets(root, base, is_packaged, overwrite=upgrade)
        if copied:
            console.print(f"[green]Materialized assets:[/green] {', '.join(copied)}")
        else:
            console.print("[dim]Assets already present (use --upgrade to refresh).[/dim]")

    # Always install skills from the canonical skill_templates/ source.
    # This ensures init and skills-install produce identical skill sets
    # regardless of whether the build used the repo root or the wheel.
    skill_installed, skill_skipped = _install_skills(root, force=upgrade)
    if skill_installed:
        console.print(f"[green]Installed skills:[/green] {', '.join(skill_installed)}")
    if skill_skipped:
        console.print("[dim]Skills already present (use --upgrade to refresh).[/dim]")

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

    # ── Dynamic capability check ──
    from knowledge_studio.capability_commands import (
        capability_doctor,
        print_capability_summary,
    )
    try:
        doctor_result = capability_doctor()
    except Exception:
        doctor_result = None
    print_capability_summary(console, doctor_result)


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
            f"  Fix: [bold]pipx install --force \"git+https://github.com/1263-ux/claude-code-knowledge-studios.git@main#subdirectory=cli\"[/bold],\n"
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
