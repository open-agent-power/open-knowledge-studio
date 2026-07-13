"""Knowledge health check — validates wiki integrity.

Extracted from autpilot-web/backend/app/services/knowledge_health.py.
Removed KnowledgeStore dependency. Uses store.repo_root().
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from knowledge_studio.store import repo_root, wiki_dir, drafts_dir, raw_dir

_logger = logging.getLogger(__name__)


def run_health_check() -> dict:
    """Run all health checks. Returns {errors, warnings, info, summary}."""
    root = repo_root()

    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    wd = wiki_dir()
    total_pages = 0
    orphan_pages = 0
    dropped_pages = 0
    if wd.is_dir():
        for md in sorted(wd.rglob("*.md")):
            if md.name == "INDEX.md":
                continue
            total_pages += 1
            result = _check_wiki_page(md, errors, warnings)
            if result == "orphan":
                orphan_pages += 1
            elif result == "dropped":
                dropped_pages += 1

    dd = drafts_dir()
    total_drafts = 0
    if dd.is_dir():
        for md in sorted(dd.glob("*.md")):
            total_drafts += 1
            try:
                text = md.read_text(encoding="utf-8")
                if not text.startswith("---"):
                    warnings.append(f"Draft missing frontmatter: {md.name}")
            except Exception as e:
                errors.append(f"Draft unreadable: {md.name} — {e}")

    rd = raw_dir()
    if not rd.exists():
        warnings.append("raw/ directory not found")
    info.append(f"Wiki pages: {total_pages} (dropped: {dropped_pages}, orphan: {orphan_pages})")
    info.append(f"Drafts: {total_drafts}")

    active_pages = total_pages - dropped_pages
    coverage = (active_pages / total_pages * 100) if total_pages > 0 else 0
    info.append(f"Active coverage: {coverage:.0f}%")

    return {
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "info": len(info),
            "total_wiki_pages": total_pages,
            "dropped": dropped_pages,
            "orphan": orphan_pages,
            "total_drafts": total_drafts,
            "coverage_pct": round(coverage, 1),
        },
    }


def _check_wiki_page(md: Path, errors: list, warnings: list) -> str:
    try:
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            warnings.append(f"Wiki page missing frontmatter: {md.name}")
            return "orphan"
        parts = text.split("---", 2)
        if len(parts) < 3:
            warnings.append(f"Wiki page malformed frontmatter: {md.name}")
            return "orphan"
        meta = yaml.safe_load(parts[1].strip()) or {}
        for field in ("title", "type", "area"):
            if not meta.get(field):
                warnings.append(f"Wiki page {md.name} missing '{field}'")

        status = meta.get("status", "active")
        if status == "dropped":
            return "dropped"

        tags = meta.get("tags", "")
        traces = meta.get("traces")
        if not tags and not traces:
            return "orphan"

        return "ok"
    except Exception as e:
        errors.append(f"Wiki page unreadable: {md.name} — {e}")
        return "orphan"
