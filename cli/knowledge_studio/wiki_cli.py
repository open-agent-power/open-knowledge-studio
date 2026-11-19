"""`oks wiki` — page CRUD, use-signal and portable export.

Split out of `cli.py` as a verbatim move (B4-3). Command bodies are byte-identical
to the pre-split version; `block_equivalence.py` verifies that via AST.

One registration detail: `use` is both a root command and a `wiki` subcommand. The
double decorator cannot live here, because `cli.py` imports this module — decorating
with the root `app` would be a circular import at load time. So this module keeps
only `@wiki_app.command("use")`, and `cli.py` re-registers the same function on the
root app with `app.command("use")(wiki_cli.wiki_use)`. Registration order is kept
where it was so the root `--help` command list does not reorder.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from knowledge_studio import store
from knowledge_studio.instance_cli import _instance_root

console = Console()

wiki_app = typer.Typer(help="Wiki page management.")


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
    root = _instance_root(None)
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
