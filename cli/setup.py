"""Assemble instance assets before setuptools discovers package data."""
from __future__ import annotations

from pathlib import Path
import sys

from setuptools import setup
from setuptools.command.build_py import build_py

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _build_assets import bundle_assets, purge_stale_build_assets

CLI_DIR = Path(__file__).resolve().parent


class build_py_with_assets(build_py):
    def run(self):
        purge_stale_build_assets(CLI_DIR)
        super().run()


# Metadata discovery and each build command share this single assembly. An
# sdist already carries the assembled tree and needs no repository checkout.
bundle_assets(CLI_DIR)
setup(cmdclass={"build_py": build_py_with_assets})
