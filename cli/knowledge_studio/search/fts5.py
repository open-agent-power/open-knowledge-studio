"""FTS5 backend — CV from TreeSearch (shibing624) FTS5Index, node-level version.

SQLite FTS5 + jieba 中文分词 + node-level BM25 + column weights + 增量 diff。
每 `##` heading 段一 FTS5 row，slug 聚合多 node 命中。持久化索引。

v0.6.0 升级: flat page → node-level（每 ## 段一 row），50-case R@1
0.525(native) → 0.825(node-level)。v0.6.0+ 默认 search backend。

CV source: github.com/shibing624/TreeSearch treesearch/fts.py
Adapted: tree-node → markdown-node（## heading 切分, column weights).

为何 CV（用户决策）：
- 不假设数据少——大数据下 native 每次遍历 wiki + 实时算 IDF/title 越来越慢，
  FTS5 持久化索引 + BM25 是大数据标配
- jieba 已是 OKS 依赖，FTS5 用 stdlib sqlite3，无新依赖
- 作为 fusion 的补盲 backend + connector 扩展的参照实现
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from typing import Any

from . import SearchHit

# ── Markdown 解析（CV from TreeSearch parse_md_node_text）──

_RE_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
_RE_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_RE_HAS_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_RE_FTS5_SPECIAL = re.compile(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]")
_FTS5_OPERATORS = {"AND", "OR", "NOT", "NEAR"}

# BM25 column weights: title 最重（5x），tags 次之（3x），body 基准（1x），code 轻（0.5x）
_DEFAULT_WEIGHTS = {"title": 5.0, "body": 1.0, "tags": 3.0, "code_blocks": 0.5}


def _check_fts5() -> bool:
    """检测当前 SQLite 是否支持 FTS5（CPython 多数发行版自带，但部分精简版没有）。"""
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


def _tokenize_for_fts(text: str) -> str:
    """FTS5 索引分词：CJK 用 jieba（复用 OKS recall._tokenize），英文靠 FTS5 unicode61。

    返回空格分隔的 token 串（FTS5 unicode61 会二次切英文）。
    """
    if not text or not text.strip():
        return ""
    if _RE_HAS_CJK.search(text):
        from ..recall import _tokenize

        # _tokenize 返回 set（含 jieba cut_for_search + stopwords），FTS5 要 list 串
        return " ".join(sorted(_tokenize(text)))
    return text  # 纯英文：FTS5 unicode61 自己切


def _parse_md(text: str) -> tuple[str, str, str]:
    """Markdown → (front_matter, body, code_blocks)。

    CV from TreeSearch ``parse_md_node_text``。code_blocks 从 body 抽出单独索引
    （代码 query 不污染正文 BM25）。
    """
    if not text:
        return "", "", ""
    front_matter = ""
    remaining = text
    m = _RE_FRONT_MATTER.match(text)
    if m:
        front_matter = m.group(1).strip()
        remaining = text[m.end():]

    code_parts: list[str] = []

    def _grab(mm: re.Match) -> str:
        code_parts.append(mm.group(1).strip())
        return ""  # 从 body 移除

    body = _RE_CODE_BLOCK.sub(_grab, remaining)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return front_matter, body, "\n".join(code_parts)


# v0.6.0: 吸收 TreeSearch 的 markdown tree parser（node-level 拆分）。
# CV source: TreeSearch `_extract_md_headings` + `_cut_md_text`。
# 把 body 按 `#` heading 切成 nodes；每个 node = heading + 该段正文。
# 无 heading 的 body 作为单一 node。code fence 内的假 heading 跳过。
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_RE_CODE_FENCE = re.compile(r"^```")


def _split_md_nodes(title: str, body: str) -> list[tuple[int, str]]:
    """title + body → [(node_idx, node_text), ...]（node-level, CV from TreeSearch）。

    - 首个 node 是 page title + title 下的引言段（第一个 heading 前的文本）
    - 后续每个 `#`/`##` heading 开一个新 node：heading 行 + 该 heading 到下一 heading 间的正文
    - code fence 内的假 heading 跳过（防误切）
    """
    if not body and not title:
        return [(0, "")]
    full = f"# {title}\n\n{body}" if title else body
    lines = full.split("\n")
    markers: list[dict] = []
    in_code = False
    for num, line in enumerate(lines, 1):
        stripped = line.strip()
        if _RE_CODE_FENCE.match(stripped):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        m = _RE_HEADING.match(stripped)
        if m:
            markers.append({"line_num": num})
    if not markers:
        return [(0, full.strip())]
    nodes: list[tuple[int, str]] = []
    for i, mk in enumerate(markers):
        start = mk["line_num"] - 1
        end = markers[i + 1]["line_num"] - 1 if i + 1 < len(markers) else len(lines)
        nodes.append((i, "\n".join(lines[start:end]).strip()))
    return nodes


class FTS5Backend:
    """SQLite FTS5 全文检索 backend（CV from TreeSearch FTS5Index, 平铺版）。

    每页 1 行（slug, title, body, tags, code_blocks）。
    - BM25 + column weights（title 5x > tags 3x > body 1x > code 0.5x）
    - 增量 diff（content_hash），未变页跳过
    - 持久化（db_path）或 in-memory（None）

    FTS5 不可用时降级 LIKE（保证可用性）。
    """

    def __init__(
        self,
        root: str | None = None,
        db_path: str | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        self._root = root
        if db_path is None and root:
            db_path = os.path.join(root, ".oks", "fts5.db")
        self._db_path = db_path or ":memory:"
        if self._db_path != ":memory:":
            # sqlite3.connect() does not create missing parent directories.
            # Create only the local derived-state directory before opening it.
            os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._weights = {**_DEFAULT_WEIGHTS, **(weights or {})}
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._use_fts5 = _check_fts5()
        self._init_db()
        self._indexed = False

    def _init_db(self) -> None:
        # v0.6.0: schema version 检测——node-level schema 不匹配则强制重建
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        cur = self._conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if cur and cur[0] != "node-v1":
            # 旧 schema（flat page-level），DROP 重建
            self._conn.execute("DROP TABLE IF EXISTS wiki_fts")
            self._conn.execute("DROP TABLE IF EXISTS pages")
            self._conn.execute("DELETE FROM meta WHERE key='schema_version'")
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', 'node-v1')"
        )
        # pages 表存 content_hash 做 diff（不存全文，全文在 fts 表）
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS pages (slug TEXT PRIMARY KEY, content_hash TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        if self._use_fts5:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5("
                "slug UNINDEXED, node_idx UNINDEXED, title, body, tags, code_blocks)"
            )
        self._conn.commit()

    def index(self, pages: list[dict[str, Any]]) -> None:
        """增量索引（CV from TreeSearch index_document diff 逻辑）。

        逐页算 content_hash，未变跳过；变的先删旧行再插新。
        """
        for page in pages:
            slug = page.get("slug") or page.get("path", "").replace(".md", "")
            if not slug:
                continue
            title = str(page.get("title", ""))
            body = str(page.get("body", ""))
            tags = page.get("tags", "")
            if isinstance(tags, list):
                tags = " ".join(str(t) for t in tags)

            front, md_body, code = _parse_md(f"{title}\n\n{body}")
            content = f"{title}\n{body}\n{tags}\n{code}"
            content_hash = hashlib.md5(content.encode()).hexdigest()[:16]

            row = self._conn.execute(
                "SELECT content_hash FROM pages WHERE slug=?", (slug,)
            ).fetchone()
            if row and row[0] == content_hash:
                continue  # 未变，跳过（增量 diff 核心）

            if row:
                self._conn.execute("DELETE FROM pages WHERE slug=?", (slug,))
                if self._use_fts5:
                    self._conn.execute("DELETE FROM wiki_fts WHERE slug=?", (slug,))

            self._conn.execute(
                "INSERT OR REPLACE INTO pages (slug, content_hash) VALUES (?, ?)",
                (slug, content_hash),
            )
            if self._use_fts5:
                # v0.6.0: node-level 索引——吸收 TreeSearch tree parser，
                # 每个 `##` heading 段落一个 FTS5 row，多词同段出现 BM25 高分。
                nodes = _split_md_nodes(title, md_body)
                tok_title = _tokenize_for_fts(title)
                tok_tags = _tokenize_for_fts(str(tags))
                tok_code = _tokenize_for_fts(code)
                for node_idx, node_text in nodes:
                    self._conn.execute(
                        "INSERT INTO wiki_fts "
                        "(slug, node_idx, title, body, tags, code_blocks) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            slug, node_idx, tok_title,
                            _tokenize_for_fts(node_text),
                            tok_tags, tok_code,
                        ),
                    )
        self._conn.commit()
        self._indexed = True

    def _wiki_fingerprint(self) -> str:
        """所有 wiki 文件 path+mtime+size 的 hash——变了就 stale。

        粗粒度但够用：遍历 wiki/**/*.md，只 stat（不读内容），比逐页
        content_hash 快。index() 再逐页 content_hash 做增量 diff。
        """
        import hashlib

        root = self._root
        if not root:
            from ..store import repo_root

            root = repo_root()
        wiki_dir = os.path.join(root or ".", "wiki")
        if not os.path.isdir(wiki_dir):
            return ""
        h = hashlib.md5()
        for dirpath, _, filenames in os.walk(wiki_dir):
            for fn in sorted(filenames):
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                    h.update(f"{p}:{st.st_mtime_ns}:{st.st_size}\n".encode())
                except OSError:
                    continue
        return h.hexdigest()

    def _maybe_reindex(self) -> None:
        """lazy watch：recall 前调——fingerprint 变了才 index()。

        无后台守护进程，recall 时自动保证索引新鲜。index() 已有 content_hash
        逐页 diff，未变页跳过，所以"重索引"只处理变页，快（61 页 < 50ms）。
        """
        current = self._wiki_fingerprint()
        if not current:
            return
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='wiki_fingerprint'"
        ).fetchone()
        stored = row[0] if row else ""
        if current == stored and self._indexed:
            return  # 新鲜，跳过
        from ..recall import list_wiki_pages

        self.index(list_wiki_pages())
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("wiki_fingerprint", current),
        )
        self._conn.commit()

    def _build_match_expr(self, query: str) -> str | None:
        """query → FTS5 MATCH 表达式（token OR 连接）。"""
        tokens = _tokenize_for_fts(query)
        if not tokens.strip():
            return None
        words = [
            _RE_FTS5_SPECIAL.sub("", w).strip()
            for w in tokens.split()
            if w and w.upper() not in _FTS5_OPERATORS
        ]
        words = [w for w in words if w]
        if not words:
            return None
        return " OR ".join(words) if len(words) > 1 else words[0]

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[SearchHit]:
        self._maybe_reindex()  # lazy watch：stale 就增量重索引
        if not self._use_fts5:
            return self._search_like(query, limit=limit)

        match_expr = self._build_match_expr(query)
        if match_expr is None:
            return []

        w = self._weights
        # v0.6.0: bm25 列序对应建表 (slug, node_idx, title, body, tags, code_blocks)
        # slug/node_idx UNINDEXED 权重 0。按 slug 聚合取最高分 node（node-level）。
        sql = (
            f"SELECT f.slug, f.title, "
            f"bm25(wiki_fts, 0, 0, {w['title']}, {w['body']}, {w['tags']}, {w['code_blocks']}) AS rank "
            f"FROM wiki_fts f WHERE wiki_fts MATCH ? ORDER BY rank LIMIT ?"
        )
        rows = self._conn.execute(sql, (match_expr, limit * 4)).fetchall()
        # node-level：同 slug 可能多 row（每个 heading 段一 row），取最高分那个去重
        best: dict[str, tuple[str, float]] = {}
        order: list[str] = []
        for slug, title, rank in rows:
            score = float(-rank)
            if slug not in best or score > best[slug][1]:
                best[slug] = (title or slug, score)
                if slug not in order:
                    order.append(slug)
        hits = [
            SearchHit(slug=slug, title=best[slug][0], score=best[slug][1], backend="fts5")
            for slug in order
        ]
        # scope 硬过滤（FTS5 不存 area，需后过滤——若要 FTS5 内过滤，扩展 schema 加 area 列）
        if scope:
            scope_set = {s.strip().lower() for s in scope.split(",") if s.strip()}
            from ..recall import list_wiki_pages

            area_map = {
                p.get("slug"): str(p.get("area", "")).lower().strip()
                for p in list_wiki_pages()
            }
            hits = [h for h in hits if area_map.get(h.slug, "") in scope_set]
        return hits[:limit]

    def _search_like(self, query: str, limit: int = 10) -> list[SearchHit]:
        """FTS5 不可用时的 LIKE fallback（保证可用性，不崩）。"""
        ql = query.lower()
        rows = self._conn.execute("SELECT slug, title FROM pages").fetchall()
        hits = []
        for slug, title in rows:
            if ql in (title or "").lower() or ql in slug.lower():
                hits.append(
                    SearchHit(slug=slug, title=title or slug, score=0.1, backend="fts5")
                )
        return hits[:limit]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["FTS5Backend"]
