"""Knowledge metrics — 4-dimension report card.

Extracted from autpilot-web/backend/app/services/knowledge_metrics.py.
Removed KnowledgeStore dependency. Uses store functions.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from knowledge_studio.store import list_wiki_pages, repo_root, wiki_dir


def get_knowledge_report() -> dict:
    """Full 4-dimension knowledge report card."""
    wiki_pages = list_wiki_pages()

    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    ninety_days_ago = now - timedelta(days=90)

    return {
        "scale": _compute_scale(wiki_pages),
        "vitality": _compute_vitality(wiki_pages, seven_days_ago),
        "value": _compute_value(wiki_pages),
        "credibility": _compute_credibility(wiki_pages, ninety_days_ago),
    }


def _compute_scale(pages: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    for item in pages:
        wt = item.get("type", item.get("category", "concept"))
        by_type[wt] = by_type.get(wt, 0) + 1

    wd = wiki_dir()
    areas = 0
    if wd.exists():
        areas = sum(1 for d in wd.iterdir() if d.is_dir() and not d.name.startswith("."))

    return {
        "total_wiki_pages": len(pages),
        "wiki_by_type": by_type,
        "wiki_areas": areas,
    }


def _compute_vitality(pages: list[dict], seven_days_ago: datetime) -> dict:
    recent = sum(1 for item in pages if _parse_date(item.get("created")) >= seven_days_ago)
    active = [item for item in pages if item.get("status", "active") not in ("dropped", "superseded") and not item.get("archived")]
    active_ratio = len(active) / len(pages) if pages else 0
    return {
        "wiki_pages_last_7d": recent,
        "active_wiki_ratio": round(active_ratio, 3),
        "dropped_count": len(pages) - len(active),
    }


def _compute_value(pages: list[dict]) -> dict:
    traced = [item for item in pages if item.get("traces")]
    with_review = [item for item in pages if item.get("review")]
    total_access = sum(item.get("access_count", 0) for item in pages)
    avg_access = total_access / len(pages) if pages else 0
    return {
        "wiki_with_traces": len(traced),
        "wiki_with_review": len(with_review),
        "total_access_count": total_access,
        "avg_access_per_wiki": round(avg_access, 1),
    }


def _compute_credibility(pages: list[dict], ninety_days_ago: datetime) -> dict:
    total = len(pages)
    if total == 0:
        return {"trace_coverage": 0, "review_coverage": 0, "fresh_ratio": 0, "avg_confidence": 0, "avg_score": 0}
    traced = [item for item in pages if item.get("traces")]
    reviewed = [item for item in pages if item.get("review")]
    fresh = [item for item in pages if _parse_date(item.get("created")) >= ninety_days_ago or item.get("access_count", 0) > 0]
    avg_confidence = sum(item.get("confidence", 0.5) for item in pages) / total
    avg_score = sum(item.get("score", 0) for item in pages) / total
    return {
        "trace_coverage": round(len(traced) / total, 3),
        "review_coverage": round(len(reviewed) / total, 3),
        "fresh_ratio": round(len(fresh) / total, 3),
        "avg_confidence": round(avg_confidence, 3),
        "avg_score": round(avg_score, 3),
    }


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=UTC)
