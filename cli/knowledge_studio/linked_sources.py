"""Read-only federation of independently maintained Git knowledge repositories.

Only committed blobs are read. No fetch, checkout, upstream Python execution,
file copying into Wiki, or interpretation of a merged PR as human approval.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote

import yaml

from . import store, tasks


def _git(path, *args):
    try:
        return subprocess.check_output(
            [
                "git",
                "--no-optional-locks",
                "--no-replace-objects",
                "-C",
                str(path),
                *args,
            ],
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "Linked repository is unavailable or revision cannot be read"
        ) from exc


def _relative(value):
    if not isinstance(value, str):
        raise ValueError("Expected a repository-relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(p in {"..", ".git"} for p in path.parts)
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("Unsafe linked path")
    return path.as_posix()


def _blob(path, revision, relative):
    relative = _relative(relative)
    record = _git(path, "ls-tree", "-z", revision, "--", relative)
    if not record or len(record.rstrip(b"\0").split(b"\0")) != 1:
        raise ValueError("Linked file is missing: " + relative)
    header, name = record.rstrip(b"\0").split(b"\t")
    mode, kind, oid = header.split()
    if (
        mode not in {b"100644", b"100755"}
        or kind != b"blob"
        or name.decode() != relative
    ):
        raise ValueError("Linked file must be a regular committed blob")
    size = int(_git(path, "cat-file", "-s", oid.decode()))
    if size > 2 * 1024 * 1024:
        raise ValueError("Linked file exceeds 2 MiB")
    return _git(path, "cat-file", "blob", oid.decode())


def configuration(root):
    target = tasks._inside(root, "settings/sources.yaml")
    value = yaml.safe_load(target.read_text()) if target.is_file() else {}
    if not isinstance(value or {}, dict):
        raise ValueError("Linked source configuration must be a mapping")
    rows = (value or {}).get("sources", [])
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError("Invalid linked source configuration")
    if any(
        not isinstance(row, dict)
        or not all(
            isinstance(row.get(k), str)
            for k in ("name", "path", "repository", "revision")
        )
        for row in rows
    ):
        raise ValueError("Invalid linked source entry")
    return rows


def link(root, name, path, repository, revision="HEAD"):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
        raise ValueError("Choose a source name of letters, numbers, _ or -")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Repository must be owner/name")
    path = Path(path).expanduser().resolve()
    if (
        path == root.resolve()
        or path.is_relative_to(root.resolve())
        or root.resolve().is_relative_to(path)
    ):
        raise ValueError(
            "Linked repositories must remain separate from the personal knowledge root"
        )
    if revision != "HEAD" and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use HEAD or a complete Git commit SHA")
    item = {
        "name": name,
        "path": str(path),
        "repository": repository,
        "revision": revision,
    }
    snapshot(item)  # Validate before writing personal configuration.
    with store._file_lock(tasks._inside(root, ".oks/locks/sources.lock")):
        rows = [s for s in configuration(root) if s["name"] != name] + [item]
        store._atomic_write(
            tasks._inside(root, "settings/sources.yaml"),
            yaml.safe_dump(
                {"schema_version": 1, "sources": rows},
                allow_unicode=True,
                sort_keys=False,
            ),
        )
    return item


def unlink(root, name):
    with store._file_lock(tasks._inside(root, ".oks/locks/sources.lock")):
        rows = [s for s in configuration(root) if s["name"] != name]
        store._atomic_write(
            tasks._inside(root, "settings/sources.yaml"),
            yaml.safe_dump(
                {"schema_version": 1, "sources": rows},
                allow_unicode=True,
                sort_keys=False,
            ),
        )
    return {"name": name, "status": "unlinked", "upstream_modified": False}


def snapshot(source, *, approved_only=False):
    path = Path(source["path"])
    revision = (
        _git(path, "rev-parse", "--verify", source["revision"] + "^{commit}")
        .decode()
        .strip()
    )
    # Cache only immutable commits; HEAD is resolved again on every request.
    return _snapshot(
        str(path), revision, source["repository"], source["name"], approved_only
    )


@lru_cache(maxsize=32)
def _snapshot(path, revision, repository, name, approved_only=False):
    catalog = yaml.safe_load(_blob(path, revision, "catalog/knowledge.yaml"))
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema_version") != 1
        or catalog.get("repository") != repository
    ):
        raise ValueError("Unsupported or mismatched team knowledge catalog")
    rows = catalog.get("knowledge")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Catalog must contain at most 2000 knowledge entries")
    entries, seen = [], set()
    base = f"https://github.com/{repository}/blob/{revision}/"
    source_rows = json.loads(_blob(path, revision, "sources/index.json")).get(
        "sources", []
    )
    evidence = {row["id"]: row for row in source_rows}
    for row in rows:
        # Query workers are short-lived. Avoid opening every unreviewed document
        # when it cannot enter recall; the graph still loads the full catalog.
        if approved_only and row.get("status") != "approved":
            continue
        identifier = row["id"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[\w-]{1,100}", identifier)
            or identifier in seen
        ):
            raise ValueError("Invalid or duplicate team knowledge ID")
        seen.add(identifier)
        relative = _relative(row["path"])
        if not relative.startswith("knowledge/") or not relative.endswith(".md"):
            raise ValueError("Team knowledge must be Markdown under knowledge/")
        body = _blob(path, revision, relative)
        digest = hashlib.sha256(body).hexdigest()
        status = row["status"]
        if status not in {"candidate", "approved", "deprecated", "rejected"}:
            raise ValueError("Unsupported team review status")
        approval = row.get("approval")
        if status == "approved":
            if (
                not isinstance(approval, str)
                or not approval.startswith("sources/reviews/")
                or not approval.endswith(".json")
            ):
                raise ValueError("Approved knowledge needs a review record")
            review = json.loads(_blob(path, revision, approval))
            if (
                review.get("decision") != "approved"
                or review.get("id") != identifier
                or review.get("body_sha256") != digest
            ):
                raise ValueError("Approval does not bind this knowledge version")
            for key in ("reviewer", "decided_at", "decision_ref"):
                if (
                    not isinstance(review.get(key), str)
                    or not review[key].strip()
                    or review[key].lower() in {"todo", "pending", "unknown", "tbd"}
                ):
                    raise ValueError("Review is missing " + key)
            datetime.fromisoformat(review["decided_at"].replace("Z", "+00:00"))
            if not review["decision_ref"].startswith("https://"):
                if review["decision_ref"] == approval:
                    raise ValueError("Review cannot be its own evidence")
                _blob(path, revision, review["decision_ref"])
        elif status == "candidate" and approval is not None:
            raise ValueError("Candidate cannot claim approval")
        source_id = row.get("source_id", identifier)
        if source_id not in evidence:
            raise ValueError("Knowledge is missing its source registration")
        original = evidence[source_id]
        # Preserve source catalog reference; do not invent an evidence URL.
        entries.append(
            {
                "id": f"team:{name}/{identifier}",
                "slug": f"team:{name}/{identifier}",
                "title": row["title"],
                "type": "team",
                "family": "team",
                "group": name,
                "path": relative,
                "source_path": relative,
                "source_sha256": digest,
                "repository": repository,
                "revision": revision,
                "status": status,
                "pending": status == "candidate",
                "uses": 0,
                "tags": row.get("topics", []),
                "body": body.decode("utf-8"),
                "url": base + quote(relative, safe="/"),
                "approval_url": base + quote(approval, safe="/") if approval else None,
                "evidence_url": (
                    original.get("url")
                    if str(original.get("url", "")).startswith("https://")
                    else None
                ),
                "metadata": {
                    "repository": repository,
                    "revision": revision,
                    "status": status,
                    "source_id": source_id,
                    "sha256": digest,
                    "source_version": original.get("version"),
                    "source_sha256": original.get("sha256"),
                },
            }
        )
    return {
        "name": name,
        "repository": repository,
        "revision": revision,
        "entries": entries,
        "approved_count": sum(e["status"] == "approved" for e in entries),
        "candidate_count": sum(e["pending"] for e in entries),
    }


def catalog(root, *, approved_only=False):
    sources, warnings = [], []
    try:
        configured = configuration(root)
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return {
            "sources": [],
            "warnings": ["Linked source settings unavailable; excluded from recall"],
        }
    for source in configured:
        try:
            sources.append(snapshot(source, approved_only=approved_only))
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, yaml.YAMLError):
            warnings.append(
                source.get("name", "source") + ": unavailable; excluded from recall"
            )
    return {"sources": sources, "warnings": warnings}


def search(root, query, limit=3, scope=None, type_filter=None):
    from .recall import _tokenize

    tokens = _tokenize(query.lower())
    if not tokens:
        return [], []
    data = catalog(root, approved_only=True)
    hits = []
    for source in data["sources"]:
        for entry in source["entries"]:
            if (
                entry["status"] != "approved"
                or (scope and scope not in entry["tags"])
                or type_filter
            ):
                continue
            # Independent, explicitly named lexical channel: its scores are not
            # compared with personal BM25 or confidence/decay scores.
            matched = tokens & _tokenize(
                (entry["title"] + "\n" + entry["body"]).lower()
            )
            if matched:
                hits.append(
                    {
                        **entry,
                        "backend": "team-lexical",
                        "relevance": len(matched) / len(tokens),
                        "body": entry["body"][:800],
                        "channel": "team",
                        "read_only": True,
                    }
                )
    return (
        sorted(hits, key=lambda e: (-e["relevance"], e["id"]))[:limit],
        data["warnings"],
    )
