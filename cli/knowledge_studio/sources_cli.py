"""`oks sources` — linked read-only Git knowledge repositories.

Split out of `cli.py` as a verbatim move (B4-5c). These four commands were
interleaved with `layout-migrate` and the eval group in the original file, so the
split needed three separate splices; nothing else used them.
"""
from __future__ import annotations

from knowledge_studio.output import emit_json as _emit_json

from pathlib import Path

import typer

from knowledge_studio.instance_cli import _instance_root

sources_app = typer.Typer(help="Link independent read-only Git knowledge repositories.")


@sources_app.command('link')
def sources_link(path: Path, name: str = typer.Option(..., '--name'),
                 repository: str = typer.Option(..., '--repository'), revision: str = typer.Option('HEAD', '--revision')):
    from .linked_sources import link
    try:
        _emit_json(link(_instance_root(None), name, path, repository, revision))
    except (OSError, ValueError, KeyError) as exc:
        raise typer.BadParameter(str(exc))


@sources_app.command('inspect')
def sources_inspect(path: Path, revision: str = typer.Option('HEAD', '--revision')):
    """Read a library's committed README requirements before registering it."""
    from .linked_sources import inspect_library
    try:
        _emit_json(inspect_library(path, revision))
    except (OSError, ValueError, UnicodeError) as exc:
        raise typer.BadParameter(str(exc))


@sources_app.command('list')
def sources_list():
    from .linked_sources import catalog
    _emit_json(catalog(_instance_root(None)))


@sources_app.command('unlink')
def sources_unlink(name: str):
    from .linked_sources import unlink
    _emit_json(unlink(_instance_root(None), name))
