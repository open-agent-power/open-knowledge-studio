"""oks — Open Knowledge Studio CLI.

Typer-based CLI for knowledge base search, wiki CRUD, drafts, and maintenance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

from knowledge_studio import store
from knowledge_studio.recall import recall, recall_episodic, recall_knowledge

app = typer.Typer(
    name="oks",
    help="Open Knowledge Studio — file-based knowledge engineering CLI.",
    no_args_is_help=True,
)
console = Console()

wiki_app = typer.Typer(help="Wiki page management.")
drafts_app = typer.Typer(help="Draft proposal management.")
handlers_app = typer.Typer(help="Handler management — multi-modal intake plugins.")
config_app = typer.Typer(help="Global configuration (~/.oks/config.json).")
app.add_typer(wiki_app, name="wiki")
app.add_typer(drafts_app, name="drafts")
app.add_typer(handlers_app, name="handlers")
app.add_typer(config_app, name="config")


# ── Search / Recall ──────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
):
    """Search wiki pages using the 6-factor recall engine."""
    results = recall_knowledge(query=query, limit=limit)

    if domain:
        results = [r for r in results if r.get("area") == domain]
    if type_filter:
        results = [r for r in results if r.get("type") == type_filter]

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

    for r in results:
        table.add_row(
            r["slug"],
            r["title"],
            r.get("type", ""),
            r.get("area", ""),
            f"{r.get('score', 0):.2f}",
            f"{r.get('relevance', 0):.2f}",
        )

    console.print(table)
    console.print(f"\n[dim]{len(results)} result(s) from wiki/[/dim]")


@app.command(name="recall")
def recall_cmd(
    query: str = typer.Argument(help="Search query"),
    topic_id: Optional[int] = typer.Option(None, "--topic-id", help="Filter by topic ID"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results per path"),
):
    """Two-path recall: episodic (raw/) + knowledge (wiki/)."""
    result = recall(query=query, topic_id=topic_id, limit=limit)

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
            console.print(Panel(
                item.get("body_preview", "")[:200],
                title=f"[{item.get('type', '')}] {item.get('title', '')} ({item.get('slug', '')})",
                subtitle=f"score={item.get('score', 0):.2f} relevance={item.get('relevance', 0):.2f}",
                border_style="green",
                expand=False,
            ))

    if not result["episodic"] and not result["knowledge"]:
        console.print("[dim]No results from either path.[/dim]")


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

    type_map = {"concept": "concepts", "strategy": "strategies", "anti-pattern": "anti-patterns"}
    wiki_type = type_map.get(page_type, "concepts")

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
        table.add_row(
            d["slug"],
            d.get("title", d["slug"]),
            d.get("draft_type", ""),
            d.get("draft_area", ""),
            d.get("drafted_at", ""),
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


@app.command()
def sync(
    pull: bool = typer.Option(False, "--pull", help="Pull from remote"),
):
    """Git sync the knowledge repo."""
    from knowledge_studio.sync import sync_repo
    ok = sync_repo(pull=pull)
    if ok:
        console.print("[green]Sync complete.[/green]")
    else:
        console.print("[red]Sync failed.[/red]")
        raise typer.Exit(1)


# ── Ingest — Universal Intake ─────────────────────────────────────

@app.command()
def ingest(
    input_path: str = typer.Argument(help="URL, file path, or directory to ingest"),
    handler: str = typer.Option(None, "--handler", "-H", help="Force specific handler (web/pdf/video/audio/image/repo)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect only, don't write to raw/"),
):
    """Universal multi-modal intake — auto-detects modality and processes input."""
    from knowledge_studio.ingest import ingest as run_ingest

    result = run_ingest(input_path, handler_name=handler, dry_run=dry_run)

    if result.get("error"):
        console.print(f"[red]Error:[/red] {result['error']}")
        if result.get("hint"):
            console.print(f"[dim]Hint: {result['hint']}[/dim]")
        raise typer.Exit(1)

    if dry_run:
        console.print(f"[cyan]Dry run:[/cyan] modality={result['modality']} handler={result['handler']}")
        return

    console.print(f"[green]Ingested:[/green] {result['raw_path']}")
    console.print(f"  [dim]Modality: {result['modality']}  Handler: {result['handler']}[/dim]")
    console.print(f"  [dim]Title: {result['title']}[/dim]")


# ── Handlers ────────────────────────────────────────────────────

@handlers_app.command("list")
def handlers_list():
    """List registered modality handlers."""
    from knowledge_studio.handlers.registry import HandlerRegistry

    registry = HandlerRegistry()
    handlers = registry.list_handlers()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name", style="dim", max_width=15)
    table.add_column("Modalities", max_width=40)
    table.add_column("Description", max_width=40)
    table.add_column("Enabled", justify="center", max_width=8)
    table.add_column("Available", justify="center", max_width=10)

    for h in handlers:
        table.add_row(
            h["name"],
            ", ".join(h["modalities"]),
            h["description"],
            "[green]✓[/green]" if h["enabled"] else "[red]✗[/red]",
            "[green]✓[/green]" if h["available"] else "[red]✗[/red]",
        )

    console.print(table)


@handlers_app.command("enable")
def handlers_enable(
    name: str = typer.Argument(help="Handler name (web/pdf/video/audio/image/repo)"),
):
    """Enable a handler."""
    from knowledge_studio.handlers.registry import HandlerRegistry

    registry = HandlerRegistry()
    if registry.enable(name):
        console.print(f"[green]Enabled:[/green] {name}")
    else:
        console.print(f"[red]Not found:[/red] {name}")
        raise typer.Exit(1)


@handlers_app.command("disable")
def handlers_disable(
    name: str = typer.Argument(help="Handler name (web/pdf/video/audio/image/repo)"),
):
    """Disable a handler."""
    from knowledge_studio.handlers.registry import HandlerRegistry

    registry = HandlerRegistry()
    if registry.disable(name):
        console.print(f"[yellow]Disabled:[/yellow] {name}")
    else:
        console.print(f"[red]Not found:[/red] {name}")
        raise typer.Exit(1)


# ── Config ───────────────────────────────────────────────────────

@config_app.command("init")
def config_init(
    kb_path: str = typer.Option(None, "--kb-path", help="Knowledge base path"),
):
    """Initialize global config at ~/.oks/config.json."""
    from knowledge_studio.config import init_config

    path = init_config(kb_path)
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
        f"[bold]API Keys[/bold]\n"
        f"  openai: {'✓ set' if config.get('api_keys', {}).get('openai') else '✗ empty'}\n"
        f"  anthropic: {'✓ set' if config.get('api_keys', {}).get('anthropic') else '✗ empty'}\n\n"
        f"[bold]Handler Config[/bold]",
        border_style="cyan",
    ))

    handlers = config.get("handlers", {})
    if handlers:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Handler", max_width=15)
        table.add_column("Settings", max_width=50)
        for name, settings in handlers.items():
            table.add_row(name, ", ".join(f"{k}={v}" for k, v in settings.items()))
        console.print(table)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key (e.g., api_keys.openai, handlers.video.frame_interval)"),
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

    if value.lower() in ("true", "false"):
        target[keys[-1]] = value.lower() == "true"
    elif value.isdigit():
        target[keys[-1]] = int(value)
    else:
        target[keys[-1]] = value

    save_config(config)
    console.print(f"[green]Set:[/green] {key} = {value}")


if __name__ == "__main__":
    app()
