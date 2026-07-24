"""Knowledge Recall — two-path retrieval: episodic search + knowledge stability.

Extracted from autpilot-web/backend/app/services/knowledge_recall.py.
Removed settings and knowledge_sync dependencies. Uses store.repo_root().

6+1-factor relevance scoring:
  1. Token overlap (×0.3) — jieba segmentation + intersection
  2. Substring match (+1.0 title / +0.5 body)
  3. Topic trace match (+2.0)
  4. Type boost (anti-pattern=1.5, strategy=0.8, concept=0.6)
  5. Review penalty boost (+2.0 wrong / +1.0 failure)
  6. Memory-curve score (×0.5)
  7. Goal boost — active goals (profiles/goals/, status=active) lift pages
     that already matched: area in a goal's domains (+0.8) and page content
     hits a goal keyword (+0.4). No-op when there are no active goals.

Recall is read-only: a search does NOT count as a use and never mutates
access counts or page state. Access is recorded only via the explicit
`store.record_access` signal (exposed as `oks wiki use <slug>`), so the
memory curve reflects real usage, not query frequency.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowledge_studio.store import (
    list_wiki_pages,
    load_active_goals,
    raw_dir,
    repo_root,
)

_logger = logging.getLogger(__name__)

DEFAULT_RECALL_LIMIT = 5
MAX_BODY_PREVIEW = 200


def recall(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
    scope: str | None = None,
    goal_boost: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Two-path recall: episodic (search) + knowledge (stability).

    scope narrows only the knowledge path (wiki area); episodic recall stays
    global since raw/ is time-partitioned and has no area.
    """
    return {
        "episodic": recall_episodic(query=query, topic_id=topic_id, limit=limit),
        "knowledge": recall_knowledge(
            query=query, topic_id=topic_id, limit=limit, scope=scope, goal_boost=goal_boost
        ),
    }


def recall_episodic(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
) -> list[dict[str, Any]]:
    """Search episodic memory (raw/) by keyword with freshness weighting."""
    if not query.strip():
        return []

    root = repo_root()
    query_lower = query.lower().strip()
    query_tokens = _tokenize(query_lower)
    results: list[tuple[float, dict[str, Any]]] = []

    rd = raw_dir()
    if rd.exists():
        for f in rd.rglob("*.md"):
            try:
                content = f.read_text(encoding="utf-8").lower()
                if _matches_query(content, query_lower, query_tokens):
                    freshness = _freshness_score(f)
                    snippet_idx = content.find(query_lower) if len(query_lower) > 3 else 0
                    snippet = content[snippet_idx:snippet_idx + 300] if snippet_idx >= 0 else content[:300]
                    results.append((freshness, {
                        "type": "raw",
                        "source_path": str(f.relative_to(root)),
                        "snippet": snippet,
                        "freshness": round(freshness, 3),
                        "relevance": round(freshness, 3),
                    }))
            except OSError:
                continue

        for f in rd.rglob("*.jsonl"):
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    content = json.dumps(entry, ensure_ascii=False).lower()
                    if _matches_query(content, query_lower, query_tokens):
                        freshness = _freshness_score(f)
                        results.append((freshness + 0.5, {
                            "type": "trace",
                            "source_path": str(f.relative_to(root)),
                            "snippet": content[:300],
                            "freshness": round(freshness, 3),
                            "relevance": round(freshness + 0.5, 3),
                        }))
            except (json.JSONDecodeError, OSError):
                continue

    profiles_dir = root / "profiles"
    if profiles_dir.exists():
        for f in profiles_dir.rglob("*.md"):
            try:
                content = f.read_text(encoding="utf-8").lower()
                if _matches_query(content, query_lower, query_tokens):
                    freshness = _freshness_score(f)
                    snippet_idx = content.find(query_lower) if len(query_lower) > 3 else 0
                    snippet = content[snippet_idx:snippet_idx + 300] if snippet_idx >= 0 else content[:300]
                    results.append((freshness + 1.0, {
                        "type": "profile",
                        "source_path": str(f.relative_to(root)),
                        "snippet": snippet,
                        "freshness": round(freshness, 3),
                        "relevance": round(freshness + 1.0, 3),
                    }))
            except OSError:
                continue

    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:limit]]


def recall_knowledge(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
    scope: str | None = None,
    goal_boost: bool = True,
) -> list[dict[str, Any]]:
    """Find wiki pages relevant to the query via 6+1-factor scoring.

    scope: optional area name for soft, opt-in narrowing (reuses the `area`
    field). None = global recall across all areas. This is a soft scope, not
    a hard partition — it filters candidates before scoring, nothing more.

    goal_boost: when True (default), pages that already matched are lifted if
    they fall within an active goal's domains/keywords. No-op when there are
    no active goals, so it is safe to leave on.
    """
    all_pages = list_wiki_pages()
    if not all_pages:
        return []

    scope_lower = scope.lower().strip() if scope else ""

    goal_domains: set[str] = set()
    goal_keywords: set[str] = set()
    if goal_boost:
        for goal in load_active_goals():
            goal_domains |= goal.get("domains", set())
            goal_keywords |= goal.get("keywords", set())

    query_lower = query.lower().strip() if query else ""
    query_tokens = _tokenize(query_lower)

    scored: list[tuple[float, dict]] = []
    for item in all_pages:
        if item.get("status") in ("dropped", "superseded") or item.get("archived"):
            continue

        if scope_lower and str(item.get("area", "")).lower().strip() != scope_lower:
            continue

        relevance = _compute_relevance(
            item, query_lower, query_tokens, topic_id, goal_domains, goal_keywords
        )
        if relevance > 0:
            scored.append((relevance, item))

    scored.sort(key=lambda x: (-x[0], x[1]["slug"]))

    results: list[dict[str, Any]] = []
    for relevance, item in scored[:limit]:
        review = item.get("review") or {}
        entry: dict[str, Any] = {
            "slug": item["slug"],
            "title": item.get("title", item["slug"]),
            "type": item.get("type", item.get("category", "concept")),
            "area": item.get("area", ""),
            "status": item.get("status", "active"),
            "score": round(item.get("score", 0), 3),
            "relevance": round(relevance, 3),
            "confidence": item.get("confidence", 0.8),
            "body_preview": item.get("body", "")[:MAX_BODY_PREVIEW],
            "tags": item.get("tags", ""),
            "has_traces": bool(item.get("traces")),
            "relates_to": item.get("relates_to", ""),
            "relationship": item.get("relationship", ""),
        }
        if review.get("lesson"):
            entry["review_lesson"] = review["lesson"][:200]
        results.append(entry)

    return results


def _tokenize(text: str) -> set[str]:
    """Split text into search tokens using jieba when available."""
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "on", "at", "for", "with", "and", "or", "not",
        "this", "that", "it", "from", "by", "as", "how", "what", "why",
        "的", "了", "是", "在", "和", "与", "或", "也", "都", "就", "这", "那",
    }
    raw_words: list[str]
    try:
        import jieba

        import logging as _logging
        jieba.setLogLevel(_logging.WARNING)  # silence "Building prefix dict" chatter
        raw_words = list(jieba.cut_for_search(text))
    except Exception:
        raw_words = text.split()

    tokens = set()
    _strip_chars = ".,!?;:\"'()[]{}，。！？；：''""（）【】"
    for word in raw_words:
        word = word.strip(_strip_chars)
        if len(word) < 2 or word in stopwords:
            continue
        tokens.add(word)
    return tokens


def _compute_relevance(
    item: dict,
    query_lower: str,
    query_tokens: set[str],
    topic_id: int | None,
    goal_domains: set[str] | None = None,
    goal_keywords: set[str] | None = None,
) -> float:
    base = 0.0

    title = item.get("title", "").lower()
    body = item.get("body", "").lower()
    tags_raw = item.get("tags", "")
    if isinstance(tags_raw, list):
        tags = " ".join(str(t) for t in tags_raw).lower()
    else:
        tags = str(tags_raw).lower()

    searchable = f"{title} {body} {tags}"
    if query_tokens:
        overlap = sum(1 for t in query_tokens if t in searchable)
        base += overlap * 0.3

    if query_lower and len(query_lower) > 3:
        if query_lower in title:
            base += 1.0
        if query_lower in body:
            base += 0.5

    if topic_id is not None:
        traces = item.get("traces") or []
        for trace in traces:
            if trace.get("kind") == "discuss" and str(trace.get("id")) == str(topic_id):
                base += 2.0
                break

    has_query = bool(query_lower.strip() or query_tokens or topic_id is not None)
    if has_query and base == 0:
        return 0.0

    wiki_type = item.get("type", item.get("category", "concept"))
    type_boost = {
        "anti-pattern": 1.5,
        "strategy": 0.8,
        "concept": 0.6,
    }
    relevance = base * type_boost.get(wiki_type, 0.5)

    review = item.get("review")
    if review and isinstance(review, dict):
        if review.get("decision_correct") is False:
            relevance += 2.0
        if review.get("outcome") == "failure":
            relevance += 1.0

    score = item.get("score", 0)
    relevance += score * 0.5

    if relevance > 0 and (goal_domains or goal_keywords):
        if goal_domains and str(item.get("area", "")).lower().strip() in goal_domains:
            relevance += 0.8
        if goal_keywords and any(kw in searchable for kw in goal_keywords):
            relevance += 0.4

    return relevance


def _matches_query(content: str, query_lower: str, query_tokens: set[str]) -> bool:
    if query_lower and len(query_lower) > 3 and query_lower in content:
        return True
    if query_tokens:
        return any(token in content for token in query_tokens)
    return bool(query_lower and query_lower in content)


def _freshness_score(file_path: Path) -> float:
    try:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
    except (OSError, ValueError):
        return 0.5
    days_old = max(0, (datetime.now(UTC) - mtime).days)
    return max(0.01, 1.0 * (0.95 ** days_old))
