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

WIKI_TYPES = {"concept", "strategy", "anti-pattern"}
# ``published`` was used by older KB instances. Keep accepting it so lint is
# compatible with existing files; new writes continue to use ``active``.
WIKI_STATUSES = {"provisional", "active", "stale", "dropped", "superseded", "published"}
RELATIONSHIPS = {"supersedes", "enriches", "confirms", "challenges"}


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
    # v0.6.0: backlink audit — 收集所有 page 的 relates_to，检查双向链接
    # A.relates_to=B 时 B 应有反向引用（relates_to=A 或 body 含 [[A]]/[A](.) 链接）
    relates_map: dict[str, list[tuple[str, str]]] = {}  # slug -> [(target, relationship)]
    slug_set: set[str] = set()
    if wd.is_dir():
        for md in sorted(wd.rglob("*.md")):
            if md.name.lower() in {"index.md", "readme.md"}:
                continue
            total_pages += 1
            result = _check_wiki_page(md, errors, warnings)
            if result == "orphan":
                orphan_pages += 1
            elif result == "dropped":
                dropped_pages += 1
            # 收集 relates_to 用于 backlink audit
            try:
                text = md.read_text(encoding="utf-8")
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1].strip()) or {}
                        slug = meta.get("slug") or md.stem
                        slug_set.add(slug)
                        rt = meta.get("relates_to")
                        if rt:
                            rel = meta.get("relationship", "see-also")
                            for t in ([rt] if isinstance(rt, str) else rt):
                                relates_map.setdefault(slug, []).append((t.strip(), rel))
            except Exception:
                pass

    # backlink audit: A→B 时检查 B 是否反向引用 A
    for src, targets in relates_map.items():
        for target, rel in targets:
            if target not in slug_set:
                warnings.append(f"Backlink: {src} relates_to '{target}' but no such page exists")
                continue
            reverse = relates_map.get(target, [])
            reverse_targets = {t for t, _ in reverse}
            if src not in reverse_targets:
                warnings.append(
                    f"Backlink: {src} →{rel}→ {target} but {target} does not link back to {src}"
                )

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

        if meta.get("type") and meta["type"] not in WIKI_TYPES:
            warnings.append(f"Wiki page {md.name} has invalid 'type': {meta['type']}")
        if meta.get("status", "active") not in WIKI_STATUSES:
            warnings.append(f"Wiki page {md.name} has invalid 'status': {meta.get('status')}")
        for field in ("importance", "confidence"):
            if field in meta:
                value = meta[field]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                    warnings.append(f"Wiki page {md.name} has invalid '{field}': expected 0..1")
        for field in ("pinned", "archived"):
            if field in meta and not isinstance(meta[field], bool):
                warnings.append(f"Wiki page {md.name} has invalid '{field}': expected boolean")
        if "traces" in meta and not isinstance(meta["traces"], list):
            warnings.append(f"Wiki page {md.name} has invalid 'traces': expected list")
        relationship = meta.get("relationship")
        relates_to = meta.get("relates_to")
        if bool(relationship) != bool(relates_to):
            warnings.append(f"Wiki page {md.name} must pair 'relationship' with 'relates_to'")
        if relationship and relationship not in RELATIONSHIPS:
            warnings.append(f"Wiki page {md.name} has invalid 'relationship': {relationship}")
        if meta.get("status") == "superseded" and not meta.get("superseded_by"):
            warnings.append(f"Wiki page {md.name} is superseded but missing 'superseded_by'")

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
