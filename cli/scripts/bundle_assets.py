#!/usr/bin/env python3
"""Assemble the same instance assets used by setuptools."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _build_assets import bundle_assets


def main() -> None:
    cli_dir = Path(__file__).resolve().parents[1]
    if not (cli_dir.parent / "assets").is_dir():
        raise SystemExit("assets/ not found — run this from a source checkout")
    destination = bundle_assets(cli_dir)
    copied = sorted(entry.name for entry in destination.iterdir())
    print(f"Bundled assets into {destination}: {', '.join(copied)}")


if __name__ == "__main__":
    main()
