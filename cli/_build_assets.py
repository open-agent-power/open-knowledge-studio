"""Shared asset assembly for setuptools and the manual bundle command."""
from pathlib import Path
import shutil

from knowledge_studio.schemas import BUNDLED_SCHEMA_NAMES


def bundle_assets(cli_dir: Path) -> Path:
    """Replace checkout assets and add bundled schemas from their package source."""
    source = cli_dir.parent / "assets"
    destination = cli_dir / "knowledge_studio" / "_assets"
    if not source.is_dir():
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    schemas = destination / "_meta" / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    for name in BUNDLED_SCHEMA_NAMES:
        shutil.copy2(cli_dir / "knowledge_studio" / "schemas" / name, schemas / name)
    return destination


def purge_stale_build_assets(cli_dir: Path) -> None:
    """Remove incremental build copies so deleted assets cannot survive in a wheel."""
    stale = cli_dir / "build" / "lib" / "knowledge_studio" / "_assets"
    if stale.exists():
        shutil.rmtree(stale)
