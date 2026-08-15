"""Filesystem CRUD for wiki pages — pure file operations, no database.

Extracted from autpilot-web/backend/app/services/knowledge_distiller.py.
Removed KnowledgeStore, settings, and hook dispatcher dependencies.
Repo root resolved via OKS_ROOT env var or current working directory.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None

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
    """Thin delegate — config.get_kb_root() is the single root resolver."""
    from knowledge_studio.config import get_kb_root

    return get_kb_root()


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


def load_goals(*, active_only: bool = False) -> list[dict]:
    """Return normalized goal profiles.

    Domains and keywords are lowercased sets so recall can match them without
    repeating normalization. Explicit goal selection may use an inactive goal
    for a reproducible historical evaluation; the default recall path still
    calls :func:`load_active_goals` and only sees active goals.
    """
    gd = goals_dir()
    if not gd.exists():
        return []

    goals: list[dict] = []
    for path in sorted(gd.rglob("*.md")):
        meta = parse_wiki_file(path)
        if not meta:
            continue
        if meta.get("type") != "goal":
            continue
        status = str(meta.get("status", "active")).lower().strip()
        if active_only and status != "active":
            continue
        goals.append({
            "slug": meta.get("slug", path.stem),
            "title": meta.get("title", path.stem),
            "status": status,
            "domains": _as_str_set(meta.get("domains")),
            "keywords": _as_str_set(meta.get("keywords")),
        })
    return goals


def load_active_goals() -> list[dict]:
    """Return active goals used by the default goal-aware recall mode."""
    return load_goals(active_only=True)


def get_goal(slug: str) -> dict | None:
    """Return one goal by slug, regardless of status."""
    wanted = slug.lower().strip()
    return next(
        (goal for goal in load_goals() if str(goal.get("slug", "")).lower() == wanted),
        None,
    )


def _access_log_path() -> Path:
    # Read-only: no mkdir here. Writers go through _atomic_write, which
    # creates the parent directory.
    return repo_root() / ".oks" / "access.json"


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


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    """Serialize a local read/modify/write or append sequence."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            handle.seek(0)
            with contextlib.suppress(OSError):
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def _atomic_write(path: Path, content: str) -> None:
    """Write a snapshot with fsync + atomic replace + directory fsync."""
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


def _append_jsonl(
    path: Path,
    record: dict,
    *,
    lock_path: Path | None = None,
) -> None:
    """Append one JSON record under a lock and fsync the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path or path.with_name(f".{path.name}.lock")
    with _file_lock(lock):
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _locked_atomic_update(
    path: Path,
    update: Callable[[str], str | None],
    *,
    lock_path: Path | None = None,
) -> bool:
    """Run a text read/modify/write under one lock and atomic replacement."""
    lock = lock_path or path.with_name(f".{path.name}.lock")
    with _file_lock(lock):
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        updated = update(current)
        if updated is None:
            return False
        _atomic_write(path, updated)
        return True


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

    created_raw = meta.get("created", "")
    if isinstance(created_raw, datetime):
        created = created_raw
    elif isinstance(created_raw, date):
        created = datetime(created_raw.year, created_raw.month, created_raw.day)
    else:
        try:
            created = datetime.fromisoformat(str(created_raw))
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
    # Read-only: no mkdir here. Writers go through _atomic_write, which
    # creates the parent directory.
    return repo_root() / ".oks" / "fingerprints.json"


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


def _update_frontmatter_field(file_path: Path, field: str, value) -> bool:
    text = file_path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    try:
        meta = yaml.safe_load(parts[1].strip()) or {}
    except yaml.YAMLError:
        return False
    meta[field] = value
    new_fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _atomic_write(file_path, f"---\n{new_fm}---\n{parts[2]}")
    return True


def _reinforce_on_reconfirmation(slug: str) -> None:
    """Raise confidence when the same knowledge is independently re-derived.

    Only the duplicate-fingerprint path in :func:`write_wiki_page` calls this:
    arriving at an existing page again from new material is evidence about the
    content. Reading a page is not — see :func:`record_access`.
    """
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
    """Count a use. Deliberately does not touch confidence or status.

    Usage feeds ranking via ``compute_score``'s access_bonus. Letting it also
    raise confidence or promote provisional pages would mean a page nobody
    reviewed gets injected as ``[verified]`` after three reads.
    """
    counts = _load_access_counts()
    counts[slug] = counts.get(slug, 0) + 1
    _save_access_counts(counts)


def make_slug(title: str, fallback: str = "untitled") -> str:
    # Keep CJK characters so Chinese titles don't degrade to the fallback.
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", title.lower())[:60].strip("-")
    return slug or fallback


def _apply_relationship(relates_to: str, relationship: str, new_slug: str) -> None:
    """Record an A4 relationship on the older page.

    Skips a self-referential target: after fingerprint dedup the "new" page can
    be the very page the draft declared it supersedes, and a page cannot
    supersede itself.
    """
    if not relates_to or not relationship or relates_to == new_slug:
        return
    old_file = _find_file_by_slug(relates_to)
    if not old_file:
        return
    if relationship == "supersedes":
        _update_frontmatter_field(old_file, "status", "superseded")
        _update_frontmatter_field(old_file, "superseded_by", new_slug)
    elif relationship == "enriches":
        _update_frontmatter_field(old_file, "enriched_by", new_slug)
    elif relationship == "confirms":
        old_meta = parse_wiki_file(old_file)
        if old_meta:
            current_conf = old_meta.get("confidence", 0.8)
            new_conf = min(1.0, current_conf + 0.1)
            _update_frontmatter_field(old_file, "confidence", round(new_conf, 4))
        _update_frontmatter_field(old_file, "confirmed_by", new_slug)
    elif relationship == "challenges":
        _update_frontmatter_field(old_file, "status", "stale")
        _update_frontmatter_field(old_file, "challenged_by", new_slug)


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
    slug_hint: str | None = None,
    human_reviewed: bool = False,
) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", area):
        raise ValueError(
            f"Invalid area name: {area!r}. "
            "Area must be a lowercase identifier (letters, digits, hyphens only)."
        )
    fp = _fingerprint(content)
    fp_index = _load_fingerprint_index()
    existing_slug = fp_index.get(fp)
    if existing_slug:
        existing = _find_file_by_slug(existing_slug)
        if existing:
            # Dedup must not swallow what the caller newly established. A human
            # approving a draft whose body matches an existing page used to lose
            # the review, the active status and the declared A4 relationship —
            # and promote_draft then deleted the draft, so it was unrecoverable.
            _reinforce_on_reconfirmation(existing_slug)
            if human_reviewed:
                _update_frontmatter_field(
                    existing, "human_reviewed_at", datetime.now(UTC).isoformat()
                )
                _update_frontmatter_field(existing, "status", "active")
            if supersedes and not relates_to:
                relates_to, relationship = supersedes, "supersedes"
            _apply_relationship(relates_to or "", relationship or "", existing_slug)
            return existing

    wd = wiki_dir()
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    type_dir = wd / area / wiki_type
    type_dir.mkdir(parents=True, exist_ok=True)

    slug = make_slug(slug_hint or title, fallback="untitled")
    slug = f"{date_str}-{slug}"

    file_path = type_dir / f"{slug}.md"
    counter = 1
    while file_path.exists():
        file_path = type_dir / f"{slug}-{counter}.md"
        counter += 1

    if supersedes and not relates_to:
        relates_to = supersedes
        relationship = "supersedes"

    _apply_relationship(relates_to or "", relationship or "", slug)

    frontmatter: dict = {
        "title": title,
        "type": wiki_type[:-3] + "y" if wiki_type.endswith("ies") else wiki_type.rstrip("s"),
        "area": area,
        "status": "active" if human_reviewed else "provisional",
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
    if human_reviewed:
        frontmatter["human_reviewed_at"] = now.isoformat()
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
    return _update_frontmatter_field(f, "pinned", True)


def archive_page(slug: str) -> bool:
    f = _find_file_by_slug(slug)
    if not f:
        return False
    dropped = _update_frontmatter_field(f, "status", "dropped")
    archived = _update_frontmatter_field(f, "archived", True)
    return dropped and archived


def unarchive_page(slug: str) -> bool:
    """Bring an archived page back into recall.

    CONSTITUTION A3 permits decay to archive without human review only because
    archiving is reversible. It is only reversible if this exists:
    ``compute_score`` returns 0.0 for ``status: dropped`` and recall filters it
    out, so without this the sole way back was editing the Markdown by hand.

    Returns to ``provisional``, not ``active`` — leaving the archive is not a
    human review, so the page must not gain active standing on the way out.
    """
    f = _find_file_by_slug(slug)
    if not f:
        return False
    restored = _update_frontmatter_field(f, "status", "provisional")
    unarchived = _update_frontmatter_field(f, "archived", False)
    return restored and unarchived


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


def _draft_path(slug: str) -> Path:
    if not slug or slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise ValueError(f"Invalid draft slug: {slug!r}")
    return drafts_dir() / f"{slug}.md"


def promote_draft(
    slug: str,
    title: str | None = None,
    wiki_type: str | None = None,
    area: str | None = None,
    tags: list[str] | None = None,
    slug_hint: str | None = None,
) -> str:
    draft_path = _draft_path(slug)
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")

    meta = parse_wiki_file(draft_path)
    if not meta:
        raise ValueError(
            f"Draft '{slug}' has no valid YAML frontmatter. "
            f"Drafts must start with '---' and contain title, type, and area fields."
        )
    if meta.get("status") == "rejected":
        raise ValueError(f"Draft '{slug}' was explicitly rejected and cannot be promoted.")
    body = meta.get("body", "")
    if not body.strip():
        raise ValueError(
            f"Draft '{slug}' has empty body. "
            f"Refusing to promote a draft with no content — check Candidate generation."
        )

    final_title = title or meta.get("title", slug)
    requested_type = wiki_type or meta.get("draft_type", "concept")
    _type_dirs = {
        "concept": "concepts", "concepts": "concepts",
        "strategy": "strategies", "strategies": "strategies",
        "anti-pattern": "anti-patterns", "anti-patterns": "anti-patterns",
    }
    final_type = _type_dirs.get(requested_type)
    if final_type is None:
        raise ValueError(f"Unsupported Wiki type: {requested_type}")
    final_area = area or meta.get("draft_area", "computing")
    human_note = meta.get("source_note") or None

    draft_tags = meta.get("tags", [])
    if isinstance(draft_tags, str):
        draft_tags = [item.strip() for item in draft_tags.split(",") if item.strip()]
    if not isinstance(draft_tags, list):
        draft_tags = []

    path = write_wiki_page(
        title=final_title,
        content=body,
        wiki_type=final_type,
        area=final_area,
        source_type=meta.get("source_type", "auto"),
        importance=0.7,
        tags=tags if tags is not None else draft_tags,
        traces=meta.get("traces") if isinstance(meta.get("traces"), list) else None,
        review=meta.get("review") if isinstance(meta.get("review"), dict) else None,
        human_note=human_note,
        slug_hint=slug_hint,
        # A3: reaching here means a human approved the draft. Recording it is
        # what lets recall label the page [verified] honestly.
        human_reviewed=True,
        # A4: carry the declared relationship through, otherwise the superseded
        # page stays active and both versions get recalled side by side.
        supersedes=meta.get("supersedes"),
        relates_to=meta.get("relates_to"),
        relationship=meta.get("relationship"),
    )

    draft_path.unlink()
    return path.stem


def reject_draft(slug: str) -> Path:
    dd = drafts_dir()
    draft_path = _draft_path(slug)
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")

    draft_content = draft_path.read_text(encoding="utf-8")
    draft_meta = parse_wiki_file(draft_path) or {}
    decided_at = datetime.now(UTC).isoformat()
    receipt = {
        "decision": "rejected",
        "decided_at": decided_at,
        "draft_slug": slug,
        "draft_title": draft_meta.get("title", slug),
        "draft_path": str(draft_path.relative_to(repo_root())),
        "draft_sha256": hashlib.sha256(draft_content.encode("utf-8")).hexdigest(),
    }
    receipt_name = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{slug}-{uuid.uuid4().hex[:12]}.json"
    )
    receipt_path = dd / "rejected" / receipt_name
    _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    draft_path.unlink()
    return receipt_path


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
