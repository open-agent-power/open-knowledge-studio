"""Native backend — OKS legacy 召回（6+1 因子 + jieba + IDF + title boost）。

v0.6.0 前默认召回；v0.6.0+ 默认改 fts5（node-level BM25, R@1=0.825）。
native 保留作向后兼容 + --explain 七因子逐项分可见 + fusion re-rank 用。
包装 ``recall_knowledge()``，无新依赖，实时遍历 wiki/。
"""
from __future__ import annotations

from typing import Any

from . import SearchHit

# Pure retrieval inputs, including the current request's optional snapshots.
_RECALL_KWARGS = ("goal", "goal_boost", "type_filter", "explain", "topic_id",
                  "candidate_pages", "params", "goal_context")


class NativeBackend:
    """包装 ``recall_knowledge()`` — OKS 6+1 召回。

    无预索引（实时计算），无新依赖。小库（< 1000 页）足够快。
    """

    def index(self, pages: list[dict[str, Any]]) -> None:
        """native 实时计算，无需预索引。"""
        return None

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[SearchHit]:
        from ..recall import recall_knowledge

        recall_kwargs = {k: v for k, v in kwargs.items() if k in _RECALL_KWARGS}
        hits = recall_knowledge(
            query=query,
            limit=limit,
            scope=scope,
            search_backend="native",
            **recall_kwargs,
        )
        return [
            SearchHit(
                slug=h["slug"],
                title=h.get("title", h["slug"]),
                score=h.get("relevance", 0.0),
                backend="native",
                extra={"confidence": h.get("confidence", 0.8)},
            )
            for h in hits
        ]


__all__ = ["NativeBackend"]
