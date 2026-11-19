"""`oks fs` — read-only virtual context filesystem.

Split out of `cli.py` as a verbatim move (B4-4). The four `_vfs_*` helpers moved
with the commands because nothing else used them. Output helpers come from
`knowledge_studio.output`, shared with `recall` and the other command modules;
the moved `_run_vfs` body stays byte-identical.
"""
from __future__ import annotations

from knowledge_studio.output import (
    emit_json as _emit_json,
    validate_output_format as _validate_output_format,
)

from typing import Any, Callable

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from knowledge_studio.instance_cli import _instance_root
from knowledge_studio.vfs import FS_RESPONSE_SCHEMA, VfsError, VfsService

console = Console()

fs_app = typer.Typer(
    help="Read-only virtual context filesystem.", no_args_is_help=True
)


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
            _emit_json(payload)
        else:
            console.print(
                f"[red]{escape(exc.code)}:[/red] {escape(exc.public_message)}"
            )
        raise typer.Exit(2)
    except OSError:
        exc = VfsError("IO_ERROR", "Filesystem operation failed")
        payload = _vfs_error(operation, uri, exc)
        if output_format == "json":
            _emit_json(payload)
        else:
            console.print(f"[red]{exc.code}:[/red] {exc.public_message}")
        raise typer.Exit(1)

    canonical_uri = str(result.get("uri", uri))
    payload = _vfs_success(operation, canonical_uri, result)
    if output_format == "json":
        _emit_json(payload)
    else:
        _render_vfs_text(operation, canonical_uri, result)


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


@fs_app.command('inspect')
def fs_inspect(uri: str, operation: str = typer.Option('ls', '--operation'),
               query: str = typer.Option('', '--query'), offset: int = typer.Option(0), limit: int = typer.Option(20000)):
    """Execute a measured VFS call and retain real stage timings."""
    from .vfs_observation import execute
    try:
        _emit_json(execute(_instance_root(None), operation, uri, query=query, offset=offset, limit=limit))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc))
