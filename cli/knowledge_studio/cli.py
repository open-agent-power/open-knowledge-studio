"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from knowledge_studio import store
from knowledge_studio.hooks_cli import app as hook_app
from knowledge_studio.i18n import t
from knowledge_studio.metrics_html import _generate_metrics_html
from knowledge_studio.raw_commit import CommitError as _CommitError
from knowledge_studio.raw_commit import raw_commit as _raw_commit
from knowledge_studio.recall import (
    RECALL_RESPONSE_SCHEMA,
    describe_goal_selection,
    recall,
    recall_episodic,
    recall_knowledge,
)
from knowledge_studio.workbuddy import inspect_workbuddy_adapter
from knowledge_studio.skills_cli import app as skills_app
from knowledge_studio.handoff_cli import app as handoff_app
from knowledge_studio.feedback_cli import app as feedback_app
from knowledge_studio.tasks_cli import app as tasks_app
from knowledge_studio import instance_cli
from knowledge_studio import mail_cli
from knowledge_studio import trace_cli
from knowledge_studio import wiki_cli
from knowledge_studio import fs_cli
from knowledge_studio import drafts_cli
from knowledge_studio import config_cli
from knowledge_studio import sources_cli
from knowledge_studio import capability_cli
from knowledge_studio import ingest_cli
from knowledge_studio import eval_cli

# Instance scaffolding lives in instance_cli; these names stay importable from
# `knowledge_studio.cli` because tests and hooks_cli resolve them here.
from knowledge_studio.instance_cli import (
    _AGENT_TARGETS,
    _DEFAULT_CORE_SKILLS,
    _INSTANCE_DIRS,
    _instance_root,
    _materialize_assets,
)

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


workbuddy_app = typer.Typer(
    help="WorkBuddy local Agent workflow.", no_args_is_help=True,
)

schema_app = typer.Typer(help="Protocol document shapes an Agent must author.")
security_app = typer.Typer(help="Credential redaction for provider raw output.")


from .daily_cli import app as capture_app
app.add_typer(capture_app, name="capture")
app.add_typer(wiki_cli.wiki_app, name="wiki")
app.add_typer(skills_app, name="skills")
app.add_typer(drafts_cli.drafts_app, name="drafts")
app.add_typer(config_cli.config_app, name="config")
app.add_typer(hook_app, name="hook")
app.add_typer(mail_cli.app, name="mail")
app.add_typer(handoff_app, name="handoff")
app.add_typer(feedback_app, name="feedback")
app.add_typer(tasks_app, name="task")
app.add_typer(mail_cli.registry_app, name="registry")
app.add_typer(eval_cli.eval_app, name="eval")
app.add_typer(sources_cli.sources_app, name="sources")
app.add_typer(instance_cli.onboarding_app, name="onboarding")
app.add_typer(trace_cli.trace_app, name="trace")
app.add_typer(workbuddy_app, name="workbuddy")
app.add_typer(fs_cli.fs_app, name="fs")

app.add_typer(capability_cli.capability_app, name="capability")
app.add_typer(schema_app, name="schema")
app.add_typer(security_app, name="security")
app.add_typer(ingest_cli.ingest_app, name="ingest")
app.add_typer(instance_cli.team_app, name="team")

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
    from knowledge_studio.recall import load_recall_params
    load_recall_params()  # 触发 env 迁移警告（env 已废弃）
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


@app.command('layout-migrate')
def layout_migrate():
    """Unify legacy goal/discuss/skill buckets with a resumable local audit."""
    from .layout import migrate
    try:
        _emit_json(migrate(_instance_root(None)))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))


# ── Root aliases ─────────────────────────────────────────────────

# `use` is also a root command (see wiki_cli). Re-register it at its original
# position so the root `--help` command list keeps the same order.
app.command("use")(wiki_cli.wiki_use)


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
    output_format = output_format.lower().strip()
    if output_format not in {"text", "json"}:
        console.print("[red]--format must be text or json[/red]")
        raise typer.Exit(2)
    root = kb_root.expanduser().resolve() if kb_root is not None else store.repo_root()
    result = inspect_workbuddy_adapter(root)
    if output_format == "json":
        _emit_json(result)
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


# ── Instance scaffolding ─────────────────────────────────────────

# Map flat CLI keys (oks config set <key>) to (yaml_section, yaml_field)
# in settings/recall.yaml. Anything here is routed to yaml, not config.json,
# so recall (which reads yaml) honors the value. v0.5.12 single-source rule.


def _asset_source() -> Path | None:
    """Locate the instance-template tree.

    A module in the source tree uses its adjacent assets, including Git archives.
    Installed packages use their own `_assets/` even inside another checkout.
    """
    package = Path(__file__).resolve().parent
    source = package.parent.parent
    if package == source / "cli" / "knowledge_studio" and (source / "assets").is_dir():
        return source / "assets"
    packaged = package / "_assets"
    if packaged.is_dir() and any(packaged.iterdir()):
        return packaged
    return None


instance_cli.register(app)


if __name__ == "__main__":
    app()
