"""Exact-version decisions for ordinary Draft artifacts.

Draft files remain in place after review. Decisions and preserved originals are
content-addressed so a later edit at the same path becomes a fresh Candidate.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def _store():
    from . import store
    return store


def _inside(root: Path, relative: str) -> Path:
    from .tasks import _inside as inside
    return inside(Path(root).resolve(), relative)


def _safe_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug or slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise ValueError(f"Invalid draft slug: {slug!r}")
    return slug


def lock_path(root: Path, slug: str) -> Path:
    _safe_slug(slug)
    key = hashlib.sha256(slug.encode("utf-8")).hexdigest()
    return _inside(root, f".oks/locks/draft-review-{key}.lock")


@contextmanager
def review_lock(root: Path, slug: str):
    with _store()._file_lock(lock_path(root, slug)):
        yield


def capture(root: Path, slug: str) -> dict:
    """Read one exact Draft revision; digest always covers original bytes."""
    slug = _safe_slug(slug)
    path = _inside(root, f"drafts/{slug}.md")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    return {"path": path, "relative": f"drafts/{slug}.md", "raw": raw,
            "text": text, "sha256": hashlib.sha256(raw).hexdigest()}


def _receipt_path(root: Path, slug: str, sha256: str) -> Path:
    key = hashlib.sha256(slug.encode("utf-8")).hexdigest()
    return _inside(root, f".oks/draft-reviews/{key}/{sha256}.json")


def preserve_original(root: Path, relative: str, raw: bytes) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    relative_snapshot = f".oks/reviewed-drafts/{digest}.md"
    path = _inside(root, relative_snapshot)
    store = _store()
    with store._file_lock(path.with_suffix(".lock")):
        if path.exists() and path.read_bytes() != raw:
            raise ValueError("Original Draft evidence changed; review retained")
        if not path.exists():
            store._atomic_write(path, raw)
    return {"path": relative_snapshot, "sha256": digest, "candidate_path": relative}


def _recover_promotion(root: Path, slug: str, sha256: str) -> dict | None:
    """Recover a promoted decision from its exact reviewed Wiki evidence."""
    if slug.startswith("task-learning-"):
        return None  # Task-learning keeps its own projection and receipt contract.
    expected_relative = f"drafts/{slug}.md"
    original = {"path": f".oks/reviewed-drafts/{sha256}.md", "sha256": sha256,
                "candidate_path": expected_relative}
    from .task_workflow import _promotions
    from . import store
    matches = _promotions(root).get(expected_relative, [])
    exact = [item for item in matches
             if isinstance(item.get("reviewed_source"), dict)
             and item["reviewed_source"] == original]
    for item in exact:
        wiki_path = item.get("wiki_path")
        if not isinstance(wiki_path, str) or not wiki_path.startswith("wiki/"):
            continue
        try:
            page_path = _inside(root, wiki_path)
            meta = store.parse_wiki_file(page_path) or {}
        except (OSError, ValueError, TypeError):
            continue
        if (not meta.get("human_reviewed_at")
                or expected_relative not in (meta.get("source_candidates") or [])):
            continue
        proof = meta.get("reviewed_source")
        reviews = meta.get("workflow_reviews")
        if proof != original and not (isinstance(reviews, list) and any(
                isinstance(entry, dict) and entry.get("reviewed_source") == original
                for entry in reviews)):
            continue
        if read_original(root, {"draft_path": expected_relative, "draft_sha256": sha256,
                                "original": original}) is None:
            raise ValueError("Promoted Draft original is missing or mismatched; keep the Draft for review")
        return {"schema_version": "oks-draft-review/v1", "draft_slug": slug,
                "draft_path": expected_relative, "draft_sha256": sha256,
                "decision": "promoted", "decided_at": item.get("reviewed_at") or meta["human_reviewed_at"],
                "original": original, "wiki_path": wiki_path}
    return None


def record_decision(root: Path, slug: str, raw: bytes, decision: str, *, wiki_path: str | None = None) -> dict:
    if decision not in {"promoted", "rejected"}:
        raise ValueError("Unsupported Draft decision")
    relative = f"drafts/{_safe_slug(slug)}.md"
    original = preserve_original(root, relative, raw)
    record = {"schema_version": "oks-draft-review/v1", "draft_slug": slug,
              "draft_path": relative, "draft_sha256": original["sha256"],
              "decision": decision, "decided_at": datetime.now(UTC).isoformat(),
              "original": original}
    if wiki_path is not None:
        record["wiki_path"] = wiki_path
    path = _receipt_path(root, slug, original["sha256"])
    store = _store()
    if path.exists():
        prior = read_receipt(root, slug, original["sha256"])
        if prior and prior.get("decision") != decision:
            raise ValueError("Draft revision already has the opposite decision")
        if prior:
            return prior
    store._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def read_receipt(root: Path, slug: str, sha256: str | None = None) -> dict | None:
    _safe_slug(slug)
    if sha256 is not None and (len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)):
        raise ValueError("Invalid Draft revision hash")
    if sha256 is None:
        folder = _inside(root, f".oks/draft-reviews/{hashlib.sha256(slug.encode('utf-8')).hexdigest()}")
        try:
            paths = sorted(folder.glob("*.json"))
        except OSError:
            return None
        receipts = [read_receipt(root, slug, path.stem) for path in paths
                    if re.fullmatch(r"[0-9a-f]{64}", path.stem)]
        receipts = [item for item in receipts if item is not None]
        return max(receipts, key=lambda item: item.get("decided_at", "")) if receipts else None
    path = _receipt_path(root, slug, sha256)
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _recover_promotion(root, slug, sha256)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("Draft review receipt is unreadable; keep the Draft for review") from exc
    if not isinstance(item, dict):
        raise ValueError("Draft review receipt is invalid; keep the Draft for review")
    original = item.get("original")
    expected_relative = f"drafts/{slug}.md"
    if (item.get("schema_version") != "oks-draft-review/v1"
            or item.get("draft_slug") != slug
            or item.get("draft_path") != expected_relative
            or item.get("draft_sha256") != sha256
            or item.get("decision") not in {"promoted", "rejected"}
            or not isinstance(item.get("decided_at"), str)
            or not isinstance(original, dict)
            or original.get("sha256") != sha256
            or original.get("path") != f".oks/reviewed-drafts/{sha256}.md"
            or original.get("candidate_path") != expected_relative):
        raise ValueError("Draft review receipt is invalid; keep the Draft for review")
    if item["decision"] == "promoted":
        wiki_path = item.get("wiki_path")
        if not isinstance(wiki_path, str) or not wiki_path.startswith("wiki/"):
            raise ValueError("Draft review receipt has an invalid Wiki path; keep the Draft for review")
        try:
            _inside(root, wiki_path)
        except (ValueError, OSError) as exc:
            raise ValueError("Draft review receipt has an invalid Wiki path; keep the Draft for review") from exc
    elif "wiki_path" in item:
        raise ValueError("Rejected Draft receipt cannot reference a Wiki page; keep the Draft for review")
    if read_original(root, item) is None:
        raise ValueError("Draft review original is missing or mismatched; keep the Draft for review")
    return item


def disposition(root: Path, relative: str, sha256: str) -> dict | None:
    if not relative.startswith("drafts/") or not relative.endswith(".md") or relative.count("/") != 1:
        return None
    slug = relative[len("drafts/"):-3]
    _safe_slug(slug)
    item = read_receipt(root, slug, sha256)
    return item


def read_original(root: Path, record: dict) -> bytes | None:
    proof = record.get("original")
    if not isinstance(proof, dict):
        return None
    digest, relative = proof.get("sha256"), proof.get("path")
    if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative != f".oks/reviewed-drafts/{digest}.md"):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("draft_sha256") != digest or proof.get("candidate_path") != record.get("draft_path"):
        return None
    try:
        path = _inside(root, relative)
    except (ValueError, OSError):
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw if hashlib.sha256(raw).hexdigest() == digest else None
