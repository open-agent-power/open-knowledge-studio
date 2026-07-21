"""Filesystem CRUD for wiki pages — pure file operations, no database.

Extracted from autpilot-web/backend/app/services/knowledge_distiller.py.
Removed KnowledgeStore, settings, and hook dispatcher dependencies.
Repo root resolved via OKS_ROOT env var or current working directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

_logger = logging.getLogger(__name__)

DECAY_LAMBDA: dict[str, float] = {
    "concept": 0.0,
    "strategy": 0.014,
    "anti-pattern": 0.010,
}

DEFAULT_CONFIG: dict = {
    "decay": {
        "archive_threshold": 0.3,
        "pin_bonus": 0.5,
    },
}


def repo_root() -> Path:
    env_root = os.environ.get("OKS_ROOT")
    if env_root:
        return Path(env_root)
    try:
        from knowledge_studio.config import load_config

        kb_path = load_config().get("knowledge_base_path")
        if kb_path:
            return Path(kb_path)
    except Exception:
        pass
    return Path(os.getcwd())


def wiki_dir() -> Path:
    return repo_root() / "wiki"


def drafts_dir() -> Path:
    return repo_root() / "drafts"


def raw_dir() -> Path:
    return repo_root() / "raw"


def goals_dir() -> Path:
    return repo_root() / "profiles" / "goals"


def _as_str_set(value) -> set[str]:
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value]
    else:
        return set()
    return {item.lower() for item in items if item}


def load_active_goals() -> list[dict]:
    """Return active goals (type==goal, status==active) as normalized dicts.

    Each entry has lowercased 'domains' and 'keywords' string sets, used by
    recall to boost pages that fall within an active goal's scope. Returns an
    empty list when profiles/goals is absent or holds no active goals.
    """
    gd = goals_dir()
    if not gd.exists():
        return []

    goals: list[dict] = []
    for path in sorted(gd.rglob("*.md")):
        meta = parse_wiki_file(path)
        if not meta:
            continue
        if meta.get("type") != "goal" or meta.get("status") != "active":
            continue
        goals.append({
            "slug": meta.get("slug", path.stem),
            "title": meta.get("title", path.stem),
            "domains": _as_str_set(meta.get("domains")),
            "keywords": _as_str_set(meta.get("keywords")),
        })
    return goals


def _access_log_path() -> Path:
    log_dir = repo_root() / ".oks"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "access.json"


def _load_access_counts() -> dict[str, int]:
    path = _access_log_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_access_counts(counts: dict[str, int]) -> None:
    path = _access_log_path()
    _atomic_write(path, json.dumps(counts, indent=2))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def parse_wiki_file(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1].strip()) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(meta, dict):
        return None

    meta["body"] = parts[2].strip()
    meta["slug"] = path.stem
    meta["file_path"] = str(path)
    return meta


def compute_score(meta: dict, access_count: int = 0, config: dict | None = None) -> float:
    importance = meta.get("importance", 0.5)
    wiki_type = meta.get("type", meta.get("category", "concept"))
    lam = DECAY_LAMBDA.get(wiki_type, 0.030)
    pinned = meta.get("pinned", False)
    status = meta.get("status", "active")
    archived = meta.get("archived", False)

    if archived or status == "dropped":
        return 0.0

    created_str = meta.get("created", "")
    try:
        created = datetime.fromisoformat(created_str)
    except (ValueError, TypeError):
        created = datetime.now(UTC)

    tz = UTC if not created.tzinfo else created.tzinfo
    days_old = max(0, (datetime.now(UTC) - created.replace(tzinfo=tz)).days)
    time_decay = importance * math.exp(-lam * days_old)
    access_bonus = 0.5 * math.log(1 + access_count)

    cfg = config or DEFAULT_CONFIG
    pin_bonus = cfg.get("decay", {}).get("pin_bonus", 0.5) if pinned else 0.0

    score = time_decay + access_bonus + pin_bonus
    if status == "active":
        score *= 1.2
    return score


def compute_tier(score: float) -> str:
    if score >= 0.7:
        return "hot"
    if score >= 0.4:
        return "warm"
    if score >= 0.15:
        return "cold"
    return "evictable"


def compute_quality(meta: dict) -> int:
    # Content factors (55) are reachable by any well-written page;
    # traces/review (40) are earned bonuses, not the baseline.
    score = 0
    if len(meta.get("body", "")) >= 50:
        score += 25
    if meta.get("importance", 0) >= 0.7:
        score += 15
    tags = meta.get("tags", "")
    if isinstance(tags, list):
        if tags:
            score += 15
    elif isinstance(tags, str) and tags.strip():
        score += 15
    if meta.get("traces"):
        score += 20
    if meta.get("review"):
        score += 20
    if meta.get("options"):
        score += 5
    return score


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _fingerprint_index_path() -> Path:
    d = repo_root() / ".oks"
    d.mkdir(parents=True, exist_ok=True)
    return d / "fingerprints.json"


def _load_fingerprint_index() -> dict[str, str]:
    path = _fingerprint_index_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_fingerprint_index(index: dict[str, str]) -> None:
    _atomic_write(_fingerprint_index_path(), json.dumps(index, indent=2))


def _find_file_by_slug(slug: str) -> Path | None:
    wd = wiki_dir()
    if not wd.exists():
        return None
    for f in wd.rglob("*.md"):
        if f.stem == slug:
            return f
    return None


def _update_frontmatter_field(file_path: Path, field: str, value) -> None:
    text = file_path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    try:
        meta = yaml.safe_load(parts[1].strip()) or {}
    except yaml.YAMLError:
        return
    meta[field] = value
    new_fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _atomic_write(file_path, f"---\n{new_fm}---\n{parts[2]}")


def _reinforce_confidence(slug: str) -> None:
    f = _find_file_by_slug(slug)
    if not f:
        return
    meta = parse_wiki_file(f)
    if not meta:
        return
    current = meta.get("confidence", 0.8)
    new_conf = min(1.0, current + 0.1 * (1 - current))
    if new_conf != current:
        _update_frontmatter_field(f, "confidence", round(new_conf, 4))
    access_counts = _load_access_counts()
    if access_counts.get(slug, 0) >= 3:
        if meta.get("status", "active") == "provisional":
            _update_frontmatter_field(f, "status", "active")


def list_wiki_pages(config: dict | None = None) -> list[dict]:
    wd = wiki_dir()
    if not wd.exists():
        return []

    access_counts = _load_access_counts()
    pages: list[dict] = []

    for f in wd.rglob("*.md"):
        if f.name == "INDEX.md":
            continue
        meta = parse_wiki_file(f)
        if not meta:
            continue
        slug = meta["slug"]
        ac = access_counts.get(slug, 0)
        meta["access_count"] = ac
        score = compute_score(meta, ac, config)
        meta["score"] = score
        meta["tier"] = compute_tier(score)
        meta["quality_score"] = compute_quality(meta)
        if "status" not in meta:
            meta["status"] = "active"
        pages.append(meta)

    pages.sort(key=lambda x: (-x["score"], x["slug"]))
    return pages


def get_wiki_page(slug: str) -> dict | None:
    f = _find_file_by_slug(slug)
    if not f:
        return None
    meta = parse_wiki_file(f)
    if not meta:
        return None
    access_counts = _load_access_counts()
    ac = access_counts.get(slug, 0)
    meta["access_count"] = ac
    meta["score"] = compute_score(meta, ac)
    meta["tier"] = compute_tier(meta["score"])
    meta["quality_score"] = compute_quality(meta)
    return meta


def record_access(slug: str) -> None:
    counts = _load_access_counts()
    counts[slug] = counts.get(slug, 0) + 1
    _save_access_counts(counts)
    _reinforce_confidence(slug)


def make_slug(title: str, fallback: str = "untitled") -> str:
    # Keep CJK characters so Chinese titles don't degrade to the fallback.
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", title.lower())[:60].strip("-")
    return slug or fallback


def write_wiki_page(
    title: str,
    content: str,
    wiki_type: str = "concepts",
    area: str = "computing",
    source_type: str = "auto",
    importance: float = 0.5,
    tags: list[str] | None = None,
    options: list[dict] | None = None,
    traces: list[dict] | None = None,
    review: dict | None = None,
    supersedes: str | None = None,
    relates_to: str | None = None,
    relationship: str | None = None,
    human_note: str | None = None,
) -> Path:
    fp = _fingerprint(content)
    fp_index = _load_fingerprint_index()
    existing_slug = fp_index.get(fp)
    if existing_slug:
        _reinforce_confidence(existing_slug)
        existing = _find_file_by_slug(existing_slug)
        if existing:
            return existing

    wd = wiki_dir()
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    type_dir = wd / area / wiki_type
    type_dir.mkdir(parents=True, exist_ok=True)

    slug = make_slug(title, fallback="untitled")
    slug = f"{date_str}-{slug}"

    file_path = type_dir / f"{slug}.md"
    counter = 1
    while file_path.exists():
        file_path = type_dir / f"{slug}-{counter}.md"
        counter += 1

    if supersedes and not relates_to:
        relates_to = supersedes
        relationship = "supersedes"

    if relates_to and relationship:
        old_file = _find_file_by_slug(relates_to)
        if old_file:
            if relationship == "supersedes":
                _update_frontmatter_field(old_file, "status", "superseded")
                _update_frontmatter_field(old_file, "superseded_by", slug)
            elif relationship == "enriches":
                _update_frontmatter_field(old_file, "enriched_by", slug)
            elif relationship == "confirms":
                old_meta = parse_wiki_file(old_file)
                if old_meta:
                    current_conf = old_meta.get("confidence", 0.8)
                    new_conf = min(1.0, current_conf + 0.1)
                    _update_frontmatter_field(old_file, "confidence", round(new_conf, 4))
                _update_frontmatter_field(old_file, "confirmed_by", slug)
            elif relationship == "challenges":
                _update_frontmatter_field(old_file, "status", "stale")
                _update_frontmatter_field(old_file, "challenged_by", slug)

    frontmatter: dict = {
        "title": title,
        "type": wiki_type[:-3] + "y" if wiki_type.endswith("ies") else wiki_type.rstrip("s"),
        "area": area,
        "status": "provisional",
        "source_type": source_type,
        "importance": importance,
        "confidence": 0.8,
        "created": now.isoformat(),
        "pinned": False,
        "archived": False,
        "tags": ", ".join(tags) if tags else "",
        "fingerprint": fp,
    }
    if options:
        frontmatter["options"] = options
    if traces:
        frontmatter["traces"] = traces
    if review:
        frontmatter["review"] = review
    if human_note:
        frontmatter["human_note"] = human_note
    if relates_to and relationship:
        frontmatter["relates_to"] = relates_to
        frontmatter["relationship"] = relationship

    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _atomic_write(file_path, f"---\n{fm_str}---\n\n{content}")

    fp_index[fp] = slug
    _save_fingerprint_index(fp_index)

    return file_path


def apply_decay(config: dict | None = None) -> list[str]:
    cfg = config or DEFAULT_CONFIG
    threshold = cfg.get("decay", {}).get("archive_threshold", 0.3)
    dropped: list[str] = []

    wd = wiki_dir()
    if not wd.exists():
        return []

    access_counts = _load_access_counts()

    for f in wd.rglob("*.md"):
        if f.name == "INDEX.md":
            continue
        meta = parse_wiki_file(f)
        if not meta or meta.get("archived") or meta.get("pinned"):
            continue
        if meta.get("status") == "dropped":
            continue

        score = compute_score(meta, access_counts.get(meta["slug"], 0), cfg)
        if score < threshold:
            _update_frontmatter_field(f, "status", "dropped")
            dropped.append(meta["slug"])

    return dropped


def pin_page(slug: str) -> bool:
    f = _find_file_by_slug(slug)
    if not f:
        return False
    _update_frontmatter_field(f, "pinned", True)
    return True


def archive_page(slug: str) -> bool:
    f = _find_file_by_slug(slug)
    if not f:
        return False
    _update_frontmatter_field(f, "status", "dropped")
    _update_frontmatter_field(f, "archived", True)
    return True


def list_drafts() -> list[dict]:
    dd = drafts_dir()
    if not dd.exists():
        return []

    drafts: list[dict] = []
    for f in sorted(dd.glob("*.md")):
        meta = parse_wiki_file(f)
        if not meta:
            continue
        drafts.append({
            "slug": meta["slug"],
            "title": meta.get("title", meta["slug"]),
            "draft_type": meta.get("draft_type", "concept"),
            "draft_area": meta.get("draft_area", "computing"),
            "source_pages": meta.get("source_pages", []),
            "drafted_at": meta.get("drafted_at", ""),
            "status": meta.get("status", "draft"),
            "body": meta.get("body", ""),
        })
    return drafts


def promote_draft(
    slug: str,
    title: str | None = None,
    wiki_type: str | None = None,
    area: str | None = None,
    tags: list[str] | None = None,
) -> str:
    dd = drafts_dir()
    draft_path = dd / f"{slug}.md"
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")

    meta = parse_wiki_file(draft_path)
    if not meta:
        meta = {}
    body = meta.get("body", "")

    final_title = title or meta.get("title", slug)
    final_type = (wiki_type or meta.get("draft_type", "concepts")).rstrip("s") + "s"
    final_area = area or meta.get("draft_area", "computing")
    human_note = meta.get("source_note") or None

    path = write_wiki_page(
        title=final_title,
        content=body,
        wiki_type=final_type,
        area=final_area,
        importance=0.7,
        tags=tags,
        human_note=human_note,
    )

    draft_path.unlink()
    return path.stem


def reject_draft(slug: str) -> None:
    dd = drafts_dir()
    draft_path = dd / f"{slug}.md"
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")
    draft_path.unlink()


def wiki_digest(config: dict | None = None) -> dict:
    all_pages = list_wiki_pages(config)

    tier_counts = {"hot": 0, "warm": 0, "cold": 0, "evictable": 0}
    quality_scores: list[int] = []
    pinned_count = 0
    type_counts: dict[str, int] = {}
    date_groups: dict[str, dict] = {}

    for item in all_pages:
        tier_counts[item.get("tier", "cold")] += 1
        quality_scores.append(item.get("quality_score", 0))
        if item.get("pinned"):
            pinned_count += 1

        wiki_type = item.get("type", item.get("category", "concept"))
        type_counts[wiki_type] = type_counts.get(wiki_type, 0) + 1

        created = item.get("created", "")
        if hasattr(created, "strftime"):
            date = created.strftime("%Y-%m-%d")
        elif isinstance(created, str):
            date = created[:10]
        else:
            date = "unknown"
        if date not in date_groups:
            date_groups[date] = {"date": date, "count": 0, "types": {}, "titles": [], "top_score": 0.0}
        g = date_groups[date]
        g["count"] += 1
        g["types"][wiki_type] = g["types"].get(wiki_type, 0) + 1
        g["titles"].append(item.get("title", item["slug"]))
        g["top_score"] = max(g["top_score"], item.get("score", 0))

    dates = sorted(date_groups.values(), key=lambda x: x["date"], reverse=True)
    for g in dates:
        g["titles"] = g["titles"][:5]

    quality_avg = round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0.0

    return {
        "tiers": tier_counts,
        "quality_avg": quality_avg,
        "total": len(all_pages),
        "pinned": pinned_count,
        "types": type_counts,
        "dates": dates,
    }
