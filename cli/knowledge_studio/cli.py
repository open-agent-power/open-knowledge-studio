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
app.add_typer(wiki_app, name="wiki")
app.add_typer(drafts_app, name="drafts")
app.add_typer(config_app, name="config")
app.add_typer(hook_app, name="hook")


# ── Search / Recall ──────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    scope: Optional[str] = typer.Option(None, "--scope", "--domain", "-d", help="Soft scope: narrow to one area (opt-in, not a hard partition)"),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
):
    """Search wiki pages using the 6+1-factor recall engine (read-only)."""
    results = recall_knowledge(query=query, limit=limit, scope=scope)

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
    scope: Optional[str] = typer.Option(None, "--scope", "-s", help="Soft scope: narrow knowledge path to one area (opt-in, not a hard partition)"),
):
    """Two-path recall: episodic (raw/) + knowledge (wiki/)."""
    result = recall(query=query, topic_id=topic_id, limit=limit, scope=scope)

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

# NOTE: wiki/, drafts/, profiles/ are intentionally TRACKED — they ARE your
# memory. Unlike the open-knowledge-studio code repo (which ignores wiki/ &
# drafts/ so it ships clean), an instance commits its knowledge to git.
"""


_ASSET_MAP = [
    ("claude", ".claude"),
    ("templates", "templates"),
    ("_meta", "_meta"),
    ("settings", "settings"),
]


def _asset_source() -> tuple[Path | None, bool]:
    """Locate the shareable asset layer. Returns (base, is_packaged).

    Priority: bundled `_assets/` inside the installed package (release build),
    else the dev repo root (walk up for a dir containing .claude + templates).
    """
    packaged = Path(__file__).resolve().parent / "_assets"
    if packaged.is_dir() and any(packaged.iterdir()):
        return packaged, True
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude").is_dir() and (parent / "templates").is_dir():
            return parent, False
    return None, False


def _materialize_assets(root: Path, base: Path, is_packaged: bool, overwrite: bool) -> list[str]:
    import shutil

    done: list[str] = []
    for pkg_name, dest_name in _ASSET_MAP:
        src = base / (pkg_name if is_packaged else dest_name)
        if not src.is_dir():
            continue
        dest = root / dest_name
        if dest.exists():
            if not overwrite:
                continue
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        done.append(dest_name)
    return done


@app.command()
def init(
    path: str = typer.Argument(".", help="Target directory for the new knowledge instance"),
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
):
    """Scaffold a new knowledge INSTANCE folder (e.g. your personal artboy-knowledge-studio).

    Creates the bucket structure and a .gitignore that TRACKS your memory
    (wiki/, drafts/, profiles/) while ignoring only per-machine state (.oks/).
    By default points ~/.oks/config.json at the new folder so `oks` targets it
    from anywhere.
    """
    root = Path(path).expanduser().resolve()
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
        f"\n[bold]Instance ready.[/bold] Next:\n"
        f"  cd {root}\n"
        f"  oks status\n"
        f"  oks wiki create --title \"...\" --type concept --area computing"
    )


# ── Optional editor hooks (opt-in auto-recall) ───────────────────

_RECALL_HOOK_CMD = ".claude/hooks/user-prompt-recall.sh"
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
    """Copy the recall hook scripts into <root>/.claude/hooks/ if missing."""
    import shutil
    import stat

    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    base, is_packaged = _asset_source()
    src_dir = None
    if base is not None:
        src_dir = base / ("claude/hooks" if is_packaged else ".claude/hooks")

    created: list[str] = []
    for name in _RECALL_HOOK_SCRIPTS:
        dest = hooks_dir / name
        if dest.exists():
            continue
        if src_dir is None or not (src_dir / name).is_file():
            raise FileNotFoundError(
                f"bundled hook script not found: {name} (asset source: {src_dir})"
            )
        shutil.copy2(src_dir / name, dest)
        if name.endswith(".sh"):
            import sys
            text = dest.read_text(encoding="utf-8").replace(
                '"${OKS_PYTHON:-python3}"', f'"${{OKS_PYTHON:-{sys.executable}}}"'
            )
            dest.write_text(text, encoding="utf-8")
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        created.append(name)
    return created


def _wire_userpromptsubmit(settings_path: Path, command: str) -> str:
    """Idempotently add a UserPromptSubmit command hook. Returns 'wired'|'exists'."""
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    ups = hooks.setdefault("UserPromptSubmit", [])
    for group in ups:
        for h in group.get("hooks", []):
            if h.get("command") == command:
                return "exists"
    ups.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return "wired"


def _hook_is_wired(settings_path: Path, command: str) -> bool:
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return False
    for group in data.get("hooks", {}).get("UserPromptSubmit", []):
        for h in group.get("hooks", []):
            if h.get("command") == command:
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

    editors = ("claude", "qoder") if editor == "both" else (editor,)
    for name in editors:
        settings_path = root / _HOOK_EDITORS[name]
        result = _wire_userpromptsubmit(settings_path, _RECALL_HOOK_CMD)
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
                 else "[red]NOT importable — hook will silently no-op; re-run oks hook install[/red]")
        console.print(f"  engine: {state} (python: {py})")
    for name, rel in _HOOK_EDITORS.items():
        settings_path = root / rel
        wired = _hook_is_wired(settings_path, _RECALL_HOOK_CMD)
        state = "[green]wired[/green]" if wired else "[dim]not wired[/dim]"
        console.print(f"  {name}: {state}")


if __name__ == "__main__":
    app()
