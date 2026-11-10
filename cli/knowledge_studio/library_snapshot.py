"""Project standard OKS buckets from an immutable, independently owned library.

No checkout or linked code imports. Catalog-backed libraries retain their exact
review receipts; ordinary OKS Wiki uses the same review metadata as local Wiki.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from datetime import datetime
import hashlib
import re
from urllib.parse import quote

import yaml

BUCKETS = ("raw", "drafts", "wiki", "skills", "profiles", "records")
TYPES = {"concept", "strategy", "anti-pattern"}


def _metadata(text):
    match = re.match(r"\A\ufeff?---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    meta = yaml.safe_load(match[1]) if match else {}
    if not isinstance(meta or {}, dict):
        raise ValueError("Library frontmatter must be a mapping")
    return meta or {}


def unified_snapshot(path, revision, repository, name, *, approved_only=False):
    from .linked_sources import _blob, _catalog_snapshot, _git, _has_blob

    manifest = {}
    if _has_blob(path, revision, "settings/library.yaml"):
        manifest = yaml.safe_load(_blob(path, revision, "settings/library.yaml"))
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                or manifest.get("layout") != "oks" or manifest.get("repository") != repository):
            raise ValueError("Invalid or mismatched library identity")
    entries = []
    cataloged = _has_blob(path, revision, "records/catalog/knowledge.yaml")
    if cataloged:
        entries = _catalog_snapshot(
            path, revision, repository, name, approved_only,
            catalog_path="records/catalog/knowledge.yaml",
            source_path=manifest.get("source_index", "raw/sources/index.json"), unified=True,
        )["entries"]
    indexed = {e["path"] for e in entries}
    listing = _git(path, "ls-tree", "-rz", "--full-tree", revision)
    regular = []
    for record in filter(None, listing.split(b"\0")):
        header, raw = record.split(b"\t", 1)
        mode, kind, _ = header.split()
        relative = raw.decode("utf-8")
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] not in BUCKETS or not relative.endswith(".md"):
            continue
        if any(part.startswith(".") for part in parts):
            continue
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            raise ValueError("Linked content must be a regular committed blob")
        regular.append(relative)
    if len(regular) > 2000:
        raise ValueError("Library exceeds 2000 Markdown entries")
    # A random repository is not a knowledge library.
    if not cataloged and not _has_blob(path, revision, "wiki"):
        raise ValueError("Linked repository has no standard Wiki")
    used_ids = {e["id"] for e in entries}
    for relative in sorted(regular):
        bucket = relative.split("/")[0]
        if relative in indexed or (cataloged and bucket in {"wiki", "drafts"}):
            continue
        if approved_only and bucket != "wiki":
            continue
        text = _blob(path, revision, relative).decode("utf-8")
        meta = _metadata(text)
        # Executable packages never enter knowledge recall as instructions.
        kind = "skills" if bucket == "wiki" and meta.get("skill_id") else bucket
        status = "candidate" if bucket == "drafts" else "reference"
        if bucket == "wiki":
            reviewed = meta.get("human_reviewed_at")
            if reviewed:
                datetime.fromisoformat(str(reviewed).replace("Z", "+00:00"))
            status = "approved" if reviewed else "candidate"
            if PurePosixPath(relative).name == "README.md" and not reviewed:
                status = "reference"
            if meta.get("archived") or meta.get("status") in {"archived", "deprecated", "rejected"}:
                status = "deprecated"
        if approved_only and (status != "approved" or kind != "wiki"):
            continue
        identifier = meta.get("id") or relative
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Invalid library document identity")
        identifier = f"team:{name}/{identifier}"
        if identifier in used_ids:
            raise ValueError("Duplicate library document identity")
        used_ids.add(identifier)
        title = meta.get("title")
        if not isinstance(title, str) or not title.strip():
            heading = re.search(r"^#\s+(.+)$", text, re.M)
            title = heading[1] if heading else PurePosixPath(relative).stem
        tags = meta.get("tags", meta.get("topics", []))
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise ValueError("Invalid library tags")
        digest = hashlib.sha256(text.encode()).hexdigest()
        knowledge_type = meta.get("type", meta.get("draft_type", "concept"))
        entries.append({
            "id": identifier, "slug": identifier, "title": title,
            "type": "team", "family": "team", "group": Path(path).name, "library_id": name,
            "asset_kind": kind, "knowledge_type": knowledge_type if knowledge_type in TYPES else "concept",
            "path": relative, "source_path": relative, "source_sha256": digest,
            "repository": repository, "revision": revision, "status": status,
            "pending": status == "candidate", "uses": 0, "tags": tags,
            "body": text, "read_only": True,
            "uri": f"oks://team/{name}/" + quote(relative, safe="/"),
            "url": f"https://github.com/{repository}/blob/{revision}/" + quote(relative, safe="/"),
            "approval_url": None, "evidence_url": None,
            "metadata": {**meta, "repository": repository, "revision": revision,
                         "status": status, "sha256": digest, "library": name},
        })
    return {"name": name, "repository": repository, "revision": revision,
            "layout": "oks", "entries": entries,
            "approved_count": sum(e["status"] == "approved" for e in entries),
            "candidate_count": sum(e["pending"] for e in entries)}
