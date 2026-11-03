"""Fusion backend — fts5 主召回 + native 6+1 归一化 re-rank。

v0.6.0 重构（之前 native 主 + fts5 补盲，native 54% 拖累 fts5 96%）。
现在 fts5 作主召回（精度高），native 6+1 因子作归一化加权 re-rank，
保留 oks 灵魂又不丢精度。

50-case 消融实测（v0.6.2）：
- fts5 alone: R@1=0.825, MRR=0.907（默认最优）
- fusion (0.7 fts5 + 0.3 native): R@1=0.805, MRR=0.900
- → fusion 不如纯 fts5，证明灵魂因子须在注入层，召回层 re-rank 是负优化
- fusion 保留作向后兼容 + connector 参照 + --search-backend fusion 可复现
"""
from __future__ import annotations

from typing import Any

from . import SearchHit


class FusionBackend:
    """fts5 主召回 + native 6+1 归一化 re-rank。

    - fts5 取 2*limit 候选作主召回
    - native 取同量候选，slug → score 映射
    - 各归一化到 0-1，加权 0.7*fts5 + 0.3*native 重排
    - fts5 空则退回纯 native
    """

    def __init__(
        self,
        root: str | None = None,
        native_top: int = 3,
        fts5_supplement: int = 2,
        **kwargs: Any,
    ) -> None:
        from .native import NativeBackend
        from .fts5 import FTS5Backend

        # native_top / fts5_supplement 是 v0.6.0 前 native 主 + fts5 补盲
        # 策略的参数，v0.6.0 重构后 re-rank 不再用到，保留签名向后兼容。
        self._native = NativeBackend()
        self._fts5 = FTS5Backend(root=root, **{
            k: v for k, v in kwargs.items() if k in ("db_path", "weights")
        })
        self._native_top = native_top
        self._fts5_supplement = fts5_supplement

    def index(self, pages: list[dict[str, Any]]) -> None:
        """fts5 预索引；native 实时计算。"""
        self._native.index(pages)
        self._fts5.index(pages)

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[SearchHit]:
        fts5_hits = self._fts5.search(query, limit=limit * 2, scope=scope, **kwargs)
        if not fts5_hits:
            return self._native.search(query, limit=limit, scope=scope, **kwargs)
        native_hits = self._native.search(
            query, limit=limit * 2, scope=scope, **kwargs
        )
        native_map = {h.slug: h.score for h in native_hits}
        fts5_max = max((h.score for h in fts5_hits), default=1.0) or 1.0
        native_max = max(native_map.values(), default=1.0) or 1.0
        for h in fts5_hits:
            f_norm = h.score / fts5_max  # 0-1
            n_norm = native_map.get(h.slug, 0) / native_max if native_map else 0
            h.score = 0.7 * f_norm + 0.3 * n_norm
            h.backend = "fusion"
        fts5_hits.sort(key=lambda h: -h.score)
        return fts5_hits[:limit]


__all__ = ["FusionBackend"]
