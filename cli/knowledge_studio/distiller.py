"""Distiller — knowledge evolution and digest pipeline.

Extracted from autpilot-web/backend/app/services/knowledge_distiller.py.
Removed asyncio, KnowledgeStore, hook_dispatcher, and AI API dependencies.
AI distillation is delegated to Claude Code skills (/ingest, /compile).

This module handles:
- evolve_knowledge: scan wiki/ for 3+ pages with same tag → draft proposals
- write_digest: write daily digest summaries to raw/
- run_distill_cycle: maintenance pipeline (decay + evolve), AI parts are manual
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from knowledge_studio.store import (
    DEFAULT_CONFIG,
    _atomic_write,
    _load_access_counts,
    _update_frontmatter_field,
    apply_decay,
    compute_score,
    drafts_dir,
    make_slug,
    parse_wiki_file,
    wiki_dir,
)

_logger = logging.getLogger(__name__)


def write_digest(
    title: str,
    content: str,
    source_count: int = 0,
    tags: list[str] | None = None,
) -> Path:
    """Write a daily digest summary to raw/{YYYY}/{MM}/{DD}/.

    Digests are episodic memory — no decay, no stability score.
    Used by recall_episodic() for search-based retrieval.
    """
    rd = _digests_dir()
    now = datetime.now(UTC)
    date_dir = rd / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    slug = make_slug(title, fallback="digest")
    slug = f"{now.strftime('%Y%m%d')}-{slug}"

    file_path = date_dir / f"{slug}.md"
    counter = 1
    while file_path.exists():
        file_path = date_dir / f"{slug}-{counter}.md"
        counter += 1

    frontmatter: dict = {
        "title": title,
        "date": now.strftime("%Y-%m-%d"),
        "source_count": source_count,
    }
    if tags:
        frontmatter["tags"] = ", ".join(tags)

    frontmatter_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _atomic_write(file_path, f"---\n{frontmatter_str}---\n\n{content}")
    return file_path


def _digests_dir() -> Path:
    return _raw_base() / ".logs" / "digests"


def _raw_base() -> Path:
    from knowledge_studio.store import repo_root
    return repo_root() / "raw"


def evolve_knowledge(config: dict | None = None) -> dict:
    """Draft wiki proposals from high-value page clusters for human review.

    Scans wiki/ for pages with score > 0.5 grouped by primary tag.
    3+ pages with same tag → draft merged proposal to drafts/{tag}.md.

    Returns {"drafts": int, "tags_evaluated": int}.
    """
    wd = wiki_dir()
    if not wd.exists():
        return {"drafts": 0, "tags_evaluated": 0}

    access_counts = _load_access_counts()
    all_pages: list[dict] = []
    for f in wd.rglob("*.md"):
        if f.name == "INDEX.md":
            continue
        meta = parse_wiki_file(f)
        if not meta or meta.get("archived"):
            continue
        if meta.get("status") == "dropped":
            continue
        meta["score"] = compute_score(meta, access_counts.get(meta["slug"], 0), config)
        all_pages.append(meta)

    drafts_written = _draft_wiki_proposals(all_pages)
    return {
        "drafts": drafts_written,
        "tags_evaluated": len(all_pages),
    }


def _draft_wiki_proposals(pages: list[dict]) -> int:
    """Draft merged wiki proposals from 3+ pages sharing a primary tag."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in pages:
        tags = item.get("tags", "")
        if isinstance(tags, list):
            tags = " ".join(str(t) for t in tags)
        first_tag = (
            str(tags).split(",")[0].strip().split()[0]
            if tags and str(tags).strip()
            else ""
        )
        if first_tag and item["score"] > 0.5:
            groups[first_tag].append(item)

    dd = drafts_dir()
    count = 0
    for tag, items in groups.items():
        if len(items) < 3:
            continue

        slug = tag.lower().replace(" ", "-")
        draft_path = dd / f"{slug}.md"
        if draft_path.exists():
            continue

        sample = items[0]
        area = sample.get("area", "computing")
        wiki_type = sample.get("type", "concept")

        sections = [f"# {tag.title()} — Wiki Proposal\n"]
        sections.append(
            f"> Drafted from {len(items)} wiki pages. "
            f"Sources: {', '.join(i['slug'] for i in items[:5])}.\n"
        )
        sections.append(f"Proposed type: `{wiki_type}` | Area: `{area}`\n")
        for item in sorted(items, key=lambda x: -x["score"])[:5]:
            title = item.get("title", item["slug"])
            body = item.get("body", "")[:300]
            sections.append(f"## {title}\n{body}\n")

        sections.append("\n---\nReview and merge into wiki/ if valuable, or discard.")

        now = datetime.now(UTC).strftime("%Y-%m-%d")
        frontmatter = yaml.dump(
            {
                "title": f"{tag.title()} Proposal",
                "draft_type": wiki_type,
                "draft_area": area,
                "source_pages": [i["slug"] for i in items[:5]],
                "drafted_at": now,
                "status": "draft",
            },
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        dd.mkdir(parents=True, exist_ok=True)
        _atomic_write(draft_path, f"---\n{frontmatter}---\n\n" + "\n".join(sections))
        count += 1
        _logger.info(
            "Drafted wiki proposal for tag '%s' from %d pages", tag, len(items)
        )

    return count


def run_distill_cycle(config: dict | None = None) -> dict:
    """Maintenance pipeline: apply decay + evolve knowledge.

    AI distillation (raw → drafts) is handled by Claude Code /ingest skill.
    This function handles the non-AI maintenance:
    1. Apply decay to wiki pages
    2. Evolve knowledge (generate draft proposals from page clusters)

    Returns:
        {"dropped": [...], "drafts": int, "evolved_tags": int}
    """
    cfg = config or DEFAULT_CONFIG
    _logger.info("distiller: starting maintenance cycle")

    dropped = apply_decay(cfg)
    evolution = evolve_knowledge(cfg)

    _logger.info(
        "distiller: cycle done — %d dropped, %d drafts",
        len(dropped),
        evolution.get("drafts", 0),
    )
    return {
        "dropped": dropped,
        "drafts": evolution.get("drafts", 0),
        "evolved_tags": evolution.get("tags_evaluated", 0),
    }
