"""Semantic embedding search backend — built-in connector.

注册为 entry_points(group="oks_search_backend", name="embedding")。
用 sentence-transformers 本地模型（不调远程 API，尊重 OKS P4 边界）embed
wiki pages + query，cosine similarity 召回。解决 fts5 BM25 无法跨越的
同义词鸿沟（query "自进化知识平台" → wiki "ai-native-strategy" 正文
不含 "自进化" 也不含 "知识平台"）。

返回 _EmbeddingHit（字段同 oks SearchHit: slug/title/score/backend/extra），
recall 引擎 duck-typing 访问，不强 import oks 主包——避免循环依赖。

optional 依赖：sentence-transformers + numpy。装 open-knowledge-studio[embedding]
启用；未装时 index/search 抛友好 ImportError。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# v0.5.0: 切 bge-small-zh-v1.5（BAAI 中文优化，512 维）替代 MiniLM（英文）。
# CV from OpenViking local_embedders.py —— MiniLM 中文 R@1 反低 20 点，bge-small-zh 是中文 SOTA。
# bge-small-zh query 需加 instruction 前缀（passage 不加），见 BGE_ZH_QUERY_INSTRUCTION。
DEFAULT_MODEL = os.environ.get(
    "OKS_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"
)
# bge-small-zh 官方推荐 query 前缀（CV from OpenViking DEFAULT_BGE_ZH_QUERY_INSTRUCTION）。
# 仅 query 加，document/passage 不加（bge 不对称设计）。
BGE_ZH_QUERY_INSTRUCTION = os.environ.get(
    "OKS_BGE_QUERY_INSTRUCTION", "为这个句子生成表示以用于检索相关文章："
)


@dataclass
class _EmbeddingHit:
    """duck-typed SearchHit — recall.py 按 .slug/.score 访问，不强 import。"""
    slug: str
    title: str
    score: float
    backend: str = "embedding"
    extra: dict[str, Any] = field(default_factory=dict)


def _page_text(page: dict[str, Any]) -> str:
    """title + body + tags 拼接（frontmatter 已 parse）。截 4000 字控成本。"""
    parts = [page.get("title", "")]
    body = page.get("body") or page.get("content") or ""
    if isinstance(body, str):
        parts.append(body)
    tags = page.get("tags") or []
    if isinstance(tags, list):
        parts.append(" ".join(str(t) for t in tags))
    return "\n".join(p for p in parts if p)[:4000]


class EmbeddingBackend:
    """语义 embedding 召回 backend。

    index(): 每页 embed 一次，持久化 vectors + slug + content_hash 到
    .oks/embeddings.npz。content_hash 增量——未变页跳过 re-embed。
    search(): query embed → cosine similarity（vectors 已 L2 归一）→ top-k。
    scope: area 硬过滤（slug 首段，如 computing/... → area=computing）。
    """

    def __init__(self, root: str | None = None, **kwargs: Any) -> None:
        self.root = Path(root) if root else Path.cwd()
        self._model = None
        self._vectors = None  # np.ndarray (N, dim)
        self._slugs: list[str] = []
        self._hashes: dict[str, str] = {}
        self._db_path = self.root / ".oks" / "embeddings.npz"

    # ---- model ----
    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "embedding backend 需 sentence-transformers。装："
                    "pip install 'open-knowledge-studio[embedding]'"
                ) from e
            # 支持本地路径（绕网络）：OKS_EMBEDDING_MODEL 指向已下载模型目录时
            # 直接加载，不查 HF hub。否则按模型名从 HF 加载。
            from pathlib import Path
            model_spec = DEFAULT_MODEL
            local_path = Path(model_spec)
            if local_path.exists() and local_path.is_dir():
                model_spec = str(local_path)
            self._model = SentenceTransformer(model_spec)
        return self._model

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    # ---- SearchBackend protocol ----
    def index(self, pages: list[dict[str, Any]]) -> None:
        if not pages:
            return
        # 增量：load existing index
        if self._db_path.exists() and self._vectors is None:
            self._load_persisted()
        model = self._load_model()

        new_texts: list[str] = []
        new_slugs: list[str] = []
        for p in pages:
            slug = p.get("slug") or p.get("id") or ""
            if not slug:
                continue
            text = _page_text(p)
            ch = self._content_hash(text)
            if self._hashes.get(slug) == ch:
                continue  # 未变，跳过
            new_texts.append(text)
            new_slugs.append(slug)
            self._hashes[slug] = ch

        if not new_texts:
            self._persist()
            return

        new_vecs = model.encode(
            new_texts, normalize_embeddings=True, show_progress_bar=False
        )
        import numpy as np
        new_vecs = np.asarray(new_vecs, dtype=np.float32)

        if self._vectors is None or len(self._vectors) == 0:
            self._vectors = new_vecs
            self._slugs = list(new_slugs)
        else:
            existing = {s: i for i, s in enumerate(self._slugs)}
            for slug, vec in zip(new_slugs, new_vecs):
                if slug in existing:
                    self._vectors[existing[slug]] = vec
                else:
                    self._slugs.append(slug)
                    self._vectors = (
                        import_numpy_vstack(self._vectors, vec)
                    )
        self._persist()

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[_EmbeddingHit]:
        import numpy as np
        if self._vectors is None or len(self._vectors) == 0:
            self._lazy_index_from_wiki()
        if self._vectors is None or len(self._vectors) == 0:
            return []

        model = self._load_model()
        # bge-small-zh: query 加 instruction 前缀（document 不加，非对称）
        q_text = (
            BGE_ZH_QUERY_INSTRUCTION + query
            if "bge" in DEFAULT_MODEL.lower()
            else query
        )
        qvec = model.encode([q_text], normalize_embeddings=True, show_progress_bar=False)
        qvec = np.asarray(qvec[0], dtype=np.float32)
        scores = self._vectors @ qvec  # cosine（已 L2 归一）

        scope_areas = (
            {s.strip().lower() for s in scope.split(",") if s.strip()} if scope else set()
        )
        ranked: list[tuple[int, float, str]] = []
        for i, score in enumerate(scores):
            slug = self._slugs[i]
            if scope_areas:
                area = slug.split("/")[0].lower() if "/" in slug else ""
                if area not in scope_areas:
                    continue
            ranked.append((i, float(score), slug))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [
            _EmbeddingHit(
                slug=slug,
                title=slug.rsplit("/", 1)[-1],
                score=round(score, 4),
                backend="embedding",
            )
            for _, score, slug in ranked[:limit]
        ]

    # ---- helpers ----
    def _load_persisted(self) -> None:
        import numpy as np
        if not self._db_path.exists():
            return
        data = np.load(self._db_path, allow_pickle=True)
        self._slugs = list(data["slugs"])
        self._hashes = {s: h for s, h in zip(self._slugs, data["hashes"])}
        self._vectors = data["vectors"]

    def _persist(self) -> None:
        import numpy as np
        if self._vectors is None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        hashes_arr = np.array([self._hashes.get(s, "") for s in self._slugs])
        np.savez(
            self._db_path,
            slugs=np.array(self._slugs),
            hashes=hashes_arr,
            vectors=self._vectors,
        )

    def _lazy_index_from_wiki(self) -> None:
        """无持久化索引时，读 wiki/ 建索引。

        list_wiki_pages() 用 wiki_dir()（从 OKS_ROOT env / cwd），
        不接 root 参数——OKS 调 backend 时 cwd 已是 knowledge root。
        """
        try:
            from knowledge_studio.store import list_wiki_pages
        except Exception:
            return
        try:
            pages = list_wiki_pages()
            if pages:
                self.index(pages)
        except Exception:
            pass


def import_numpy_vstack(base, vec):
    import numpy as np
    return np.vstack([base, vec[None, :]])
