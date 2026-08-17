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
  7. Goal boost — all active goals by default, one explicit goal for a
     reproducible run, or disabled. Matching area adds 0.8 and matching a
     goal keyword adds 0.4 to pages that already matched the query.

Explain mode exposes every score component and matching reason without
changing the ranking. Structured responses use recall-response/v1 and
recall-hit/v1 so evaluation tooling does not have to parse terminal tables.

Recall is read-only: a search does NOT count as a use and never mutates
access counts or page state. Access is recorded only via the explicit
`store.record_access` signal (exposed as `oks wiki use <slug>`), so the
memory curve reflects real usage, not query frequency.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowledge_studio.store import (
    get_goal,
    list_wiki_pages,
    load_active_goals,
    raw_dir,
    repo_root,
)

_logger = logging.getLogger(__name__)

DEFAULT_RECALL_LIMIT = 5
MAX_BODY_PREVIEW = 200
RECALL_HIT_SCHEMA = "recall-hit/v1"
RECALL_RESPONSE_SCHEMA = "recall-response/v1"

# Subdirectories of raw/ that hold records rather than human-collected material.
# CONSTITUTION P3: recalling them would feed an agent its own output back as
# memory. executions/ holds provenance traces; .logs/ holds tool and AI-written
# digests (see distiller.write_digest).
_NON_RECALLABLE_RAW_SUBDIRS = ("executions", ".logs")

# A2 requires every injected item to carry a source label. Episodic hits used to
# arrive unlabelled, and raw/ is the one channel that holds third-party text an
# agent must never take instructions from.
_EPISODIC_SOURCE_LABELS = {
    "raw": "[untrusted-source]",
    "trace": "[provenance]",
    "profile": "[user-declared]",
}


def load_recall_params(root=None):
    """Load recall params: env > settings/recall.yaml > code defaults.

    Per-instance tunable params. Users edit settings/recall.yaml, commit it,
    and the params travel with their knowledge base. OKS only ships defaults.
    """
    import os
    from pathlib import Path

    params = {
        "recall_floor": 0.7, "recall_topn": 3, "recall_minlen": 6,
        "recall_cooldown": 10,
        "posttool_floor": 0.9, "posttool_topn": 2, "posttool_mode": "signal",
        "posttool_recall": 1, "posttool_signal_rel_floor": 2.5,
        "conflict_window": 300, "search_backend": "native", "mail_topn": 3,
    }

    # 1. settings/recall.yaml (per-instance, git-synced)
    try:
        import yaml
        from knowledge_studio.store import repo_root
        kb_root = root if root is not None else repo_root()
        ypath = Path(kb_root) / "settings" / "recall.yaml"
        if ypath.is_file():
            data = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
            rc = data.get("recall", {}) or {}
            pc = data.get("posttool", {}) or {}
            cc = data.get("conflict", {}) or {}
            params["recall_floor"] = float(rc.get("floor", params["recall_floor"]))
            params["recall_topn"] = int(rc.get("topn", params["recall_topn"]))
            params["recall_minlen"] = int(rc.get("minlen", params["recall_minlen"]))
            params["recall_cooldown"] = int(rc.get("cooldown", params["recall_cooldown"]))
            params["posttool_floor"] = float(pc.get("floor", params["posttool_floor"]))
            params["posttool_topn"] = int(pc.get("topn", params["posttool_topn"]))
            params["posttool_mode"] = str(pc.get("mode", params["posttool_mode"]))
            params["posttool_recall"] = int(pc.get("recall", params["posttool_recall"]))
            params["posttool_signal_rel_floor"] = float(pc.get("signal_rel_floor", params["posttool_signal_rel_floor"]))
            params["conflict_window"] = int(cc.get("window", params["conflict_window"]))
            params["search_backend"] = str(data.get("search_backend", params["search_backend"]))
            params["mail_topn"] = int(data.get("mail_topn", params["mail_topn"]))
    except Exception:
        pass

    # env 已废弃——settings/recall.yaml 是唯一真源（git 同步，走到哪带到哪）。
    # 临时调参用 CLI flag（oks recall --floor 0.9），不污染持久状态。
    # 迁移：检测到旧 OKS_ env 时警告，提示迁移到 yaml + unset。
    _legacy_env = [
        "OKS_RECALL_FLOOR", "OKS_RECALL_TOPN", "OKS_RECALL_MINLEN",
        "OKS_RECALL_COOLDOWN", "OKS_POSTTOOL_FLOOR", "OKS_POSTTOOL_TOPN",
        "OKS_POSTTOOL_MODE", "OKS_POSTTOOL_RECALL", "OKS_POSTTOOL_SIGNAL_REL_FLOOR",
        "OKS_CONFLICT_WINDOW", "OKS_SEARCH_BACKEND", "OKS_MAIL_TOPN",
    ]
    import os as _os
    _found = [k for k in _legacy_env if _os.environ.get(k)]
    if _found and not getattr(load_recall_params, "_warned", False):
        load_recall_params._warned = True
        import sys
        print(
            "⚠ OKS: 检测到旧环境变量 " + ", ".join(_found) + "，已废弃。\n"
            "  settings/recall.yaml 是唯一参数真源（git 同步）。\n"
            "  请把值迁移到 settings/recall.yaml，然后 unset 这些 env。\n"
            "  临时调参用 CLI flag: oks recall --floor 0.9",
            file=sys.stderr,
        )
    return params


def _resolve_goal_context(
    goal: str | None = None,
    *,
    goal_boost: bool = True,
) -> dict[str, Any]:
    """Resolve a deterministic goal selection for recall.

    ``None`` and ``active`` preserve the historical behavior of merging all
    active goals. ``none`` disables goal influence. Any other value selects a
    single goal by slug, including an inactive goal for historical replay.
    """
    requested = (goal or "active").strip()
    normalized = requested.lower()

    if not goal_boost or normalized == "none":
        selected: list[dict] = []
        mode = "none"
    elif normalized == "active":
        selected = load_active_goals()
        mode = "active"
    else:
        # 支持逗号分隔多 slug（terminal registry goal_slugs）
        slugs = [s.strip() for s in requested.split(",") if s.strip()]
        selected = []
        for slug in slugs:
            g = get_goal(slug)
            if g is not None:
                selected.append(g)
        if not selected:
            raise ValueError(f"Goal not found: {requested}")
        mode = "explicit"

    domains: set[str] = set()
    keywords: set[str] = set()
    for item in selected:
        domains |= item.get("domains", set())
        keywords |= item.get("keywords", set())

    return {
        "mode": mode,
        "requested": requested,
        "goals": selected,
        "domains": domains,
        "keywords": keywords,
    }


def describe_goal_selection(
    goal: str | None = None,
    *,
    goal_boost: bool = True,
) -> dict[str, Any]:
    """Return the JSON-safe goal context used by a recall request."""
    context = _resolve_goal_context(goal, goal_boost=goal_boost)
    return {
        "mode": context["mode"],
        "requested": context["requested"],
        "slugs": [item["slug"] for item in context["goals"]],
        "domains": sorted(context["domains"]),
        "keywords": sorted(context["keywords"]),
    }


def recall(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
    scope: str | None = None,
    goal_boost: bool = True,
    goal: str | None = None,
    explain: bool = False,
    user_id: str | None = None,
    project_slug: str | None = None,
    type_filter: str | None = None,
    knowledge_only: bool = False,
    search_backend: str = "native",
) -> dict[str, Any]:
    """Two-path recall: episodic (raw/ + profiles/) + knowledge (wiki/).

    scope narrows the knowledge path (wiki area). user_id / project_slug name
    the current identity so the episodic path may include those private
    profiles; without them A2 scope filtering excludes every user/project
    profile rather than leaking one.

    type_filter restricts the knowledge path to one wiki type. knowledge_only
    drops the episodic path — someone querying `wiki/` directly does not want
    raw source material mixed in. Both default to the previous behaviour, so
    existing callers including the auto-recall hook are unaffected.
    """
    goal_context = _resolve_goal_context(goal, goal_boost=goal_boost)
    return {
        "schema_version": RECALL_RESPONSE_SCHEMA,
        "query": query,
        "topic_id": topic_id,
        "scope": scope,
        "limit": limit,
        "goal": {
            "mode": goal_context["mode"],
            "requested": goal_context["requested"],
            "slugs": [item["slug"] for item in goal_context["goals"]],
            "domains": sorted(goal_context["domains"]),
            "keywords": sorted(goal_context["keywords"]),
        },
        "episodic": [] if knowledge_only else recall_episodic(
            query=query, topic_id=topic_id, limit=limit,
            user_id=user_id, project_slug=project_slug,
        ),
        "knowledge": _recall_knowledge_via_backend(
            query=query,
            topic_id=topic_id,
            limit=limit,
            scope=scope,
            goal_context=goal_context,
            explain=explain,
            type_filter=type_filter,
            search_backend=search_backend,
        ),
    }


def _profile_in_scope(
    path: Path, profiles_dir: Path, user_id: str | None, project_slug: str | None
) -> bool:
    """Enforce CONSTITUTION A2 scope filtering for profiles/.

    User and project profiles are private: they are recallable only when the
    caller names the current identity. Anything unnamed is excluded rather than
    leaked. team.md, goals/ and recipes/ are shared, so they stay recallable.
    """
    try:
        relative = path.relative_to(profiles_dir)
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] == "users":
        return user_id is not None and len(parts) > 1 and parts[1] in (user_id, f"{user_id}.md")
    if parts[0] == "projects":
        if project_slug is None or len(parts) < 2:
            return False
        return parts[1] in (project_slug, f"{project_slug}.md")
    return True


def recall_episodic(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
    user_id: str | None = None,
    project_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Search episodic memory (raw/) by keyword with freshness weighting.

    Profiles under users/ and projects/ are private per CONSTITUTION A2: they
    are returned only when *user_id* / *project_slug* name the current identity.
    Leaving them unset excludes those profiles instead of leaking them.
    """
    if not query.strip():
        return []

    root = repo_root()
    query_lower = query.lower().strip()
    query_tokens = _tokenize(query_lower)
    results: list[tuple[float, dict[str, Any]]] = []

    rd = raw_dir()
    if rd.exists():
        # Provenance and AI-written logs are records, not human-collected
        # material: recalling them would feed an agent its own output back as
        # memory, ranked above the real sources it came from.
        excluded_roots = tuple(rd / name for name in _NON_RECALLABLE_RAW_SUBDIRS)

        def _is_excluded(path: Path) -> bool:
            return any(root_dir in path.parents for root_dir in excluded_roots)

        for f in rd.rglob("*.md"):
            if _is_excluded(f):
                continue
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
            if _is_excluded(f):
                continue
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
            if not _profile_in_scope(f, profiles_dir, user_id, project_slug):
                continue
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
    ranked: list[dict[str, Any]] = []
    for rank, (_, item) in enumerate(results[:limit], start=1):
        item["schema_version"] = RECALL_HIT_SCHEMA
        item["channel"] = "episodic"
        # Default to untrusted: an unrecognised episodic type is third-party
        # text until proven otherwise, never trusted memory.
        item["source_label"] = _EPISODIC_SOURCE_LABELS.get(
            item.get("type", ""), "[untrusted-source]"
        )
        item["rank"] = rank
        ranked.append(item)
    return ranked


def recall_knowledge(
    query: str = "",
    topic_id: int | None = None,
    limit: int = DEFAULT_RECALL_LIMIT,
    scope: str | None = None,
    goal_boost: bool = True,
    goal: str | None = None,
    explain: bool = False,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Find wiki pages relevant to the query via 6+1-factor scoring.

    scope: optional area name for soft, opt-in narrowing (reuses the `area`
    field). None = global recall across all areas. This is a soft scope, not
    a hard partition — it filters candidates before scoring, nothing more.

    goal_boost: compatibility switch that disables all goal influence when
    False. ``goal`` selects ``active`` (default), ``none``, or one goal slug.

    explain: include score components and human-readable match reasons. This
    does not change ranking and is intended for evaluation and debugging.

    type_filter: optional wiki type filter applied before ranking and limit.
    """
    goal_context = _resolve_goal_context(goal, goal_boost=goal_boost)
    return _recall_knowledge_with_context(
        query=query,
        topic_id=topic_id,
        limit=limit,
        scope=scope,
        goal_context=goal_context,
        explain=explain,
        type_filter=type_filter,
    )


def _recall_knowledge_via_backend(
    *,
    query: str,
    topic_id: int | None,
    limit: int,
    scope: str | None,
    goal_context: dict[str, Any],
    explain: bool,
    type_filter: str | None = None,
    search_backend: str = "native",
) -> list[dict[str, Any]]:
    """Dispatch knowledge recall to native or a pluggable search backend.

    native (default) → OKS 6+1 factor recall (jieba + IDF + title boost).
    fts5 → SQLite FTS5 + BM25 (CV from TreeSearch, persistent index).
    fusion → native top-3 + fts5 supplement-2 (experiment-validated optimal).
    other → connector entry_points(group="oks_search_backend").
    """
    if search_backend == "native" or not search_backend:
        return _recall_knowledge_with_context(
            query=query,
            topic_id=topic_id,
            limit=limit,
            scope=scope,
            goal_context=goal_context,
            explain=explain,
            type_filter=type_filter,
        )

    from .search import get_backend
    from .store import repo_root

    backend = get_backend(search_backend, root=repo_root())
    backend_kwargs: dict[str, Any] = {}
    requested = goal_context.get("requested", "none")
    if goal_context.get("mode") != "none" and requested not in ("active", "none"):
        backend_kwargs["goal"] = requested
    hits = backend.search(query, limit=limit, scope=scope, **backend_kwargs)

    # 补全 recall-hit/v1 字段：backend 返回 SearchHit（slug/title/score），
    # 其余字段从 wiki 页详情查补，保证 /query skill 和 eval 不受影响。
    pages = {p.get("slug"): p for p in list_wiki_pages()}
    results: list[dict[str, Any]] = []
    for rank, h in enumerate(hits[:limit], start=1):
        p = pages.get(h.slug, {})
        review = p.get("review") or {}
        entry: dict[str, Any] = {
            "schema_version": RECALL_HIT_SCHEMA,
            "channel": "knowledge",
            "rank": rank,
            "slug": h.slug,
            "title": h.title or p.get("title", h.slug),
            "type": p.get("type", p.get("category", "concept")),
            "area": p.get("area", ""),
            "status": p.get("status", "active"),
            "score": round(float(p.get("score", 0) or 0), 3),
            "relevance": round(h.score, 3),
            "confidence": p.get("confidence", 0.8),
            "body_preview": p.get("body", "")[:MAX_BODY_PREVIEW],
            "tags": p.get("tags", ""),
            "has_traces": bool(p.get("traces")),
            "human_reviewed_at": p.get("human_reviewed_at", ""),
            "relates_to": p.get("relates_to", ""),
            "relationship": p.get("relationship", ""),
            "backend": h.backend,
        }
        if review.get("lesson"):
            entry["review_lesson"] = review["lesson"]
        results.append(entry)
    return results


def _recall_knowledge_with_context(
    *,
    query: str,
    topic_id: int | None,
    limit: int,
    scope: str | None,
    goal_context: dict[str, Any],
    explain: bool,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    all_pages = list_wiki_pages()
    if not all_pages:
        return []

    scope_areas = {s.strip().lower() for s in scope.split(",") if s.strip()} if scope else set()
    type_lower = type_filter.lower().strip() if type_filter else ""
    query_lower = query.lower().strip() if query else ""
    query_tokens = _tokenize(query_lower)

    scored: list[tuple[float, dict, dict[str, Any]]] = []
    # IDF 加权（CV from TreeSearch estimate_idf）：全库 body+title 估 IDF，
    # 稀有 query term 权重高，避免常见词淹没信号。
    query_terms = list(query_tokens)
    idf = estimate_idf(
        query_terms,
        [f"{p.get('title', '')} {p.get('body', '')}" for p in all_pages],
    )
    for item in all_pages:
        if item.get("status") in ("dropped", "superseded") or item.get("archived"):
            continue

        if scope_areas and str(item.get("area", "")).lower().strip() not in scope_areas:
            continue

        item_type = str(item.get("type", item.get("category", "concept")))
        if type_lower and item_type.lower().strip() != type_lower:
            continue

        components = _compute_relevance_components(
            item,
            query_lower,
            query_tokens,
            topic_id,
            goal_context,
            idf=idf,
        )
        relevance = components["final_score"]
        if relevance > 0:
            scored.append((relevance, item, components))

    scored.sort(key=lambda x: (-x[0], x[1]["slug"]))

    results: list[dict[str, Any]] = []
    for rank, (relevance, item, components) in enumerate(scored[:limit], start=1):
        review = item.get("review") or {}
        entry: dict[str, Any] = {
            "schema_version": RECALL_HIT_SCHEMA,
            "channel": "knowledge",
            "rank": rank,
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
            # The /query skill derives [verified] from one of two recorded
            # facts: trace evidence, or a human review. Both must be visible
            # here or the label rule cannot be applied.
            "human_reviewed_at": item.get("human_reviewed_at", ""),
            "relates_to": item.get("relates_to", ""),
            "relationship": item.get("relationship", ""),
        }
        if review.get("lesson"):
            entry["review_lesson"] = review["lesson"][:200]
        if explain:
            entry["score_components"] = {
                key: round(value, 6) if isinstance(value, float) else value
                for key, value in components.items()
                if key not in {"reasons", "goal_matches"}
            }
            entry["reasons"] = components["reasons"]
            entry["goal_matches"] = components["goal_matches"]
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
    # Markdown punctuation must go: the jieba-less fallback only splits on
    # whitespace, so `**git**` and `` `oks` `` would survive as tokens that can
    # never match a clean query token now that both sides are tokenized.
    _strip_chars = ".,!?;:\"'()[]{}*_`~#>，。！？；：''""（）【】"
    for word in raw_words:
        word = word.strip(_strip_chars)
        if len(word) < 2 or word in stopwords:
            continue
        tokens.add(word)
    return tokens


# ── IDF-weighted token overlap (CV from TreeSearch heuristics.py, shibing624) ──
# Pure functions, no extra deps. estimate_idf uses smooth IDF:
# log((N+1)/(df+1)) + 1 to avoid zero weights for unseen terms.


def estimate_idf(terms: list[str], corpus_texts: list[str]) -> dict[str, float]:
    """Estimate smooth IDF weights for query terms from a corpus.

    Uses smooth IDF: log((N + 1) / (df + 1)) + 1 to avoid zero weights.
    Corpus is typically all wiki page texts in scope.
    """
    n = len(corpus_texts)
    if n == 0:
        return {t: 1.0 for t in terms}
    df: dict[str, int] = {t: 0 for t in terms}
    for text in corpus_texts:
        text_lower = text.lower()
        for t in terms:
            if t in text_lower:
                df[t] += 1
    return {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in terms}


def compute_term_overlap(text: str, terms: list[str], idf: dict[str, float] | None = None) -> float:
    """Compute IDF-weighted fraction of query terms that appear in text.

    Rare terms (high IDF) contribute more than common terms. Falls back to
    uniform weighting when idf is None. Returns a value in [0.0, 1.0].
    """
    if not text or not terms:
        return 0.0
    text_lower = text.lower()
    if idf:
        total_w = sum(idf.get(t, 1.0) for t in terms)
        if total_w <= 0:
            return 0.0
        hit_w = sum(idf.get(t, 1.0) for t in terms if t in text_lower)
        return hit_w / total_w
    matched = sum(1 for t in terms if t in text_lower)
    return matched / len(terms)


def check_title_match(title: str, terms: list[str]) -> bool:
    """Check if any query term appears in the title (CV from TreeSearch)."""
    if not title or not terms:
        return False
    title_lower = title.lower()
    return any(t in title_lower for t in terms)


# 通用目录性页（学习迁移自 TreeSearch is_generic_section + _GENERIC_SECTIONS）
_GENERIC_PAGE_TITLES = frozenset({
    "index", "overview", "readme", "目录", "概述", "总览", "首页",
    "introduction", "conclusion", "background", "summary",
})


def is_generic_page(title: str) -> bool:
    """通用目录性页降权（学习迁移自 TreeSearch is_generic_section）。

    这类页（index/overview/README/概述）信息密度低——BM25/token 命中多但
    很少含精确答案，×0.5 降权避免淹没具体策略页。
    """
    if not title:
        return False
    return title.strip().lower() in _GENERIC_PAGE_TITLES


def _compute_relevance(
    item: dict,
    query_lower: str,
    query_tokens: set[str],
    topic_id: int | None,
    goal_domains: set[str] | None = None,
    goal_keywords: set[str] | None = None,
) -> float:
    """Compatibility wrapper returning only the final relevance score."""
    context = {
        "mode": "legacy",
        "requested": "legacy",
        "goals": [],
        "domains": goal_domains or set(),
        "keywords": goal_keywords or set(),
    }
    return _compute_relevance_components(
        item, query_lower, query_tokens, topic_id, context
    )["final_score"]


def _compute_relevance_components(
    item: dict,
    query_lower: str,
    query_tokens: set[str],
    topic_id: int | None,
    goal_context: dict[str, Any],
    idf: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute relevance and retain every component used in the score."""
    reasons: list[str] = []

    title = item.get("title", "").lower()
    body = item.get("body", "").lower()
    tags_raw = item.get("tags", "")
    if isinstance(tags_raw, list):
        tags = " ".join(str(t) for t in tags_raw).lower()
    else:
        tags = str(tags_raw).lower()

    searchable = f"{title} {body} {tags}"
    # Token overlap must compare tokens, not substrings: `token in searchable`
    # counted "go" as a hit inside "golang" and "algorithms". Substring intent
    # is already covered by the dedicated title/body substring factor below.
    page_tokens = _tokenize(searchable)
    overlap_count = len(query_tokens & page_tokens)
    # IDF 加权 token overlap（CV from TreeSearch compute_term_overlap）：
    # 稀有 term 命中权重高，加在原 count*0.3 之上作 bonus。
    idf_overlap = compute_term_overlap(searchable, list(query_tokens), idf)
    token_overlap = overlap_count * 0.3 + idf_overlap * 1.0
    if overlap_count:
        reasons.append(f"token-overlap:{overlap_count}")
    if idf_overlap > 0:
        reasons.append(f"idf-overlap:{idf_overlap:.2f}")

    title_substring = 0.0
    body_substring = 0.0
    # Title term boost（CV from TreeSearch check_title_match）：query term
    # 逐个命中 title，每个 +0.3。整 query substring（下）是更强的 1.0。
    title_terms_hit = sum(1 for t in query_tokens if t in title)
    title_term_boost = title_terms_hit * 0.3
    if title_terms_hit:
        reasons.append(f"title-terms:{title_terms_hit}")
    if query_lower and len(query_lower) > 3:
        if query_lower in title:
            title_substring = 1.0
            reasons.append("title-substring")
        if query_lower in body:
            body_substring = 0.5
            reasons.append("body-substring")

    topic_trace = 0.0
    if topic_id is not None:
        traces = item.get("traces") or []
        for trace in traces:
            if trace.get("kind") == "discuss" and str(trace.get("id")) == str(topic_id):
                topic_trace = 2.0
                reasons.append(f"topic-trace:{topic_id}")
                break

    base = token_overlap + title_substring + title_term_boost + body_substring + topic_trace
    has_query = bool(query_lower.strip() or query_tokens or topic_id is not None)
    wiki_type = item.get("type", item.get("category", "concept"))
    type_boost = {
        "anti-pattern": 1.5,
        "strategy": 0.8,
        "concept": 0.6,
    }
    type_multiplier = type_boost.get(wiki_type, 0.5)
    # 通用页降权（学习迁移自 TreeSearch is_generic_section）：index/overview 等
    # 目录性页 ×0.5，避免淹没具体策略页。
    generic_demotion = 0.5 if is_generic_page(item.get("title", "")) else 1.0
    typed_base = base * type_multiplier * generic_demotion
    if generic_demotion < 1.0:
        reasons.append("generic-page:demoted")

    components: dict[str, Any] = {
        "token_overlap_count": overlap_count,
        "token_overlap": token_overlap,
        "title_substring": title_substring,
        "title_term_boost": title_term_boost,
        "idf_overlap": idf_overlap,
        "body_substring": body_substring,
        "topic_trace": topic_trace,
        "base_score": base,
        "type_multiplier": type_multiplier,
        "generic_demotion": generic_demotion,
        "typed_base": typed_base,
        "review_decision": 0.0,
        "review_failure": 0.0,
        "memory_score": 0.0,
        "goal_area": 0.0,
        "goal_keyword": 0.0,
        "final_score": 0.0,
        "reasons": reasons,
        "goal_matches": [],
    }

    if has_query and base == 0:
        reasons.append("filtered:no-query-match")
        return components

    relevance = typed_base
    if base:
        reasons.append(f"type:{wiki_type}x{type_multiplier:g}")

    review = item.get("review")
    if review and isinstance(review, dict):
        if review.get("decision_correct") is False:
            components["review_decision"] = 2.0
            relevance += components["review_decision"]
            reasons.append("review:incorrect-decision")
        if review.get("outcome") == "failure":
            components["review_failure"] = 1.0
            relevance += components["review_failure"]
            reasons.append("review:failure")

    score = float(item.get("score", 0) or 0)
    components["memory_score"] = score * 0.5
    relevance += components["memory_score"]
    if components["memory_score"]:
        reasons.append("memory-score")

    goal_domains: set[str] = goal_context.get("domains", set())
    goal_keywords: set[str] = goal_context.get("keywords", set())
    page_area = str(item.get("area", "")).lower().strip()
    area_match = bool(goal_domains and page_area in goal_domains)
    keyword_matches = sorted(kw for kw in goal_keywords if kw in searchable)

    if relevance > 0 and area_match:
        components["goal_area"] = 0.8
        relevance += components["goal_area"]
        reasons.append(f"goal-area:{page_area}")
    if relevance > 0 and keyword_matches:
        components["goal_keyword"] = 0.4
        relevance += components["goal_keyword"]
        reasons.append(f"goal-keyword:{','.join(keyword_matches)}")

    goal_matches: list[dict[str, Any]] = []
    for goal in goal_context.get("goals", []):
        matched_keywords = sorted(
            keyword for keyword in goal.get("keywords", set()) if keyword in searchable
        )
        matched_area = bool(page_area and page_area in goal.get("domains", set()))
        if matched_area or matched_keywords:
            goal_matches.append({
                "slug": goal.get("slug", ""),
                "area": matched_area,
                "keywords": matched_keywords,
            })

    components["goal_matches"] = goal_matches
    components["final_score"] = relevance
    return components


def _matches_query(content: str, query_lower: str, query_tokens: set[str]) -> bool:
    """Decide whether an episodic file is a candidate at all.

    Token comparison is on tokens, not substrings: `token in content` let "go"
    match "algorithms" and pulled unrelated files into the agent's context. The
    whole-query substring branch is deliberate — it catches exact phrases.
    """
    if query_lower and len(query_lower) > 3 and query_lower in content:
        return True
    if query_tokens:
        return bool(query_tokens & _tokenize(content))
    return bool(query_lower and query_lower in content)


def _freshness_score(file_path: Path) -> float:
    try:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
    except (OSError, ValueError):
        return 0.5
    days_old = max(0, (datetime.now(UTC) - mtime).days)
    return max(0.01, 1.0 * (0.95 ** days_old))
