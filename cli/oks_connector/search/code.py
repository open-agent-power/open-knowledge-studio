"""AST-based Python code search backend — built-in connector.

注册为 entry_points(group="oks_search_backend", name="code")。
用 ast 解析 .py 文件，function/class 粒度召回。Complementary to native/fts5
（page-level wiki），code backend 搜 raw/ + repo .py（function-level）。

返回 _CodeSearchHit（字段同 oks SearchHit: slug/title/score/backend/extra），
recall 引擎 duck-typing 访问，不强 import oks 主包——避免循环依赖。

第三方写自己的 backend（如 codegraph）：独立包注册同名 entry_points 即可，
不需合并到这里。本包提供 code 作为内置示例 + 实用 backend。
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Any

_SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".oks",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".eggs",
}

_RE_WORD = re.compile(r"\w+")


@dataclass
class _CodeSearchHit:
    """Duck-type 兼容 oks SearchHit（同字段名，不强 import）。"""

    slug: str
    title: str
    score: float
    backend: str = "code"
    extra: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> set[str]:
    """Simple tokenizer: lowercase words + snake_case split.

    recall_engine → {recall, engine}. No jieba dependency (connector stays
    lightweight); code identifiers are mostly ASCII snake_case.
    """
    tokens: set[str] = set()
    for w in _RE_WORD.findall(text.lower()):
        for part in re.split(r"[_\-.]", w):
            if len(part) >= 2:
                tokens.add(part)
    return tokens


class CodeSearchBackend:
    """AST-based Python code search backend.

    ``index()`` scans ``code_dirs`` (default ``["raw"]``) for ``.py`` files,
    AST-parses each, extracts ``FunctionDef`` / ``AsyncFunctionDef`` /
    ``ClassDef`` (skips private/dunder), stores name + docstring + body.

    ``search()`` token-overlaps the query against function/class names +
    docstrings + bodies. Name hits weight 5x body hits (you usually search
    by function/class name, not by body content).
    """

    def __init__(
        self,
        root: str | None = None,
        code_dirs: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._root = root or os.getcwd()
        self._code_dirs = code_dirs or ["raw"]
        self._index: list[tuple[str, str, str, str, str, str]] = []
        self._indexed = False

    def index(self, pages: list[dict[str, Any]]) -> None:
        """Scan code_dirs for .py, AST-parse, build function/class index.

        The ``pages`` arg (wiki markdown from OKS) is ignored — code backend
        indexes source files, not wiki.
        """
        self._index = []
        seen_roots: set[str] = set()
        seen_files: set[str] = set()
        for d in self._code_dirs:
            base = os.path.join(self._root, d) if not os.path.isabs(d) else d
            if not os.path.isdir(base) or base in seen_roots:
                continue
            seen_roots.add(base)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [
                    dn for dn in dirnames
                    if dn not in _SKIP_DIRS and not dn.endswith(".egg-info")
                ]
                for fn in filenames:
                    if not fn.endswith(".py"):
                        continue
                    fp = os.path.normpath(os.path.join(dirpath, fn))
                    if fp in seen_files:
                        continue
                    seen_files.add(fp)
                    self._index_py(fp)
        self._indexed = True

    def _index_py(self, fp: str) -> None:
        try:
            src = open(fp, encoding="utf-8").read()
            tree = ast.parse(src)
        except Exception:
            return
        try:
            rel = os.path.relpath(fp, self._root)
        except ValueError:
            rel = fp
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if name.startswith("_"):
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            doc = ast.get_docstring(node) or ""
            try:
                body = ast.get_source_segment(src, node) or ""
            except Exception:
                body = ""
            end = getattr(node, "end_lineno", node.lineno)
            self._index.append(
                (rel, name, kind, doc, body, f"{node.lineno}-{end}")
            )

    def search(
        self, query: str, *, limit: int = 10, scope: str | None = None, **kwargs: Any
    ) -> list[_CodeSearchHit]:
        if not self._indexed:
            self.index([])
        if not self._index:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scored: list[tuple[float, str, str, str, str, str, int]] = []
        for rel, name, kind, doc, body, lines in self._index:
            name_tokens = _tokenize(name)
            name_hit = len(q_tokens & name_tokens)
            text_tokens = _tokenize(f"{doc} {body}")
            body_hit = len(q_tokens & text_tokens)
            total = name_hit + body_hit
            if total == 0:
                continue
            score = name_hit * 1.0 + body_hit * 0.2
            scored.append((score, rel, name, kind, doc, lines, total))

        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        return [
            _CodeSearchHit(
                slug=f"{rel}::{name}",
                title=f"{kind} {name} ({rel}:{lines})",
                score=s,
                backend="code",
                extra={
                    "kind": kind, "file": rel, "lines": lines,
                    "doc": doc[:200], "hit_count": hit,
                },
            )
            for s, rel, name, kind, doc, lines, hit in scored[:limit]
        ]


__all__ = ["CodeSearchBackend", "_CodeSearchHit"]
