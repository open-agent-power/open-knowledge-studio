"""Domain → Wiki migration — one-time conversion.

Extracted from autpilot-web/backend/app/services/migrate_domain_to_wiki.py.
Removed settings/knowledge_sync dependencies. Uses store._atomic_write.

Migration mapping:
  domain/{area}/foundations/*.md  -> wiki/{area}/concepts/    (type: concept)
  domain/{area}/conventions/*.md  -> wiki/{area}/strategies/   (type: strategy)
  domain/{area}/context/*.md      -> wiki/{area}/concepts/      (type: concept)
  domain/{area}/strategies/**/*.md -> wiki/{area}/strategies/  (type: strategy)
  domain/_shared/**/*.md          -> wiki/_shared/concepts/    (type: concept)

Idempotent: if the target wiki/ file already exists, it is skipped.
Original domain/ files are NOT deleted.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from knowledge_studio.store import _atomic_write, repo_root

_logger = logging.getLogger(__name__)

_SUBDIR_MAPPINGS: list[tuple[str, str, str]] = [
    ("foundations", "concepts", "concept"),
    ("conventions", "strategies", "strategy"),
    ("context", "concepts", "concept"),
    ("strategies", "strategies", "strategy"),
]


def _domain_dir() -> Path:
    return repo_root() / "domain"


def _wiki_dir() -> Path:
    return repo_root() / "wiki"


def _resolve_migration(
    src_path: Path, domain_root: Path,
) -> tuple[Path, str] | None:
    """Resolve the target wiki path and wiki type for a domain source file.

    Returns (target_path, wiki_type) or None if no mapping rule applies.
    """
    try:
        rel = src_path.relative_to(domain_root)
    except ValueError:
        return None

    parts = rel.parts
    if not parts:
        return None

    if parts[0] == "_shared":
        target = _wiki_dir() / "_shared" / "concepts" / src_path.name
        return target, "concept"

    if len(parts) < 2:
        return None

    area = parts[0]
    src_subdir = parts[1]

    for subdir, target_subdir, wiki_type in _SUBDIR_MAPPINGS:
        if src_subdir == subdir:
            target = _wiki_dir() / area / target_subdir / src_path.name
            return target, wiki_type

    return None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a Markdown file with YAML frontmatter.

    Returns (meta_dict, body_string). If no valid frontmatter is found,
    returns ({}, full_text).
    """
    if not text.startswith("---"):
        return {}, text

    split = text.split("---", 2)
    if len(split) < 3:
        return {}, text

    try:
        meta = yaml.safe_load(split[1].strip()) or {}
    except yaml.YAMLError:
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, split[2].lstrip("\n")


def _build_frontmatter(meta: dict, wiki_type: str) -> str:
    """Build migrated frontmatter preserving existing fields and setting required ones."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    fm: dict = {}

    for key in ("title", "tags", "area", "source", "last_verified"):
        if key in meta:
            fm[key] = meta[key]

    fm["type"] = wiki_type
    fm["status"] = "active"
    fm["importance"] = 0.7
    fm["confidence"] = meta.get("confidence", 0.8)
    fm["created"] = meta.get("created", today)
    fm["pinned"] = False
    fm["archived"] = False
    fm["access_count"] = 0

    return yaml.dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def run_migration() -> dict:
    """Run the domain -> wiki migration.

    Walks ``domain/`` recursively, converts each matching ``.md`` file to
    the new ``wiki/`` layout with updated frontmatter, and writes it
    atomically.

    Returns:
        ``{"migrated": int, "skipped": int, "errors": list[str]}``

    The migration is **idempotent**: if a target wiki/ file already exists,
    it is skipped.  Original ``domain/`` files are never deleted.
    """
    domain_root = _domain_dir()
    if not domain_root.exists():
        return {
            "migrated": 0,
            "skipped": 0,
            "errors": ["domain/ directory not found"],
        }

    migrated = 0
    skipped = 0
    errors: list[str] = []

    for src_path in sorted(domain_root.rglob("*.md")):
        resolved = _resolve_migration(src_path, domain_root)
        if resolved is None:
            continue

        target_path, wiki_type = resolved

        if target_path.exists():
            skipped += 1
            continue

        try:
            text = src_path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            frontmatter_str = _build_frontmatter(meta, wiki_type)
            content = f"---\n{frontmatter_str}---\n\n{body}"

            _atomic_write(target_path, content)
            migrated += 1
            _logger.info("Migrated %s -> %s", src_path, target_path)
        except Exception as exc:
            errors.append(f"{src_path}: {exc}")
            _logger.warning("Migration error for %s: %s", src_path, exc)

    _logger.info(
        "domain->wiki migration complete: %d migrated, %d skipped, %d errors",
        migrated, skipped, len(errors),
    )
    return {"migrated": migrated, "skipped": skipped, "errors": errors}
