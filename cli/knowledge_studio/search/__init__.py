"""OKS 可插拔 search backend。

内置 backend：
- **fts5**（默认, v0.6.0+）：SQLite FTS5 + node-level BM25 + 持久化索引 +
  增量 diff。50-case 实测 R@1=0.825, p50=93ms（默认最优）
- **native**（legacy, v0.6.0 前默认）：6+1 因子 + jieba + IDF + title boost，
  无新依赖，实时遍历。R@1=0.525，--explain 可见七因子逐项分
- **fusion**：fts5 主召回 + native 归一化 re-rank (0.7 fts5 + 0.3 native)。
  R@1=0.805（实测不如纯 fts5，证明灵魂因子须在注入层）

connector 扩展点（关键架构决策）：
第三方可通过 ``entry_points(group="oks_search_backend")`` 注册新 backend
（如 embedding 语义召回 / 代码搜索 ast_parser / 其他开源 search 框架），
recall 切 ``search_backend`` 配置即用，OKS 核心无需改。

v0.6.3: embedding fallback — fts5 召回空/不足时切 embedding 补充
（``embedding_fallback: true`` 开启，默认关）。

config: ``search_backend: fts5 | native | fusion | <connector-name>``
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SearchHit:
    """A single search result from any backend."""

    slug: str
    title: str
    score: float
    abstract: str | None = None  # L0 零 read: fts5 返 SQLite abstract (CV OpenViking tiers L0)
    backend: str = "native"
    extra: dict[str, Any] = field(default_factory=dict)


class SearchBackend(Protocol):
    """可插拔 search backend 接口。

    第三方实现只需满足：
    - ``search(query, *, limit, scope, **kwargs) -> list[SearchHit]``
    - ``index(pages)`` 预索引（native 可 no-op，fts5/embedding 需要）

    scope 是 area 硬过滤（comma-separated），不设默认全部。
    """

    def index(self, pages: list[dict[str, Any]]) -> None:
        """索引 wiki pages。native 实时计算可 no-op；fts5/embedding 预索引。"""
        ...

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[SearchHit]:
        """返回 ranked hits。score 越高越相关。"""
        ...


def get_backend(name: str = "fts5", root: str | None = None, **kwargs: Any) -> SearchBackend:
    """按名字取 backend。

    native / fts5 / fusion 内置；其他名字查 connector entry_points
    (group="oks_search_backend")，找不到则 ValueError。
    """
    n = (name or "fts5").lower()
    if n == "native":
        from .native import NativeBackend

        return NativeBackend()
    if n == "fts5":
        from .fts5 import FTS5Backend

        return FTS5Backend(root=root, **kwargs)
    if n == "fusion":
        from .fusion import FusionBackend

        return FusionBackend(root=root, **kwargs)
    # connector 扩展点：第三方 entry_points
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="oks_search_backend"):
            if ep.name == n:
                return ep.load()(root=root, **kwargs)
    except Exception:
        pass
    raise ValueError(
        f"unknown search backend: {name!r}. available: native, fts5, fusion "
        f"(+ connector entry_points group='oks_search_backend')"
    )


__all__ = ["SearchHit", "SearchBackend", "get_backend"]
