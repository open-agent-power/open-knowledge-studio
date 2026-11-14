"""Read-only knowledge map projection over the curated Wiki.

The map answers one question at three zoom levels:

    level 1  knowledge domain   (frontmatter ``area``)
    level 2  knowledge cluster  (first frontmatter ``tag``)
    level 3  knowledge point    (one Markdown file in ``wiki/`` or ``drafts/``)

Everything is derived from real files. Nothing is invented:

* A relation edge comes from ``relations``, ``relates_to`` + ``relationship``,
  or a shared tag. Every edge carries provenance so the UI can show its source.
* Concept / Strategy / Anti-Strategy are **governance attributes** of an entry,
  never a taxonomy of the Wiki. Grouping is always by domain.
* Skill packaging state is derived from frontmatter and reported as such, with
  the derivation spelled out, because phase 1 has no install or publish path.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import tempfile
from urllib.parse import unquote, urlsplit
from datetime import datetime, timezone
from pathlib import Path

from knowledge_studio import document_metadata, draft_review, store, worker_knowledge
from knowledge_studio.document_metadata import TIME_KEYS
from knowledge_studio.knowledge_policy import is_source_material, DOMAIN_LABELS as CANONICAL_DOMAINS

SCHEMA = "mail.knowledge-map.v1"

#: Declared relation vocabulary, including A4 knowledge evolution. Unknown declarations are
#: preserved verbatim and flagged instead of being silently remapped.
#: ``color_key`` drives the legend/palette in the panel; it is stable per kind.
RELATION_TYPES = {
    "related": "相关",
    "depends_on": "依赖 / 前置",
    "supports": "支持 / 依据",
    "contrast": "对比 / 冲突",
    "applies_to": "应用于",
    "supersedes": "更新 / 替代",
    "enriches": "补充",
    "confirms": "确认",
    "challenges": "质疑",
}

#: Human labels for the knowledge domains seen in real knowledge bases. The
#: ``area`` value itself stays the machine key; the panel groups by ``area``.
DOMAIN_LABELS = {
    "collaboration": "团队与协作",
    "engineering": "研发工程",
    "knowledge": "知识管理",
    "ai": "Agent 与 AI",
    "product": "产品与设计",
    "process": "流程与规范",
    "tooling": "工具与平台",
    "research": "研究与调研",
    **CANONICAL_DOMAINS,
}

#: Cluster labels derive from frontmatter tags; these cover the tags we ship.
#: 这份表同时被 ``TAG_LABELS`` 复用，所以它兼顾两个职责：
#: ① 簇名（会渲染成左栏 / 面包屑的一级标题，漏一个就把机器键漏给读者）；
#: ② 知识点的标签行（``tag_label`` 对表外英文键返回空串，漏一个就静默少一行）。
#: 协议自身的词表必须全在此列，别再让 ``mail-protocol`` 这种键裸奔。
CLUSTER_LABELS = {
    "checkpoint": "人类检查点",
    "ui": "界面与交互",
    "anti-pattern": "反模式",
    "projection": "投影与有损",
    "protocol": "协作协议",
    "mail-protocol": "邮件协议",
    "view-layer": "视图层",
    "evidence": "证据与来源",
    "review": "审核与治理",
    "handoff": "交接",
    "memory": "记忆",
    "recall": "召回",
    "sync": "同步",
    "skill": "Skill 治理",
    "skill-governance": "Skill 治理",
    "human-in-the-loop": "人类介入",
    "session": "会话",
    "honesty": "如实呈现",
    "receipt": "回执",
    "identity": "身份",
    "wiki": "Wiki 条目",
}

#: Wiki 标签给读者看的人话名字。知识域与知识簇共用一套口径，
#: 合成一张表，避免同一个词在两处显示成两个名字。
TAG_LABELS = {**DOMAIN_LABELS, **CLUSTER_LABELS}


def tag_label(tag) -> str:
    """把标签翻成人话。推不出来的英文机器键不硬塞给读者，返回空串。"""
    text = str(tag or "").strip()
    if not text:
        return ""
    if text in TAG_LABELS:
        return TAG_LABELS[text]
    # 中文标签是人为写的，原样保留；纯英文残留多半是内部键，不展示。
    return text if any("\u4e00" <= ch <= "\u9fff" for ch in text) else ""


#: Governance knowledge types. They serve the Skills layer only.
GOVERNANCE_TYPES = {
    "concept": ("概念", "这是什么？"),
    "strategy": ("策略", "推荐怎么做？"),
    "anti-pattern": ("反策略", "哪些做法应该避免？"),
}

#: Phase 1 publishes no executable capability. This block is policy, not data.
SKILL_BOUNDARY = {
    "kind": "policy",
    "stage": "phase-1",
    "allowed": [
        "Skill 通过 wiki_refs 引用已审核知识，不复制知识正文",
        "只有通过 Human Review 的 Wiki 条目可以作为引用来源",
        "概念 / 策略 / 反策略只用于 Skills 治理，不作 Wiki 分类",
    ],
    "not_done": [
        "不自动安装 Skill",
        "不自动发布或更新 Skill Package",
        "不做 Marketplace、不做复杂依赖解析",
        "面板不做启用 / 停用：治理位只展示，不写盘",
    ],
    "next_gate": "Skill Candidate → Human Review → Skill Package 仍需人工判断。",
}


#: 「这个时间是从哪来的」——把内部字段名翻成维护者也能直接读懂的人话。
#: 每个 TIME_KEYS 成员都必须有名字，测试会盯着这张表不许漏。
TIME_SOURCE_LABELS = {
    "updated_at": "条目里记录的更新时间",
    "updated": "条目里记录的更新时间",
    "modified_at": "条目里记录的更新时间",
    "ingested_at": "收录进知识库的时间",
    "human_reviewed_at": "人工审核通过的时间",
    "created": "条目创建时间",
    "file_mtime": "文件最后修改时间",
}


def time_source_label(key) -> str:
    """时间来源的人话名字；表里没有的一律退成中性的「记录时间」，不外漏字段名。"""
    return TIME_SOURCE_LABELS.get(str(key or "").strip(), "记录时间")


def review_summary(meta: dict, kind: str) -> dict:
    """Describe recorded human review without inferring it from location/status."""
    reviewed_at = document_metadata.parse_time(meta.get("human_reviewed_at")) if kind == "wiki" else None
    reviewed = reviewed_at is not None
    state = "reviewed" if reviewed else ("unknown" if kind == "wiki" else "pending")
    return {
        "state": state,
        "label": {"reviewed": "已审核", "unknown": "审核记录未知", "pending": "待审核"}[state],
        "reviewed": reviewed,
        "human_reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
        "kind_label": (
            "已审核 Wiki" if reviewed else "Wiki · 审核记录未知"
        ) if kind == "wiki" else "Candidate 候选",
    }


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_title(meta: dict, body: str, path: Path, fallback: str) -> str:
    text = re.sub(r"\A\s*---\s*\n.*?\n---(?:\s*\n|$)", "", body, count=1, flags=re.S)
    if meta.get("title") or meta.get("name") or re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", text):
        return document_metadata.title(meta, text, path)
    for line in text.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"<[^>]+>|[-*_`~]+", line) or line.startswith(("[{", '{"')):
            continue
        return document_metadata.plain(line, 100)
    return fallback


def _relations(meta: dict) -> list[dict]:
    raw = meta.get("relations")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = [item.strip() for item in re.split(r"[,\n]", raw) if item.strip()]
    if not isinstance(raw, (list, tuple)):
        raw = []
    declarations = [(item, "frontmatter relations") for item in raw]
    if meta.get("relates_to") and meta.get("relationship"):
        declarations.append(({"target": meta["relates_to"], "type": meta["relationship"]},
                             "frontmatter relates_to + relationship"))
    relations = []
    for item, source in declarations:
        if isinstance(item, dict):
            kind = str(item.get("type") or item.get("relation") or "related").strip().lower()
            target = str(item.get("target") or item.get("to") or item.get("path") or "").strip()
            note = str(item.get("note") or "").strip()
        else:
            kind, _, target = str(item).partition(":")
            kind = kind.strip().lower() or "related"
            target = target.strip()
            note = ""
        if not target:
            continue
        known = kind in RELATION_TYPES
        relations.append({
            "type": kind if known else "unknown",
            "type_label": RELATION_TYPES.get(kind, "未识别关系"),
            "color_key": kind if known else "unknown",
            "raw_type": kind,
            "target": target,
            "note": note,
            "source": source,
            "source_label": "知识条目自己声明的关系",
            "resolved": False,
        })
    return relations


def _scan(root: Path, relative: str) -> list[Path]:
    base = root / relative
    if not base.is_dir():
        return []
    return sorted(
        path for path in base.rglob("*.md")
        if path.is_file() and not path.name.startswith("_")
    )


def _skill_state(meta: dict, kind: str, governance_type: str) -> dict:
    """Derive Skill packaging state, and say how it was derived."""
    if not worker_knowledge.is_skill(meta):
        return {"state": "none", "label": "未声明 Skill 身份", "source": "", "target": ""}
    package = meta.get("skill_package")
    package = package.strip() if isinstance(package, str) else ""
    if kind == "candidate":
        return {"state": "candidate", "label": "Skill 候选（待 Human Review）", "source": "明确 Skill 身份的候选草稿", "target": package}
    if package:
        return {"state": "packaged", "label": "已成包", "source": "frontmatter skill_package", "target": package}
    flagged = meta.get("skill_candidate")
    flagged = flagged is True or str(flagged).strip().lower() in {"1", "true", "yes"}
    if flagged or (kind == "candidate" and worker_knowledge.is_skill(meta)):
        return {"state": "candidate", "label": "候选（待 Human Review）", "source": "drafts/ 中的治理类知识" if kind == "candidate" else "frontmatter skill_candidate", "target": ""}
    return {"state": "none", "label": "尚未进入治理流程", "source": "", "target": ""}


def _flat_edges(kept_ids: set[str], declared: list[tuple[str, dict]]) -> list[dict]:
    """Collapse per-entry relation claims into the edges the main view can draw.

    A relation is only drawable when both ends are inside the projection, so
    unresolved targets -- and entries past the limit -- drop out here.  Each
    unordered pair is kept once per relation type; ``a``/``b`` are stored in
    sorted order so the two directions can never produce two lines.  Every
    declaring entry and every provenance label is folded into the surviving
    edge, so merging loses no attribution.
    """
    merged: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []
    for source_id, relation in declared:
        target_id = relation.get("target_id") or ""
        if not target_id or source_id == target_id:
            continue
        if source_id not in kept_ids or target_id not in kept_ids:
            continue
        a, b = sorted((source_id, target_id))
        key = (a, b, relation["type"])
        edge = merged.get(key)
        if edge is None:
            edge = {
                "a": a,
                "b": b,
                "type": relation["type"],
                "type_label": relation["type_label"],
                "color_key": relation["color_key"],
                "sources": [],
                "declared_by": [],
                "claims": [],
            }
            merged[key] = edge
            order.append(key)
        label = relation.get("source_label") or relation.get("source") or ""
        if label and label not in edge["sources"]:
            edge["sources"].append(label)
        if source_id not in edge["declared_by"]:
            edge["declared_by"].append(source_id)
        if relation.get("source", "").startswith("frontmatter "):
            claim = {"from": source_id, "to": target_id,
                     **{key: relation.get(key, "") for key in ("source", "raw_type", "note")}}
            if claim not in edge["claims"]:
                edge["claims"].append(claim)
    return [merged[key] for key in order]


def _raw_documents(root: Path, *, references: list[str] | None = None) -> tuple[dict, dict, list[str]]:
    """One node per Raw Bundle; only manifest-listed files alias that node."""
    root = root.resolve()
    documents, aliases, warnings = {}, {}, []
    raw = root / "raw"
    if not raw.is_dir():
        return documents, aliases, warnings

    if references is None:
        manifests = sorted(raw.rglob("bundle.json"))
        standalone = _scan(root, "raw")
    else:
        manifests, standalone = set(), []
        for value in references:
            value = value.replace("\\", "/")
            if not value.startswith("raw/"):
                continue
            path = (root / value).resolve()
            if not path.is_relative_to(raw) or not path.is_file():
                continue
            if path.suffix.lower() == ".md":
                standalone.append(path)
            for parent in path.parents:
                if not parent.is_relative_to(raw):
                    break
                manifest = parent / "bundle.json"
                if manifest.is_file():
                    manifests.add(manifest)
                    break
        manifests = sorted(manifests)

    def local(base: Path, value) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        path = (base / value).resolve()
        return path if path.is_relative_to(base.resolve()) and path.is_relative_to(raw) and path.is_file() else None

    for manifest in manifests:
        try:
            bundle = json.loads(manifest.read_text(encoding="utf-8"))
            files = bundle.get("files", {})
            if not isinstance(files, dict):
                raise ValueError("invalid files")
        except (OSError, ValueError, AttributeError):
            warnings.append(f"来源清单无法读取：{manifest.relative_to(root).as_posix()}")
            continue
        content = local(manifest.parent, files.get("content"))
        wrapper = local(manifest.parent, "raw.md")
        canonical = wrapper or content
        if canonical is None:
            continue
        key = canonical.relative_to(root).as_posix()
        documents[key] = {
            "body_path": (content or canonical).relative_to(root).as_posix(),
            "processing_status": str(bundle.get("processing_status") or "unknown"),
        }
        sources = bundle.get("sources", [])
        paths = [canonical, content] + [
            local(manifest.parent, item.get("path"))
            for item in sources if isinstance(item, dict)
        ] if isinstance(sources, list) else [canonical, content]
        for path in paths:
            if path is not None:
                aliases.setdefault(path.relative_to(root).as_posix(), set()).add(key)
    aliases = {path: next(iter(keys)) for path, keys in aliases.items() if len(keys) == 1}
    for path in standalone:
        if not path.resolve().is_relative_to(raw):
            continue
        key = path.relative_to(root).as_posix()
        if key not in aliases:
            documents.setdefault(key, {"body_path": key, "processing_status": "unknown"})
        aliases.setdefault(key, key)
    return documents, aliases, warnings


def _reviewed_sources(root, point, metadata, promotions):
    """Read sources only from the exact original retained by this Wiki review."""
    if (point["kind"] != "wiki" or not metadata.get("human_reviewed_at")
            or metadata.get("status") != "active" or metadata.get("archived")):
        return []
    references = []
    for candidate in _as_list(metadata.get("source_candidates")):
        for review in promotions.get(candidate, []):
            proof = review.get("reviewed_source")
            if review.get("wiki_path") != point["id"] or not isinstance(proof, dict):
                continue
            original = draft_review.read_original(root, {
                "draft_path": candidate, "draft_sha256": proof.get("sha256"), "original": proof,
            })
            if original is None:
                continue
            try:
                parsed = store._parse_wiki_text(original.decode("utf-8-sig"), Path(candidate)) or {}
            except UnicodeError:
                continue
            label = f'{candidate} reviewed_source {proof["sha256"]} frontmatter sources'
            references.extend((value, label) for value in _as_list(parsed.get("sources")))
    return references


def _internal_links(points: list[dict], bodies: dict[str, str], aliases: dict | None = None) -> list[dict]:
    """Resolve written Markdown/Wiki links within the visible projection.

    Tags never create these edges. Ambiguous bare names remain unresolved.
    Fenced/inline code and comments are examples, not knowledge declarations.
    """
    ids = {point["id"] for point in points}
    names: dict[str, set[str]] = {}
    for point in points:
        for name in (point["title"], Path(point["id"]).stem):
            names.setdefault(name.casefold(), set()).add(point["id"])
    links = []
    seen = set()
    for point in points:
        source = point["id"]
        body = re.sub(r"<!--.*?-->", "", bodies.get(source, ""), flags=re.S)
        prose = []
        fence = ""
        for line in body.splitlines():
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if fence:
                if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                    fence = ""
                continue
            if marker:
                fence = marker.group(1)
            elif not line.startswith(("    ", "\t")):
                prose.append(line)
        body = re.sub(r"(`+)[\s\S]*?\1", "", "\n".join(prose))
        targets = [(match, True) for match in re.findall(r"(?<!!)\[\[([^\]\n]+)\]\]", body)]
        targets += [(match, False) for match in re.findall(r"(?<!!)\[[^\]\n]*\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", body)]
        for target, wiki in targets:
            raw = unquote(target.split("|", 1)[0].split("#", 1)[0]).strip().replace("\\", "/")
            try:
                external = bool(urlsplit(raw).scheme)
            except ValueError:
                continue
            if not raw or raw.startswith("/") or external:
                continue
            candidates = []
            for base in (raw, posixpath.normpath(posixpath.join(posixpath.dirname(source), raw))):
                candidates.extend([base, base + ".md"] if not base.endswith(".md") else [base])
            resolved = next(((aliases or {}).get(value, value) for value in candidates
                             if (aliases or {}).get(value, value) in ids), None)
            if resolved is None and wiki and "/" not in raw:
                matches = names.get(raw.removesuffix(".md").casefold(), set())
                if len(matches) == 1:
                    resolved = next(iter(matches))
            if not resolved or resolved == source or (source, resolved) in seen:
                continue
            seen.add((source, resolved))
            links.append({"a": source, "b": resolved, "type": "internal_link", "type_label": "内部链接",
                          "declared_by": [source], "sources": [f"{source} 正文中的内部链接"]})
    return links


def knowledge_map(root: Path, limit: int = 400, *, worker_snapshot: dict | None = None) -> dict:
    """Project Wiki, candidates and original sources with recorded relations."""
    limit = max(1, min(int(limit or 400), 2000))
    paths: list[tuple[Path, str]] = [(path, "wiki") for path in _scan(root, "wiki")]
    paths += [(path, "candidate") for path in _scan(root, "drafts")]
    raw_documents, raw_aliases, raw_warnings = _raw_documents(root)
    paths += [(root / path, "raw") for path in raw_documents]
    from .task_workflow import candidate_disposition, _rejections
    from .draft_review import disposition as ordinary_review
    promotions, rejections = draft_review.promotions(root), _rejections(root)

    points: list[dict] = []
    bodies: dict[str, str] = {}
    original_metadata: dict[str, dict] = {}
    hidden = 0
    for path, kind in paths:
        if kind == 'candidate' and candidate_disposition(root, path.relative_to(root).as_posix(), promotions=promotions, rejections=rejections):
            continue
        if kind == 'candidate' and ordinary_review(root, path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(), promotions=promotions):
            continue
        parsed = store.parse_wiki_file(path) or {}
        body = str(parsed.pop("body", "") or "")
        document_title = document_metadata.title(parsed, body, path)
        raw_info = raw_documents.get(path.relative_to(root).as_posix()) if kind == "raw" else None
        if raw_info:
            if raw_info["processing_status"] == "unknown":
                raw_info["processing_status"] = str(parsed.get("processing_status") or "unknown")
            with (root / raw_info["body_path"]).open(encoding="utf-8", errors="replace") as source:
                body = source.read(12001)
        if not document_metadata.is_visible(parsed):
            hidden += 1
            continue
        updated_at, timestamp_source = document_metadata.event_time(parsed, path)
        updated_at = updated_at.isoformat()
        tags = _as_list(parsed.get("tags"))
        # Candidates produced by the dreaming pipeline carry draft_* keys; they
        # describe the same two things, so they resolve into the same shape.
        area = str(parsed.get("area") or parsed.get("domain") or parsed.get("draft_area") or "").strip() or "未分类"
        governance_type = str(parsed.get("type") or parsed.get("draft_type") or "").strip().lower()
        if governance_type not in GOVERNANCE_TYPES:
            governance_type = "unclassified"
        enabled = parsed.get("enabled")
        enabled = True if enabled is None else (enabled is True or str(enabled).strip().lower() in {"1", "true", "yes"})
        # A cluster has to say something the domain does not.  The first tag that
        # differs from the domain name is the most specific honest grouping; when
        # every tag merely restates the domain, the entry is genuinely generic.
        cluster_tag = next((tag for tag in tags if tag.lower() != area.lower()), "")
        if cluster_tag:
            cluster, cluster_source = cluster_tag, f"首个不同于知识域的标签「{cluster_tag}」"
        elif tags:
            cluster, cluster_source = "本域通用", "标签与知识域同名，无法细分"
        else:
            cluster, cluster_source = "未分组", "这条知识没有标签"
        review = review_summary(parsed, kind)
        if kind == "raw":
            review = {"state": "not_applicable", "label": "来源资料", "reviewed": False,
                      "human_reviewed_at": None, "kind_label": "来源资料"}
        original_metadata[path.relative_to(root).as_posix()] = parsed
        bodies[path.relative_to(root).as_posix()] = body
        points.append({
            "id": path.relative_to(root).as_posix(),
            "path": path.relative_to(root).as_posix(),
            "kind": kind,
            "kind_label": "来源资料" if kind == "raw" else "来源资料 · 机器提取" if is_source_material(parsed) else review["kind_label"],
            "content_role": "source_material" if kind == "raw" or is_source_material(parsed) else "knowledge",
            "review": review,
            "title": _source_title(parsed, body, path, document_title) if kind == "raw" else document_title,
            "summary": document_metadata.summary(parsed, body, skip_quotes=True),
            "body": "" if kind == "raw" else body[:12000],
            **(raw_info or {}),
            "body_truncated": len(body) > 12000,
            "area": area,
            "cluster": cluster,
            "cluster_source": cluster_source,
            "tags": tags[:12],
            "all_tags": tags,
            # 给读者看的标签沿用同一套人话口径；翻不出来的英文机器键在这里就挡掉，
            # 页面拿到的是可以直接显示的清单。与独立 Wiki 页同源，两处不再各翻一套。
            "tag_labels": [label for label in (tag_label(tag) for tag in tags[:12]) if label],
            "status": str(parsed.get("status") or "active"),
            "status_label": {
                "active": "当前条目",
                "pending": "待审核",
                "provisional": "待确认",
                "stale": "需要更新",
                "draft": "草稿待审",
            }.get(str(parsed.get("status") or "active"), str(parsed.get("status") or "active")),
            "updated_at": updated_at,
            "timestamp_source": timestamp_source,
            # 界面只显示人话；原始键名（created / updated_at / file_mtime）留在
            # payload 里供排查，不进默认阅读路径。前端与独立 Wiki 页共用这一份。
            "timestamp_source_label": time_source_label(timestamp_source),
            "governance": {
                "type": governance_type,
                "type_label": GOVERNANCE_TYPES.get(governance_type, ("未分类", ""))[0],
                "type_question": GOVERNANCE_TYPES.get(governance_type, ("", "这条知识还没有治理分类"))[1],
                "enabled": enabled,
                "pinned": bool(parsed.get("pinned") is True or str(parsed.get("pinned")).strip().lower() in {"1", "true", "yes"}),
                "importance": _as_float(parsed.get("importance")),
                "confidence": _as_float(parsed.get("confidence")),
            },
            "skill": _skill_state(parsed, kind, governance_type),
            "wiki_refs": [path.relative_to(root).as_posix()],
            "relations": _relations(parsed),
            "metadata": {key: str(value) for key, value in parsed.items() if key not in {"file_path", "slug"}},
        })

    # Resolve against all visible pages before pagination to reject ambiguity.
    from knowledge_studio.ingest_workflow import _inside
    origins: dict[str, list[dict]] = {}
    for item in points:
        item["source_candidates"] = []
        meta = original_metadata[item["id"]]
        values = meta.get("source_candidates")
        if (item["kind"] != "wiki" or not meta.get("human_reviewed_at")
                or meta.get("status") != "active" or meta.get("archived")
                or not isinstance(values, list)):
            continue
        for value in set(v for v in values if isinstance(v, str)):
            try:
                path = _inside(root.resolve(), value, "drafts")
            except ValueError:
                continue
            if path.suffix.lower() == '.md':
                reviewed = None
                if path.is_file():
                    reviewed = draft_review.disposition(root, value, hashlib.sha256(path.read_bytes()).hexdigest(), promotions=promotions)
                if not path.exists() or (reviewed and reviewed.get('decision') == 'promoted' and reviewed.get('wiki_path') == item['id']):
                    origins.setdefault(value, []).append(item)
    for value, matches in origins.items():
        if len(matches) == 1:
            matches[0]["source_candidates"].append(value)
    for item in points:
        item["source_candidates"].sort()

    by_id = {point["id"]: point for point in points}
    by_name: dict[str, set[str]] = {}
    for point in points:
        for name in (Path(point["id"]).stem, point["title"]):
            by_name.setdefault(name.casefold(), set()).add(point["id"])

    def resolve(target: str):
        raw = str(target or "").strip()
        if not raw:
            return None, "missing"
        if raw in by_id:
            return by_id[raw], "resolved"
        if "/" in raw or "\\" in raw:
            return None, "missing"
        matches = by_name.get(raw.casefold(), set()) | by_name.get(raw.removesuffix(".md").casefold(), set())
        if len(matches) == 1:
            return by_id[next(iter(matches))], "resolved"
        return None, "ambiguous" if matches else "missing"

    # Tag index drives derived "shared tag" edges.  The domain tag is skipped:
    # grouping already expresses it, and letting it emit edges would connect
    # every entry in a domain to every other one.
    tag_index: dict[str, list[str]] = {}
    for point in points:
        if point["content_role"] == "source_material":
            continue
        for tag in point["tags"]:
            if tag.lower() == point["area"].lower():
                continue
            tag_index.setdefault(tag, []).append(point["id"])

    truncated = len(points) > limit
    kept = points[:limit]
    kept_ids = {point["id"] for point in kept}
    #: Drawable relations before per-entry truncation and dedup.  The
    #: per-entry list is capped at 12 so the drawer stays readable; the main
    #: view must not lose lines just because of that cap, so the flat edge
    #: table is built from this accumulator instead.
    declared: list[tuple[str, dict]] = []
    for point in kept:
        edges = []
        seen = set()
        for relation in point["relations"]:
            match, resolution = resolve(relation["target"])
            relation = dict(relation)
            relation["resolution"] = resolution
            relation["resolved"] = match is not None
            if match:
                relation["target_id"] = match["id"]
                relation["target_title"] = match["title"]
                relation["target_kind"] = match["kind"]
            else:
                relation["target_id"] = ""
                relation["target_title"] = relation["target"]
                relation["target_kind"] = "unresolved"
            key = (relation["type"], relation["target_id"] or relation["target"],
                   relation["source"], relation["raw_type"], relation["note"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(relation)
        for tag in ([] if point["content_role"] == "source_material" else point["tags"]):
            if tag == point["cluster"]:
                # Entries already sit together in this cluster; an edge would
                # only restate the grouping.
                continue
            for other in tag_index.get(tag, []):
                if other == point["id"]:
                    continue
                # Keep the drawer's first 12 entries and a truncation sentinel.
                # Beyond that, only visible targets can contribute a drawn edge.
                if len(edges) > 12 and other not in kept_ids:
                    continue
                key = ("related", other)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "type": "related",
                    "type_label": RELATION_TYPES["related"],
                    "color_key": "related",
                    "raw_type": "related",
                    "target": other,
                    "note": "",
                    "source": f"shared tag: {tag}",
                    "source_label": f"和另一条知识共享标签「{tag}」",
                    "resolved": True,
                    "target_id": other,
                    "target_title": by_id[other]["title"],
                    "target_kind": by_id[other]["kind"],
                })
        declared.extend((point["id"], edge) for edge in edges if edge.get("target_id") in kept_ids)
        truncated_edges = len(edges) > 12
        point["relations"] = edges[:12]
        point["relations_truncated"] = truncated_edges
    worker_source = worker_knowledge.project(root, kept, original_metadata, worker_snapshot)
    for point in kept:
        point["governance"]["applicable"] = point["is_skill"]
    material_ids = {point["id"] for point in kept if point["content_role"] == "source_material"}
    knowledge_ids = kept_ids - material_ids
    relation_edges = _flat_edges(knowledge_ids, declared)
    material_edges = [edge for edge in _flat_edges(kept_ids, declared)
                      if edge["a"] in material_ids or edge["b"] in material_ids]
    for point in kept:
        metadata = original_metadata[point["id"]]
        references = [(value, f'{point["id"]} frontmatter sources')
                      for value in _as_list(metadata.get("sources"))]
        references += _reviewed_sources(root, point, metadata, promotions)
        targets = {}
        for value, evidence in references:
            target = raw_aliases.get(value.replace("\\", "/"))
            if target in material_ids and target != point["id"]:
                sources = targets.setdefault(target, [])
                if evidence not in sources:
                    sources.append(evidence)
        for target in sorted(targets):
            material_edges.append({
                "a": point["id"], "b": target, "type": "source", "type_label": "来源",
                "declared_by": [point["id"]], "sources": targets[target],
            })
    area_of = {point["id"]: point["area"] for point in kept}
    internal_links = _internal_links(kept, bodies, raw_aliases)
    connected = {end for edge in relation_edges + material_edges + internal_links
                 for end in (edge["a"], edge["b"])}

    domains: dict[str, dict] = {}
    for point in kept:
        if point["content_role"] == "source_material":
            continue
        domain = domains.setdefault(point["area"], {
            "id": point["area"],
            "key": point["area"],
            "label": DOMAIN_LABELS.get(point["area"], point["area"]),
            "count": 0,
            "clusters": {},
        })
        domain["count"] += 1
        cluster = domain["clusters"].setdefault(point["cluster"], {
            "id": point["cluster"],
            "key": point["cluster"],
            "label": CLUSTER_LABELS.get(point["cluster"], point["cluster"]),
            "count": 0,
            "points": [],
        })
        cluster["count"] += 1
        cluster["points"].append(point)

    def sort_key(item):
        return (0 if item["label"] != "未分类" else 1, -item["count"], item["label"])

    domain_list = []
    for domain in sorted(domains.values(), key=sort_key):
        clusters = sorted(domain["clusters"].values(), key=sort_key)
        domain_list.append({
            "id": domain["id"],
            "key": domain["key"],
            "label": domain["label"],
            "count": domain["count"],
            "clusters": clusters,
        })

    def governance_member(point: dict) -> dict:
        return {
            "path": point["path"],
            "title": point["title"],
            "kind_label": point["kind_label"],
            "enabled": point["governance"]["enabled"],
            "status_label": point["status_label"],
        }

    governance = []
    for type_id, (label, question) in GOVERNANCE_TYPES.items():
        rows = [point for point in kept if point["is_skill"] and point["governance"]["type"] == type_id]
        governance.append({
            "id": type_id,
            "label": label,
            "question": question,
            "count": len(rows),
            "enabled": sum(1 for point in rows if point["governance"]["enabled"]),
            "disabled": sum(1 for point in rows if not point["governance"]["enabled"]),
            "members": [governance_member(point) for point in rows],
            "paths": [point["path"] for point in rows],
        })
    unclassified = [point["path"] for point in kept if point["is_skill"] and point["governance"]["type"] == "unclassified"]
    pluggable = [
        governance_member(point) for point in kept
        if point["is_skill"] and point["governance"]["type"] in GOVERNANCE_TYPES
    ]

    knowledge_points = [point for point in kept if point["content_role"] != "source_material"]
    materials = [point for point in kept if point["content_role"] == "source_material"]
    return {
        "schema": SCHEMA,
        "materials": materials,
        "material_edges": material_edges,
        "warnings": raw_warnings,
        "worker_source": worker_source,
        "scope": {
            "knowledge_base": str(root),
            "points_total": len(points),
            "points_returned": len(kept),
            "limit": limit,
            "truncated": truncated or len(points) != len(kept_ids),
            "hidden": hidden,
            "note": (
                "这是知识、候选和原始来源的只读关系视图，每条关系都标了来源；"
                "这里不包含 Agent 的执行过程。"
            ),
            "why": (
                "知识图只显示文件中已经记录的关系，不新增任何知识。"
                "文档关系视图展示真实文档；分类层级可按知识域分组。"
                "两边都收录在图里、才会有一条线；没有一条是从「看起来相关」推出来的。"
                "每条连线都标了来源。同一 Raw Bundle 只显示一份来源，不含 Agent 的执行过程。"
                "图本身不写入任何东西；治理位也只展示，不在这里改。"
            ),
            "level_sources": [
                "条目自己声明的所属领域",
                "条目自己声明的关系，或与另一条知识共享的标签",
                "一份 Wiki 或候选条目；审核记录单独展示",
            ],
        },
        "counts": {
            "domains": len(domain_list),
            "clusters": sum(len(domain["clusters"]) for domain in domain_list),
            "points": len(knowledge_points),
            "source_materials": len(materials),
            "relations": sum(len(point["relations"]) for point in knowledge_points),
            # What the main view can actually draw: one entry per unordered
            # pair, both ends inside the projection.  The legend reports this,
            # not the per-entry tally -- that tally counted a single undirected
            # relation once from each end.
            "edges": len(relation_edges),
            "edges_cross_domain": sum(
                1 for edge in relation_edges
                if area_of.get(edge["a"]) != area_of.get(edge["b"])
            ),
            "points_without_relations": sum(point["id"] not in connected for point in knowledge_points),
            "wiki_count": sum(1 for point in knowledge_points if point["kind"] == "wiki"),
            "reviewed": sum(1 for point in knowledge_points if point["review"]["reviewed"]),
            "review_unknown": sum(1 for point in knowledge_points if point["review"]["state"] == "unknown"),
            "candidates": sum(1 for point in knowledge_points if point["kind"] == "candidate"),
            "skill_candidates": sum(1 for point in knowledge_points if point["skill"]["state"] == "candidate"),
            "skill_packaged": sum(1 for point in knowledge_points if point["skill"]["state"] == "packaged"),
            "enabled": sum(1 for point in knowledge_points if point["governance"]["enabled"]),
            "disabled": sum(1 for point in knowledge_points if not point["governance"]["enabled"]),
            "governance_typed": sum(1 for point in knowledge_points if point["governance"]["type"] != "unclassified"),
        },
        "domains": domain_list,
        # The main view draws exactly these; the legend counts exactly these.
        "edges": relation_edges,
        "explicit_edges": _flat_edges(knowledge_ids, [
            (source, relation) for source, relation in declared
            if relation.get("source", "").startswith("frontmatter ")
        ]),
        "shared_tag_edges": _flat_edges(knowledge_ids, [
            (source, relation) for source, relation in declared
            if relation.get("source", "").startswith("shared tag: ")
        ]),
        "internal_links": internal_links,
        # Counting the per-entry lists instead double-counted every undirected
        # relation (once from each end) and reported 29 edges for 14 drawable
        # ones.  A legend has to describe the picture next to it.
        "relation_legend": [
            {
                "id": kind,
                "label": label,
                "color_key": kind,
                "count": sum(1 for edge in relation_edges if edge["type"] == kind),
            }
            for kind, label in RELATION_TYPES.items()
        ] + [
            {
                "id": "unknown",
                "label": "未识别关系",
                "color_key": "unknown",
                "count": sum(1 for edge in relation_edges if edge["type"] == "unknown"),
            }
        ],
        "governance": {
            "note": (
                "概念 / 策略 / 反策略说的是「这条经验该怎么用」，"
                "不改变知识本身的归类；上方的分组只看知识域。"
            ),
            "types": governance,
            "pluggable": pluggable,
            "unclassified": unclassified,
            "skill_boundary": SKILL_BOUNDARY,
            # 面板是只读观察面：这里只报计数，不再携带任何写端点 / 写保证。
            # 密钥名从 toggle 改掉，是因为它现在既不是「开关」也没有「切换」动作。
            "enabled_state": {
                "field": TOGGLE_FIELD,
                "counts": {
                    "enabled": sum(1 for point in kept if point["governance"]["enabled"]),
                    "disabled": sum(1 for point in kept if not point["governance"]["enabled"]),
                },
            },
        },
    }


# ── 治理位：库能力保留，面板不再有写路径 ──────────────────────────────
#
# 边界变更（2026-09-22，取代 Owner 2026-09-19 的「面板唯一写路径」裁定）：
#   * 原因：`enabled` 位当时**没有任何消费方** —— recall / store / skill / hook 都不读它，
#     而面板文案据此声称「停用后不再被 Skill 层启用」，等于许诺一个没实现的下游效果。
#     一个只读观察面也不该是唯一能改写知识库文件的入口。
#   * 因此移除：面板的启用 / 停用开关、`/api/mail/knowledge/toggle` 路由，
#     以及 SKILL_BOUNDARY 里与之对应的那条声明。
#   * `set_enabled()` 保留为库能力（路径限于 wiki/ 与 drafts/、字节级备份、原子替换），
#     但它当前**没有生产调用方**；将来若要暴露，必须走 CLI / Agent，而不是无鉴权的 HTTP 路由。
#   * 每次写入前把原文件整字节备份到 <KB>/.oks/knowledge-backups/，
#     再用临时文件 + os.replace 原子替换；失败不留下半截文件。
#   * 没有 frontmatter 的条目直接拒绝，不做「帮你补一个」的猜测。

TOGGLE_FIELD = "enabled"
BACKUP_DIR = Path(".oks") / "knowledge-backups"
_ENABLED_LINE = re.compile(r"^([ \t]*)enabled[ \t]*:.*$", re.MULTILINE)


def knowledge_path(root: Path, relative: str) -> Path:
    """Resolve a knowledge path, refusing anything outside wiki/ or drafts/."""
    if not relative or Path(relative).is_absolute():
        raise ValueError("知识路径必须是指向 wiki/ 或 drafts/ 的相对路径")
    candidate = (root / relative).resolve()
    allowed = [(root / "wiki").resolve(), (root / "drafts").resolve()]
    if (
        candidate.suffix.lower() != ".md"
        or not candidate.is_file()
        or not any(candidate.is_relative_to(base) for base in allowed)
    ):
        raise FileNotFoundError("这条知识不在 wiki/ 或 drafts/ 下，无法读写")
    return candidate


def _backup(root: Path, relative: str, payload: bytes) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flat = relative.replace("\\", "/").replace("/", "__")
    target = root / BACKUP_DIR / f"{flat}.{stamp}.bak"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def set_enabled(root: Path, relative: str, enabled: bool) -> dict:
    """Flip the governance ``enabled`` bit of one knowledge entry.

    Kept as a library capability; since 2026-09-22 it has **no production caller** —
    the panel's ``/api/mail/knowledge/toggle`` route was removed along with the UI
    switch, because nothing in the system reads this bit.

    Raises ``FileNotFoundError`` for paths outside wiki/drafts and ``ValueError``
    when the file has no frontmatter block to write into.
    """
    path = knowledge_path(root, relative)
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("这个文件不是 UTF-8，拒绝改写") from exc
    if not text.startswith("---"):
        raise ValueError("这条知识没有 frontmatter，拒绝硬造一个治理字段")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("这条知识的 frontmatter 不完整，拒绝改写")

    front = parts[1]
    previous = None
    for line in front.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(f"{TOGGLE_FIELD}"):
            previous = stripped.partition(":")[2].strip().strip('"').strip("'")
            break
    previous_enabled = True if previous is None else previous.strip().lower() in {"1", "true", "yes", "on"}

    want = "true" if enabled else "false"
    if _ENABLED_LINE.search(front):
        new_front = _ENABLED_LINE.sub(lambda m: f"{m.group(1)}{TOGGLE_FIELD}: {want}", front, count=1)
    else:
        newline = "\r\n" if "\r\n" in front else "\n"
        padded = front if front.endswith(("\n", "\r")) else front + newline
        new_front = f"{padded}{TOGGLE_FIELD}: {want}{newline}"

    updated = f"---{new_front}---{parts[2]}"
    backup = _backup(root, relative, original)

    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".oks-toggle-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(updated.encode("utf-8"))
        os.replace(temp_name, path)
    except OSError:
        Path(temp_name).unlink(missing_ok=True)
        raise

    return {
        "schema": "mail.knowledge-toggle.v1",
        "path": relative,
        "enabled": bool(enabled),
        "previous_enabled": previous_enabled,
        "changed": previous_enabled != bool(enabled),
        "field": TOGGLE_FIELD,
        "backup": backup.relative_to(root).as_posix(),
        "note": (
            "只改了 frontmatter 的 enabled 治理位；正文与其他字段原样保留。"
            "原文件已整字节备份，可据此回滚。"
        ),
    }

