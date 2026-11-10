"""Canonical schemas survive asset assembly, initialization and upgrades."""
from importlib.resources import files
from pathlib import Path

import pytest

from _build_assets import bundle_assets, purge_stale_build_assets
from knowledge_studio.schemas import INSTANCE_SCHEMA_NAMES


def test_asset_assembly_replaces_stale_files_and_uses_canonical_schemas(tmp_path):
    cli_dir = tmp_path / "cli"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "current.txt").write_text("current", encoding="utf-8")
    cache = assets / "__pycache__"
    cache.mkdir()
    (cache / "helper.pyc").write_bytes(b"derived")
    canonical = cli_dir / "knowledge_studio" / "schemas"
    canonical.mkdir(parents=True)
    for name in INSTANCE_SCHEMA_NAMES:
        (canonical / name).write_bytes(files("knowledge_studio.schemas").joinpath(name).read_bytes())
    destination = cli_dir / "knowledge_studio" / "_assets"
    destination.mkdir()
    (destination / "removed.txt").write_text("stale", encoding="utf-8")

    assert bundle_assets(cli_dir) == destination

    assert (destination / "current.txt").read_text(encoding="utf-8") == "current"
    assert not (destination / "removed.txt").exists()
    assert not (destination / "__pycache__").exists()
    for name in INSTANCE_SCHEMA_NAMES:
        assert (destination / "_meta" / "schemas" / name).read_bytes() == (canonical / name).read_bytes()


def test_sdist_assembly_keeps_existing_assets_without_checkout(tmp_path):
    cli_dir = tmp_path / "cli"
    destination = cli_dir / "knowledge_studio" / "_assets"
    destination.mkdir(parents=True)
    (destination / "retained.txt").write_text("sdist asset", encoding="utf-8")
    stale = cli_dir / "build" / "lib" / "knowledge_studio" / "_assets"
    stale.mkdir(parents=True)
    (stale / "removed.txt").write_text("stale", encoding="utf-8")

    assert bundle_assets(cli_dir) == destination
    purge_stale_build_assets(cli_dir)

    assert (destination / "retained.txt").read_text(encoding="utf-8") == "sdist asset"
    assert not stale.exists()


@pytest.mark.parametrize("packaged", [False, True])
def test_instance_schemas_use_canonical_source_and_preserve_upgrade_rules(tmp_path, packaged):
    from knowledge_studio.cli import _materialize_assets

    base = tmp_path / "assets"
    (base / "_meta").mkdir(parents=True)
    if packaged:
        generated = base / "_meta" / "schemas"
        generated.mkdir()
        for name in INSTANCE_SCHEMA_NAMES:
            (generated / name).write_text("stale generated copy", encoding="utf-8")
    instance = tmp_path / "instance"
    expected = files("knowledge_studio.schemas")

    _materialize_assets(instance, base, overwrite=False)

    for name in INSTANCE_SCHEMA_NAMES:
        assert (instance / "_meta" / "schemas" / name).read_bytes() == expected.joinpath(name).read_bytes()
    modified = instance / "_meta" / "schemas" / INSTANCE_SCHEMA_NAMES[0]
    modified.write_text("custom instance schema", encoding="utf-8")
    _materialize_assets(instance, base, overwrite=False)
    assert modified.read_text(encoding="utf-8") == "custom instance schema"
    _materialize_assets(instance, base, overwrite=True)
    assert modified.read_bytes() == expected.joinpath(modified.name).read_bytes()
