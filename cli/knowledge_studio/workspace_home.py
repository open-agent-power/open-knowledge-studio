"""Read-only, bounded summary for the daily workspace home view."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any

import frontmatter
import yaml


_LIMIT = 2000
_TASKS_LIMIT = 100  # tasks.overview owns this established bounded projection.
_PREVIEW = 5
_MAX_FILE_BYTES = 2 * 1024 * 1024


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _bounded_files(base: Path, *, recursive: bool, cap: int = _LIMIT) -> tuple[list[Path], bool, str | None]:
    """Enumerate a capped number of filesystem entries without materializing a tree."""
    if not base.is_dir():
        return [], False, "directory_missing"
    found: list[Path] = []
    visited = 0
    truncated = False
    stack = [base]
    try:
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > cap:
                        truncated = True
                        return sorted(found), truncated, None
                    try:
                        if entry.is_symlink():
                            continue
                        path = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                stack.append(path)
                            continue
                        if entry.is_file(follow_symlinks=False) and path.suffix.lower() == ".md":
                            found.append(path)
                    except OSError:
                        return sorted(found), truncated, "entry_unavailable"
    except OSError:
        return sorted(found), truncated, "directory_unavailable"
    return sorted(found), truncated, None


def _private_or_source_only(meta: dict[str, Any]) -> bool:
    visibility = str(meta.get("visibility", "")).strip().lower()
    workflow = meta.get("workflow_source")
    if ("feedback_origin" in meta or meta.get("private") is True or meta.get("private_scope") is True
            or visibility in {"private", "local_private"}):
        return True
    if (meta.get("source_only") is True or str(meta.get("workflow_mode", "")).lower() == "source_only"
            or str(meta.get("workflow_status", "")).lower() == "source_only"
            or str(meta.get("source_type", "")).lower() == "source_only"
            or str(meta.get("artifact_kind", "")).lower() in {"source", "raw_source"}):
        return True
    return isinstance(workflow, dict) and workflow.get("private_scope") is True


def _reviewed_disposition(root: Path, relative: str, raw: bytes, digest: str, text: str) -> bool:
    """Return true for exact-byte reviewed decisions or no-proposal records."""
    try:
        from . import draft_review
        receipt = draft_review.disposition(root, relative, digest)
        if receipt is not None:
            return True
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        # A corrupt/ambiguous decision receipt must not make a Draft look pending.
        raise ValueError("review_receipt_unavailable") from None

    try:
        from .task_workflow import candidate_disposition
        disposition = candidate_disposition(root, relative, raw, sha256=digest)
        return disposition in {"promoted", "rejected", "not_proposed"}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, yaml.YAMLError):
        raise ValueError("candidate_disposition_unavailable") from None


def _plain(value: object, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit]


def _task_summary(root: Path, errors: list[dict[str, str]], truncated: dict[str, bool]) -> tuple[dict[str, int | None], list[dict[str, Any]]]:
    try:
        from . import tasks
        overview = tasks.overview(root)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        errors.append({"section": "tasks", "code": "overview_unavailable"})
        truncated["tasks"] = False
        return {"active_tasks": None, "awaiting_confirmation": None}, []

    rows = overview.get("tasks")
    if not isinstance(rows, list):
        errors.append({"section": "tasks", "code": "overview_invalid"})
        truncated["tasks"] = False
        return {"active_tasks": None, "awaiting_confirmation": None}, []
    truncated["tasks"] = bool(overview.get("truncated"))
    active = [item for item in rows if isinstance(item, dict)
              and item.get("lifecycle", "active") == "active" and item.get("status") != "unavailable"]
    task_read_error = any(isinstance(item, dict) and item.get("status") == "unavailable" for item in rows)
    if task_read_error:
        errors.append({"section": "tasks", "code": "task_record_unavailable"})
    counts = {
        "active_tasks": len(active) if not truncated["tasks"] and not task_read_error else None,
        "awaiting_confirmation": sum(bool(item.get("awaiting_confirmation")) for item in active)
        if not truncated["tasks"] and not task_read_error else None,
    }
    next_tasks = []
    for item in active[:_PREVIEW]:
        task_id = item.get("task_id")
        if not isinstance(task_id, str):
            errors.append({"section": "tasks", "code": "task_record_invalid"})
            continue
        try:
            task = tasks.show(root, task_id)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            errors.append({"section": "tasks", "code": "task_detail_unavailable"})
            continue
        artifacts = task.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append({"section": "tasks", "code": "task_detail_invalid"})
            outputs_count = None
        else:
            outputs_count = len(artifacts)
        next_tasks.append({
            "task_id": task_id,
            "title": _plain(item.get("title")) or task_id,
            "progress": _plain(task.get("progress")),
            "next_action": _plain(item.get("next_action")),
            "outputs_count": outputs_count,
            "awaiting_confirmation": bool(item.get("awaiting_confirmation")),
        })
    return counts, next_tasks


def _wiki_counts(root: Path, errors: list[dict[str, str]], truncated: dict[str, bool]) -> tuple[int | None, int | None]:
    files, was_truncated, issue = _bounded_files(root / "wiki", recursive=True, cap=_LIMIT)
    truncated["wiki"] = was_truncated
    if issue:
        errors.append({"section": "wiki", "code": issue})
        return None, None
    reviewed = methods = 0
    read_error = False
    for path in files:
        try:
            raw = path.read_bytes()
            if len(raw) > _MAX_FILE_BYTES:
                raise ValueError("file_too_large")
            parsed = frontmatter.loads(raw.decode("utf-8-sig"))
            meta = dict(parsed.metadata)
            if not meta:
                raise ValueError("metadata_missing")
            status = str(meta.get("status", "active")).strip().lower()
            archived = meta.get("archived") is True or str(meta.get("archived", "")).strip().lower() in {"1", "true", "yes"}
            if status == "active" and bool(meta.get("human_reviewed_at")) and not archived:
                reviewed += 1
                if str(meta.get("artifact_kind", "")).lower() == "skill" or str(meta.get("type", "")).lower() == "skill":
                    methods += 1
        except (OSError, UnicodeError, ValueError, yaml.YAMLError):
            errors.append({"section": "wiki", "code": "page_unavailable"})
            read_error = True
    if was_truncated:
        errors.append({"section": "wiki", "code": "count_partial"})
    if read_error or was_truncated:
        return None, None
    return reviewed, methods


def _drafts(root: Path, errors: list[dict[str, str]], truncated: dict[str, bool]) -> tuple[int | None, list[dict[str, str]]]:
    files, was_truncated, issue = _bounded_files(root / "drafts", recursive=False, cap=_LIMIT)
    truncated["drafts"] = was_truncated
    if issue:
        errors.append({"section": "drafts", "code": issue})
        return None, []
    candidates: list[dict[str, str]] = []
    read_error = False
    for path in files:
        try:
            raw = path.read_bytes()
            if len(raw) > _MAX_FILE_BYTES:
                raise ValueError("file_too_large")
            text = raw.decode("utf-8-sig")
            parsed = frontmatter.loads(text)
            meta = dict(parsed.metadata)
            if not meta:
                raise ValueError("metadata_missing")
            if _private_or_source_only(meta):
                continue
            relative = path.relative_to(root).as_posix()
            digest = hashlib.sha256(raw).hexdigest()
            if _reviewed_disposition(root, relative, raw, digest, text):
                continue
            title = _plain(meta.get("title")) or path.stem
            kind = "skill" if str(meta.get("artifact_kind", "")).lower() == "skill" or str(meta.get("draft_type", meta.get("type", ""))).lower() == "skill" else "knowledge"
            candidates.append({"path": relative, "title": title, "kind": kind})
        except (OSError, UnicodeError, ValueError, yaml.YAMLError):
            errors.append({"section": "drafts", "code": "candidate_unavailable"})
            read_error = True
    if was_truncated:
        errors.append({"section": "drafts", "code": "count_partial"})
    return (None if read_error or was_truncated else len(candidates)), candidates[:_PREVIEW]


def build(root: str | Path) -> dict[str, Any]:
    """Build a small read-only home projection from the explicit KB root."""
    kb_root = Path(root).expanduser().resolve()
    errors: list[dict[str, str]] = []
    truncated = {"tasks": False, "wiki": False, "drafts": False}

    task_counts, next_tasks = _task_summary(kb_root, errors, truncated)
    reviewed, methods = _wiki_counts(kb_root, errors, truncated)
    pending_drafts, drafts = _drafts(kb_root, errors, truncated)

    temp_root = Path(tempfile.gettempdir()).resolve()
    storage_kind = "temporary" if _inside(kb_root, temp_root) else "folder"
    name = _plain(kb_root.name, 120) or "Knowledge base"
    return {
        "schema_version": "workspace-home/v1",
        "knowledge_base": str(kb_root),
        "name": name,
        "storage_kind": storage_kind,
        "counts": {
            **task_counts,
            "pending_drafts": pending_drafts,
            "reviewed_knowledge": reviewed,
            "reusable_methods": methods,
        },
        "next_tasks": next_tasks,
        "pending_drafts": drafts,
        "errors": errors,
        "truncated": truncated,
    }


__all__ = ["build"]
