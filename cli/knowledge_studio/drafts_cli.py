"""`oks drafts` — Candidate Markdown review and promotion.

Split out of `cli.py` as a verbatim move (B4-5a). Bodies are byte-identical to the
pre-split version, which `block_equivalence.py` verifies via AST.
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from knowledge_studio import store

console = Console()

drafts_app = typer.Typer(help="Draft proposal management.")


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
