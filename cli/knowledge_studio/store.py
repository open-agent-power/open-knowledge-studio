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
import threading
import time
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

_windows_lock_registry_guard = threading.Lock()
_windows_thread_locks: dict[str, threading.RLock] = {}


def _windows_thread_lock(lock_path: Path) -> threading.RLock:
    """Serialize same-process callers before entering the Windows CRT lock."""
    key = os.path.normcase(str(lock_path.resolve()))
    with _windows_lock_registry_guard:
        return _windows_thread_locks.setdefault(key, threading.RLock())

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
    thread_lock = _windows_thread_lock(lock_path) if msvcrt is not None else None
    if thread_lock is not None:
        # The CRT can report Resource deadlock avoided when two threads in one
        # process lock the same byte through separate file handles. Keep the
        # OS lock for cross-process coordination, but serialize local callers.
        thread_lock.acquire()
    try:
        if msvcrt is not None:
            _ensure_windows_lock_file(lock_path)
        handle = lock_path.open("r+b" if msvcrt is not None else "a+b")
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
    finally:
        if thread_lock is not None:
            thread_lock.release()


def _ensure_windows_lock_file(lock_path: Path) -> None:
    """Create the byte used by ``msvcrt.locking`` without a first-use race."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_BINARY", 0)
    for _ in range(100):
        try:
            fd = os.open(str(lock_path), flags)
        except FileExistsError:
            try:
                if lock_path.stat().st_size >= 1:
                    return
            except FileNotFoundError:
                continue
            time.sleep(0.01)
        else:
            try:
                os.write(fd, b"\0")
            finally:
                os.close(fd)
            return
    # A zero-byte lock left by an interrupted initializer is safe to repair
    # once no concurrent initializer is still publishing the sentinel.
    with lock_path.open("r+b") as seed:
        if seed.seek(0, os.SEEK_END) == 0:
            seed.write(b"\0")
            seed.flush()


def _atomic_write(path: Path, content: str | bytes) -> None:
    """Write a snapshot with fsync + atomic replace + directory fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
    try:
        with os.fdopen(fd, "wb" if isinstance(content, bytes) else "w", **({} if isinstance(content, bytes) else {"encoding": "utf-8", "newline": ""})) as f:
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

    return _parse_wiki_text(text, path)


def _parse_wiki_text(text: str, path: Path) -> dict | None:

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
    canonical = content.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


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
    """Set one frontmatter field under the target page's lock.

    The whole file is rewritten, so the read/modify/write has to be atomic
    against other writers. An unlocked caller reads a snapshot, and a concurrent
    update that lands in between is silently dropped when that snapshot is
    written back — two processes each touching a different field of the same
    page would lose one another's change. ``record_access`` locks its own
    read/modify/write the same way for the same reason.
    """
    with _file_lock(file_path.with_name(f".{file_path.name}.lock")):
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
    path = _access_log_path()
    # Keep the lock across the complete read/modify/write transaction. The
    # snapshot writer is atomic by itself, but locking only the final write
    # would still let concurrent readers overwrite one another's increments.
    with _file_lock(path.with_name(f".{path.name}.lock")):
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


def _validate_score(field: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{field} must be a number between 0 and 1, got {value!r}")


def _merge_worker_records(file_path: Path, incoming: list[dict]) -> None:
    from knowledge_studio.worker_records import merge_records

    def update(text: str) -> str:
        parts = text.split("---", 2)
        if len(parts) != 3:
            raise ValueError("Cannot preserve Worker sources without valid frontmatter")
        meta = yaml.safe_load(parts[1].strip()) or {}
        if not isinstance(meta, dict):
            raise ValueError("Cannot preserve Worker sources in invalid frontmatter")
        meta["worker_records"] = merge_records(meta.get("worker_records"), incoming)
        front = yaml.safe_dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return f"---\n{front}---{parts[2]}"

    _locked_atomic_update(file_path, update)


_CANDIDATE_EVIDENCE_FIELDS = (
    "source_url", "source_bundle_id", "source_raw_bundle", "source_article_date",
    "source_capture_id", "agent_observation", "claim_ids", "evidence_refs",
    "source_candidates", "workflow_source", "reviewed_source", "workflow_reviews",
)


def _merge_candidate_metadata(current: dict, incoming: dict) -> dict:
    merged = {}
    for key in ("summary", *_CANDIDATE_EVIDENCE_FIELDS):
        if key not in incoming:
            continue
        value = incoming[key]
        if key == "summary":
            if not isinstance(value, str):
                raise ValueError("Candidate summary must be a string; candidate retained")
        elif key in {"claim_ids", "evidence_refs", "source_candidates", "workflow_reviews"}:
            if not isinstance(value, list) or not isinstance(current.get(key, []), list):
                raise ValueError(f"Invalid {key}; candidate retained")
            existing = list(current.get(key, []))
            if key == 'workflow_reviews' and not existing and isinstance(current.get('reviewed_source'), dict):
                existing.append({'workflow_source': current.get('workflow_source'), 'reviewed_source': current['reviewed_source'], 'reviewed_at': current.get('human_reviewed_at')})
            value = existing + [item for item in value if item not in existing]
        elif key in {'workflow_source', 'reviewed_source'}:
            if not isinstance(value, dict):
                raise ValueError(f'Matching content has conflicting {key}; Draft retained')
            if current.get(key) not in (None, value):
                if not isinstance(incoming.get('workflow_reviews'), list):
                    raise ValueError(f'Matching content has conflicting {key}; Draft retained')
                value = current[key]  # Old readers keep the first approved origin.
        elif current.get(key) not in (None, "", value):
            raise ValueError(f"Matching content has conflicting {key}; review its sources explicitly; candidate retained")
        merged[key] = value
    return merged


def write_wiki_page(
    title: str,
    content: str,
    wiki_type: str = "concepts",
    area: str = "computing",
    source_type: str = "auto",
    importance: float | None = None,
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
    confidence: float | None = None,
    default_importance: float = 0.5,
    enforce_classification: bool = False,
    subdirectory: str | None = None,
    skill_metadata: dict | None = None,
    worker_records: list[dict] | None = None,
    candidate_metadata: dict | None = None,
) -> Path:
    from knowledge_studio.decisions import validate_options
    validate_options(options)
    candidate_metadata = _merge_candidate_metadata({}, candidate_metadata or {})
    for field, value in (("importance", importance), ("confidence", confidence)):
        if value is not None:
            _validate_score(field, value)
    _validate_score("default_importance", default_importance)
    if enforce_classification:
        from knowledge_studio.knowledge_policy import validate_classification
        area, wiki_type = validate_classification(
            area, wiki_type, skill=bool(skill_metadata and skill_metadata.get("artifact_kind") == "skill")
        )
    from knowledge_studio.worker_records import clean_records
    worker_records = clean_records(worker_records)
    if not re.fullmatch(r"[a-z][a-z0-9-]*", area):
        raise ValueError(
            f"Invalid area name: {area!r}. "
            "Area must be a lowercase identifier (letters, digits, hyphens only)."
        )
    if skill_metadata is not None:
        from knowledge_studio.skills import validate_skill_metadata, _inside, SKILL_FIELDS
        validate_skill_metadata(skill_metadata)
        if area != "skills" or subdirectory != skill_metadata["skill_category"]:
            raise ValueError("Skill knowledge requires its independent area and category")
        _inside(repo_root().resolve(), f"wiki/{area}/{wiki_type}/{subdirectory}")
    fp = _fingerprint(content)
    fp_index = _load_fingerprint_index()
    existing_slug = fp_index.get(fp)
    if existing_slug:
        existing = _find_file_by_slug(existing_slug)
        if existing:
            if skill_metadata is not None:
                old = parse_wiki_file(existing) or {}
                expected_dir = wiki_dir() / area / wiki_type / subdirectory
                if existing.parent != expected_dir or any(old.get(key) != skill_metadata.get(key)
                        for key in ("artifact_kind", "skill_id", "skill_version", "skill_category", "skill_lineage")):
                    raise ValueError("Skill content matches another Wiki identity; keep classifications distinct")
            if enforce_classification:
                from knowledge_studio.knowledge_policy import is_source_material, TYPE_DIRS
                previous = parse_wiki_file(existing) or {}
                if (is_source_material(previous) or previous.get("area") != area
                        or TYPE_DIRS.get(previous.get("type")) != wiki_type):
                    raise ValueError("Matching content has a different classification or is source material; candidate retained. Review the existing page explicitly.")
            # Reject conflicting provenance before changing review/score state.
            # Merge only explicit candidate fields, never arbitrary draft state.
            if candidate_metadata or options is not None:
                def merge_metadata(text):
                    parts = text.split("---", 2)
                    meta = yaml.safe_load(parts[1]) or {}
                    if options is not None and meta.get("options") is not None and meta["options"] != options:
                        raise ValueError("Matching content has conflicting options; candidate retained. Review the existing decisions explicitly.")
                    meta.update(_merge_candidate_metadata(meta, candidate_metadata))
                    if options is not None:
                        meta["options"] = options
                    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + parts[2]
                _locked_atomic_update(existing, merge_metadata)
            # Dedup must not swallow what the caller newly established. A human
            # approving a draft whose body matches an existing page used to lose
            # the review, the active status and the declared A4 relationship —
            # and promote_draft then deleted the draft, so it was unrecoverable.
            # An explicit assessment takes precedence over reconfirmation.
            # Repeating a low-confidence draft must not inflate its confidence.
            if confidence is None:
                _reinforce_on_reconfirmation(existing_slug)
            else:
                _update_frontmatter_field(existing, "confidence", confidence)
            if human_reviewed:
                if importance is not None:
                    _update_frontmatter_field(existing, "importance", importance)
                _update_frontmatter_field(
                    existing, "human_reviewed_at", datetime.now(UTC).isoformat()
                )
                _update_frontmatter_field(existing, "status", "active")
                if enforce_classification:
                    _update_frontmatter_field(existing, "classification_version", 1)
            if supersedes and not relates_to:
                relates_to, relationship = supersedes, "supersedes"
            _apply_relationship(relates_to or "", relationship or "", existing_slug)
            if worker_records:
                _merge_worker_records(existing, worker_records)
            return existing

    wd = wiki_dir()
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    type_dir = wd / area / wiki_type
    if subdirectory:
        from knowledge_studio.skills import validate_category
        subdirectory = validate_category(subdirectory)
        type_dir = type_dir / subdirectory
        if not type_dir.resolve().is_relative_to(wd.resolve()):
            raise ValueError("Wiki subdirectory escapes the knowledge base")
    type_dir.mkdir(parents=True, exist_ok=True)

    if skill_metadata is not None:
        # Put a digest first: make_slug's length bound must not erase version/category
        # identity, and slugs must stay unique across nested Wiki directories.
        identity = f"{skill_metadata['skill_id']}:{skill_metadata['skill_version']}:{wiki_type}:{subdirectory}"
        unique = hashlib.sha256(identity.encode()).hexdigest()[:16]
        slug = make_slug(f"skill-{unique}-{skill_metadata['skill_id']}")
    else:
        slug = make_slug(slug_hint or title, fallback="untitled")
    slug = f"{date_str}-{slug}"

    file_path = type_dir / f"{slug}.md"
    counter = 1
    while file_path.exists():
        file_path = type_dir / f"{slug}-{counter}.md"
        counter += 1
    slug = file_path.stem

    if supersedes and not relates_to:
        relates_to = supersedes
        relationship = "supersedes"

    if skill_metadata is None:
        _apply_relationship(relates_to or "", relationship or "", slug)

    frontmatter: dict = {
        "title": title,
        "type": wiki_type[:-3] + "y" if wiki_type.endswith("ies") else wiki_type.rstrip("s"),
        "area": area,
        "status": "active" if human_reviewed else "provisional",
        "source_type": source_type,
        "importance": default_importance if importance is None else importance,
        "confidence": 0.8 if confidence is None else confidence,
        "created": now.isoformat(),
        "pinned": False,
        "archived": False,
        "tags": ", ".join(tags) if tags else "",
        "fingerprint": fp,
    }
    if options is not None:
        frontmatter["options"] = options
    frontmatter.update(candidate_metadata)
    if human_reviewed:
        frontmatter["human_reviewed_at"] = now.isoformat()
        if enforce_classification:
            frontmatter["classification_version"] = 1
    if traces:
        frontmatter["traces"] = traces
    if review:
        frontmatter["review"] = review
    if worker_records:
        frontmatter["worker_records"] = worker_records
    if human_note:
        frontmatter["human_note"] = human_note
    if relates_to and relationship:
        frontmatter["relates_to"] = relates_to
        frontmatter["relationship"] = relationship
    if skill_metadata is not None:
        frontmatter.update({key: skill_metadata[key] for key in SKILL_FIELDS if key in skill_metadata})

    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _atomic_write(file_path, f"---\n{fm_str}---\n\n{content}")
    if skill_metadata is not None:
        # Keep the last usable approved version active if writing its replacement
        # fails. The replacement must exist before the old card is superseded.
        _apply_relationship(relates_to or "", relationship or "", slug)

    # Re-read under the lock rather than saving the snapshot loaded before the
    # page was written. Two writers racing here would each save their pre-race
    # snapshot, and the loser's ``fp -> slug`` mapping would be gone for good —
    # that content then loses duplicate protection permanently.
    with _file_lock(_fingerprint_index_path().with_name(".fingerprints.json.lock")):
        index = _load_fingerprint_index()
        index[fp] = slug
        _save_fingerprint_index(index)

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
    from .task_workflow import _promotions, _rejections, candidate_disposition
    from . import draft_review
    promotions, rejections = _promotions(repo_root()), _rejections(repo_root())
    for f in sorted(dd.glob("*.md")):
        relative = f.relative_to(repo_root()).as_posix()
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if (candidate_disposition(repo_root(), relative, raw=raw, promotions=promotions, rejections=rejections)
                or draft_review.disposition(repo_root(), relative, hashlib.sha256(raw).hexdigest())):
            continue
        meta = parse_wiki_file(f)
        if not meta:
            continue
        drafts.append({
            "slug": meta["slug"],
            "title": meta.get("title", meta["slug"]),
            "draft_type": meta.get("draft_type") or "待确认",
            "draft_area": meta.get("draft_area") or "待确认",
            "source_pages": meta.get("source_pages", []),
            "drafted_at": meta.get("drafted_at", ""),
            "status": meta.get("status", "draft"),
            "body": meta.get("body", ""),
        })
    return drafts


def read_draft(slug: str) -> str:
    """Return a draft's original Markdown for human review.

    Review must happen against the exact Candidate artifact, including its
    frontmatter and provenance fields.  Keep this read-only helper separate
    from ``list_drafts`` so callers do not have to reconstruct Markdown from
    parsed YAML and lose fields they need to inspect.
    """
    draft_path = _draft_path(slug)
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")
    content = draft_path.read_text(encoding="utf-8")
    if not parse_wiki_file(draft_path):
        raise ValueError(
            f"Draft '{slug}' has no valid YAML frontmatter. "
            f"Drafts must start with '---' and contain title, type, and area fields."
        )
    return content


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
    *,
    expected_sha256: str | None = None,
) -> str:
    from . import draft_review
    draft_review._safe_slug(slug)
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)):
        raise ValueError('Read the exact Draft revision before promotion')
    # CLI and exact-revision reviews share one slug lock and immutable input.
    with draft_review.review_lock(repo_root(), slug):
        snapshot = draft_review.capture(repo_root(), slug)
        if expected_sha256 is not None and snapshot['sha256'] != expected_sha256:
            raise ValueError('Draft changed; read it again before promotion')
        if draft_review.disposition(repo_root(), snapshot['relative'], snapshot['sha256']):
            raise ValueError('Draft revision already reviewed; edit it before another decision')
        return _reviewed_promotion(slug, title, wiki_type, area, tags, slug_hint,
                                   snapshot['text'], snapshot['raw'])


def _reviewed_promotion(slug, title, wiki_type, area, tags, slug_hint, reviewed_text=None, reviewed_bytes=None):
    from knowledge_studio.feedback import export_guard
    snapshot_meta = _parse_wiki_text(reviewed_text, _draft_path(slug)) if reviewed_text is not None else None
    with export_guard(repo_root(), _draft_path(slug), reviewed_meta=snapshot_meta):
        # Re-read under the feedback guard; Skill review keeps its existing lock.
        meta = snapshot_meta if snapshot_meta is not None else parse_wiki_file(_draft_path(slug)) or {}
        if meta.get("artifact_kind") == "skill":
            from knowledge_studio.skills import _inside, _root
            with _file_lock(_inside(_root(), ".oks/locks/skills.lock")):
                return _promote_draft(slug, title, wiki_type, area, tags, slug_hint, reviewed_text=reviewed_text, reviewed_bytes=reviewed_bytes)
        return _promote_draft(slug, title, wiki_type, area, tags, slug_hint, reviewed_text=reviewed_text, reviewed_bytes=reviewed_bytes)


def _promote_draft(
    slug: str,
    title: str | None = None,
    wiki_type: str | None = None,
    area: str | None = None,
    tags: list[str] | None = None,
    slug_hint: str | None = None,
    *,
    reviewed_text: str | None = None,
    reviewed_bytes: bytes | None = None,
) -> str:
    draft_path = _draft_path(slug)
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")

    if reviewed_text is None:
        reviewed_bytes = draft_path.read_bytes()
        reviewed_text = reviewed_bytes.decode('utf-8-sig')
    meta = _parse_wiki_text(reviewed_text, draft_path)
    if not meta:
        raise ValueError(
            f"Draft '{slug}' has no valid YAML frontmatter. "
            f"Drafts must start with '---' and contain title, type, and area fields."
        )
    if meta.get("status") == "rejected":
        raise ValueError(f"Draft '{slug}' was explicitly rejected and cannot be promoted.")
    if re.fullmatch(r'daily-learning-[0-9a-f]{28}', slug) and not meta.get('daily_sources'):
        raise ValueError('Daily learning sources missing; Draft retained')
    if meta.get('daily_sources'):
        from .daily_learning import validate_sources
        validate_sources(repo_root(), meta)
    body = meta.get("body", "")
    if not body.strip():
        raise ValueError(
            f"Draft '{slug}' has empty body. "
            f"Refusing to promote a draft with no content — check Candidate generation."
        )
    if re.fullmatch(r'task-learning-[0-9a-f]{28}', slug) and not isinstance(meta.get('workflow_source'), dict):
        raise ValueError('Task learning source markers missing; Draft retained')
    if meta.get('workflow_source'):
        from knowledge_studio.task_workflow import require_current_draft, preserve_review, candidate_disposition
        disposition = candidate_disposition(repo_root(), draft_path.relative_to(repo_root()).as_posix(), reviewed_bytes)
        if disposition == 'not_proposed':
            raise ValueError('No proposed learning content; original record retained')
        if disposition is not None:
            raise ValueError('Draft already reviewed; original evidence retained')
        require_current_draft(repo_root(), reviewed_text)
        meta['reviewed_source'] = preserve_review(repo_root(), draft_path.relative_to(repo_root()).as_posix(), reviewed_bytes if reviewed_bytes is not None else reviewed_text.encode('utf-8'))
        meta['workflow_reviews'] = [{'workflow_source': meta['workflow_source'], 'reviewed_source': meta['reviewed_source'], 'reviewed_at': datetime.now(UTC).isoformat()}]

    final_title = title or meta.get("title", slug)
    from knowledge_studio.knowledge_policy import is_source_material, validate_classification
    if is_source_material(meta):
        raise ValueError("Source material cannot be promoted directly. Distill a separate Candidate with source references, then review it; candidate retained.")
    final_area, final_type = validate_classification(
        area if area is not None else meta.get("draft_area"),
        wiki_type if wiki_type is not None else meta.get("draft_type"),
        skill=meta.get("artifact_kind") == "skill",
    )
    for field in ("importance", "confidence"):
        if field in meta:
            _validate_score(field, meta[field])
    if meta.get("artifact_kind") == "skill":
        if final_area != "skills":
            raise ValueError("Skill knowledge belongs under the independent skills area")
        from knowledge_studio.skills import entries, validate_skill_instruction_body
        validate_skill_instruction_body(meta, body, root=repo_root())
        lineage = meta.get("skill_lineage")
        if isinstance(lineage, dict) and isinstance(lineage.get("parents"), list) and len(lineage["parents"]) == 2:
            from knowledge_studio.skills import validate_skill_merge_parents
            validate_skill_merge_parents(repo_root(), lineage)
        # Several candidates may have been imported against the same old version.
        # Link to the active reviewed baseline at approval time, not import time.
        canonical_type = {"concepts": "concept", "strategies": "strategy", "anti-patterns": "anti-pattern"}[final_type]
        if meta.get("relationship") == "supersedes":
            meta.pop("relates_to", None)
            meta.pop("relationship", None)
        meta.pop("supersedes", None)
        baseline = [p for p in entries(include_drafts=False)
                    if p.get("skill_id") == meta.get("skill_id")
                    and p.get("type") == canonical_type
                    and p.get("skill_category") == meta.get("skill_category")
                    and p.get("skill_version") != meta.get("skill_version")
                    and p.get("status") == "active" and p.get("human_reviewed_at")]
        if len(baseline) > 1:
            raise ValueError("Multiple active Skill baselines; review and resolve them before promotion")
        if baseline:
            meta.update(relates_to=baseline[0]["slug"], relationship="supersedes")
    human_note = meta.get("source_note") or None

    draft_tags = meta.get("tags", [])
    if isinstance(draft_tags, str):
        draft_tags = [item.strip() for item in draft_tags.split(",") if item.strip()]
    if not isinstance(draft_tags, list):
        draft_tags = []

    if not meta.get('workflow_source'):
        # Preserve exact review evidence before writing Wiki. If the canonical
        # Draft decision receipt later fails, the reviewed Wiki metadata and
        # this content-addressed original together recover the decision.
        from . import draft_review
        raw_for_review = reviewed_bytes if reviewed_bytes is not None else reviewed_text.encode('utf-8')
        review_proof = draft_review.preserve_original(
            repo_root(), draft_path.relative_to(repo_root()).as_posix(), raw_for_review)
        meta['workflow_reviews'] = [{
            'workflow_source': None,
            'reviewed_source': review_proof,
            'reviewed_at': datetime.now(UTC).isoformat(),
        }]

    path = write_wiki_page(
        title=final_title,
        content=body,
        wiki_type=final_type,
        area=final_area,
        source_type=meta.get("source_type", "auto"),
        importance=meta.get("importance"),
        confidence=meta.get("confidence"),
        default_importance=0.7,
        tags=tags if tags is not None else draft_tags,
        options=meta.get("options"),
        traces=meta.get("traces") if isinstance(meta.get("traces"), list) else None,
        review=meta.get("review") if isinstance(meta.get("review"), dict) else None,
        human_note=human_note,
        slug_hint=slug_hint,
        # A3: reaching here means a human approved the draft. Recording it is
        # what lets recall label the page [verified] honestly.
        human_reviewed=True,
        enforce_classification=True,
        # A4: carry the declared relationship through, otherwise the superseded
        # page stays active and both versions get recalled side by side.
        supersedes=meta.get("supersedes"),
        relates_to=meta.get("relates_to"),
        relationship=meta.get("relationship"),
        subdirectory=meta.get("skill_category") if meta.get("artifact_kind") == "skill" else None,
        skill_metadata=meta if meta.get("artifact_kind") == "skill" else None,
        worker_records=meta.get("worker_records"),
        candidate_metadata={**{key: meta[key] for key in ("summary", *_CANDIDATE_EVIDENCE_FIELDS) if key in meta},
                            "source_candidates": [draft_path.relative_to(repo_root()).as_posix()]},
    )

    if meta.get('workflow_source'):
        # An external editor need not honor our lock. Do not unlink a shared
        # path after checking it: a concurrent edit could otherwise be lost.
        # Exact reviewed bytes are excluded from pending projections; any new
        # bytes at this path remain a separate, unapproved revision.
        return path.stem
    from . import draft_review
    raw = reviewed_bytes if reviewed_bytes is not None else reviewed_text.encode('utf-8')
    draft_review.record_decision(repo_root(), slug, raw, 'promoted',
                                 wiki_path=path.relative_to(repo_root()).as_posix())
    return path.stem


def reject_draft(slug: str, *, expected_sha256: str | None = None) -> Path:
    from . import draft_review
    draft_review._safe_slug(slug)
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)):
        raise ValueError('Read the exact Draft revision before rejection')
    root = repo_root()
    with draft_review.review_lock(root, slug):
        snapshot = draft_review.capture(root, slug)
        if expected_sha256 is not None and snapshot['sha256'] != expected_sha256:
            raise ValueError('Draft changed; read it again before rejection')
        is_task_learning = bool(re.fullmatch(r'task-learning-[0-9a-f]{28}', slug))
        if is_task_learning:
            from .task_workflow import candidate_disposition
            disposition = candidate_disposition(root, snapshot['relative'], snapshot['raw'])
            if disposition == 'not_proposed':
                raise ValueError('No proposed learning content; original record retained')
            if disposition:
                raise ValueError('Draft already reviewed; original evidence retained')
            draft_meta = _parse_wiki_text(snapshot['text'], snapshot['path']) or {}
            task_receipt = {
                "decision": "rejected",
                "decided_at": datetime.now(UTC).isoformat(),
                "draft_slug": slug,
                "draft_title": draft_meta.get("title", slug),
                "draft_path": snapshot['relative'],
                "draft_sha256": hashlib.sha256(snapshot['text'].replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')).hexdigest(),
                "draft_bytes_sha256": snapshot['sha256'],
            }
            receipt_name = (f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-"
                            f"{slug}-{uuid.uuid4().hex[:12]}.json")
            receipt_path = drafts_dir() / "rejected" / receipt_name
            _atomic_write(receipt_path, json.dumps(task_receipt, ensure_ascii=False, indent=2) + "\n")
            return receipt_path
        if draft_review.disposition(root, snapshot['relative'], snapshot['sha256']):
            raise ValueError('Draft revision already reviewed; edit it before another decision')
        draft_meta = _parse_wiki_text(snapshot['text'], snapshot['path']) or {}
        original = draft_review.preserve_original(root, snapshot['relative'], snapshot['raw'])
        draft_content = snapshot['text'].replace('\r\n', '\n').replace('\r', '\n')
        receipt = {
            "decision": "rejected",
            "decided_at": datetime.now(UTC).isoformat(),
            "draft_slug": slug,
            "draft_title": draft_meta.get("title", slug),
            "draft_path": snapshot['relative'],
            "draft_sha256": hashlib.sha256(draft_content.encode('utf-8')).hexdigest(),
            "draft_bytes_sha256": snapshot['sha256'],
            "original": original,
        }
        receipt_name = (f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-"
                        f"{slug}-{uuid.uuid4().hex[:12]}.json")
        receipt_path = drafts_dir() / "rejected" / receipt_name
        record = draft_review.record_decision(root, slug, snapshot['raw'], 'rejected')
        receipt["decided_at"] = record["decided_at"]
        _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
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
