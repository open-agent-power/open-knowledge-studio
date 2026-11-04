"""Validate and finalize an Agent's persisted handoff, never execute ingestion."""
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path

from knowledge_studio import mail, store


def _inside(root: Path, relative: str, bucket: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Expected an instance-relative path")
    parts = relative.split("/")
    if not parts or parts[0] != bucket or any(
        p in {"", ".", ".."} or re.search(r'[\x00-\x1f:*?"<>|]', p)
        for p in parts
    ):
        raise ValueError(f"Expected a bounded {bucket}/ path")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Symlinks and junctions are not workflow evidence")
    if not current.resolve().is_relative_to(root):
        raise ValueError("Evidence path escapes the instance")
    return current


def _bundle_paths(root: Path):
    for parent, dirs, names in os.walk(root / "raw", followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()
                   and not (Path(parent) / name).is_junction()]
        if "bundle.json" in names:
            yield _inside(root, (Path(parent) / "bundle.json").relative_to(root).as_posix(), "raw")


def _result_path(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"run-[a-zA-Z0-9_-]{1,100}", run_id):
        raise ValueError("Expected a run- identifier")
    return _inside(root, f".oks/runs/{run_id}/result.json", ".oks")


def _read_result(result_path: Path) -> dict:
    if result_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Run result exceeds the validation size limit")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Run result must be an object")
    return result


def _requires_collaboration(result: dict) -> bool:
    mode = result.get("workflow_mode")
    if mode not in (None, "source_only", "collaboration"):
        raise ValueError("workflow_mode must be source_only or collaboration")
    collab = result.get("collaboration") or {}
    if not isinstance(collab, dict):
        raise ValueError("collaboration must be an object")
    return (mode == "collaboration" or bool(collab.get("thread_id") or collab.get("messages"))
            or collab.get("status") in ("recorded", "awaiting_authorization"))


def validate_workflow(run_id: str, *, collaboration: bool = False,
                      review_owner: str = "human") -> dict:
    """Read facts; an already-declared collaboration cannot skip its handoffs."""
    root = store.repo_root().resolve()
    result = _read_result(_result_path(root, run_id))
    return _validate_result(root, run_id, result, collaboration=collaboration,
                            review_owner=review_owner)


def _validate_result(root: Path, run_id: str, result: dict, *, collaboration: bool,
                     review_owner: str) -> dict:
    collaboration = _requires_collaboration(result) or collaboration
    errors, warnings = [], []
    status = result.get("status")
    if not isinstance(status, str):
        raise ValueError("Extraction status must be a string")
    if status not in {"complete", "partial", "failed", "skipped"}:
        errors.append("invalid_extraction_status")
    if status in {"failed", "skipped"}:
        errors.append("extraction_not_ready")
    if status == "partial":
        warnings.append("extraction_partial")

    bundle_id = result.get("bundle_id")
    bundles = []
    if isinstance(bundle_id, str) and bundle_id:
        for path in _bundle_paths(root):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(data, dict) and data.get("bundle_id") == bundle_id:
                bundles.append(path.relative_to(root).as_posix())
                content = _inside(root, (path.parent / "content.md").relative_to(root).as_posix(), "raw")
                if not content.is_file():
                    errors.append("bundle_content_missing")
                if status == "complete" and data.get("processing_status") != "complete":
                    errors.append("bundle_status_mismatch")
    if not bundles:
        errors.append("bundle_not_found")

    paths = result.get("candidate_paths")
    if paths is None:
        paths = [result["candidate_path"]] if result.get("candidate_path") else []
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise ValueError("candidate_paths must be a list of relative paths")
    paths = list(dict.fromkeys(paths))
    if result.get("candidate_path") and result["candidate_path"] not in paths:
        errors.append("primary_candidate_missing_from_list")
    grade = result.get("intake_grade")
    if not isinstance(grade, str):
        raise ValueError("Intake grade must be a string")
    if grade not in {"A", "B", "C"}:
        errors.append("invalid_intake_grade")
    if grade == "A" and not paths:
        errors.append("candidate_required")
    if grade in {"B", "C"} and paths:
        errors.append("candidate_not_expected")
    promoted = {}
    wiki_pages = store.list_wiki_pages() if paths else []
    for relative in paths:
        path = _inside(root, relative, "drafts")
        meta = store.parse_wiki_file(path) if path.is_file() else None
        reviewed = None
        if meta:
            from . import draft_review
            reviewed = draft_review.disposition(root, relative, hashlib.sha256(path.read_bytes()).hexdigest())
        if reviewed and reviewed['decision'] == 'promoted':
            matches = [page for page in wiki_pages if isinstance(page.get('source_candidates'), list)
                       and relative in page['source_candidates']
                       and page.get('source_bundle_id') == bundle_id
                       and page.get('human_reviewed_at') and page.get('status') == 'active'
                       and not page.get('archived')
                       and Path(page['file_path']).relative_to(root).as_posix() == reviewed['wiki_path']]
            if len(matches) == 1:
                promoted[relative] = _inside(root, reviewed['wiki_path'], 'wiki').relative_to(root).as_posix()
            else:
                errors.append(f'candidate_promotion_unproven:{relative}')
            continue
        if not meta:
            # Retained originals are part of the review contract. Wiki labels
            # alone cannot prove which missing Candidate revision was approved.
            errors.append(f"candidate_missing:{relative}")
        elif (meta.get("human_reviewed_at") or not isinstance(meta.get("status"), str)
              or meta.get("status") not in {"pending", "draft"}):
            errors.append(f"candidate_not_pending:{relative}")
        elif meta.get("source_bundle_id") != bundle_id:
            errors.append(f"candidate_bundle_mismatch:{relative}")
    if paths and len(promoted) != len(paths) and result.get("review_status") != "pending":
        errors.append("review_status_not_pending")

    collab = result.get("collaboration") or {}
    if not isinstance(collab, dict):
        raise ValueError("collaboration must be an object")
    if collaboration:
        if collab.get("status") != "recorded":
            errors.append("collaboration_not_recorded")
        owner = mail._normalise_agent(review_owner)
        if owner in {"@all", "@unknown"}:
            raise ValueError("Choose an explicit review owner")
        thread = str(collab.get("thread_id") or "")
        # Filter by the review owner's actual visibility before resolving IDs.
        visible = {str(m["meta"].get("message_id")): m
                   for m in mail.iter_messages(root, owner)
                   if m["meta"].get("thread_id") == thread}
        ids = collab.get("messages") or {}
        if not isinstance(ids, dict):
            raise ValueError("collaboration.messages must be an object")
        previous = ""
        kinds = ["goal", "result"] + (["review_request"] if paths else [])
        selected_ids = [ids.get(kind) for kind in kinds]
        if len(set(str(value) for value in selected_ids)) != len(kinds):
            errors.append("duplicate_message_ids")
        for kind in kinds:
            message = visible.get(str(ids.get(kind)))
            if not message:
                errors.append(f"message_not_visible:{kind}")
                previous = str(ids.get(kind) or "")
                continue
            meta = message["meta"]
            if meta.get("record_kind") != kind:
                errors.append(f"message_kind_mismatch:{kind}")
            if owner not in meta.get("to", []):
                errors.append(f"message_not_addressed_to_owner:{kind}")
            if previous and meta.get("reply_to") != previous:
                errors.append(f"reply_parent_mismatch:{kind}")
            refs = mail.normalise_evidence_refs(meta.get("evidence_refs"))
            required = [{"type": "run", "id": run_id}]
            if kind != "goal":
                required += [{"type": "bundle", "id": bundle_id}]
                required += [{"type": "candidate", "path": p} for p in paths]
            if any(not any(all(ref.get(k) == v for k, v in need.items()) for ref in refs)
                   for need in required):
                errors.append(f"message_evidence_missing:{kind}")
            previous = str(meta.get("message_id"))
        if collab.get("retrospective"):
            warnings.append("collaboration_recorded_retrospectively")

    expected = ("complete" if len(promoted) == len(paths) else "awaiting_human_review") if paths else "source_only"
    if paths and expected != "complete" and result.get("workflow_status") in {"complete", "completed", "success"}:
        errors.append("premature_workflow_completion")
    return {"schema_version": "ingest.workflow-validation.v1", "run_id": run_id,
            "valid": not errors, "extraction_status": status,
            "workflow_status": "incomplete" if errors else expected,
            "collaboration_checked": collaboration, "bundles": bundles,
            "candidate_paths": paths, "promoted_pages": promoted, "errors": errors, "warnings": warnings}


def finalize_workflow(run_id: str, *, source_only: bool = False,
                      review_owner: str = "human") -> dict:
    """Persist checked workflow state, retaining extraction and human-review facts.

    Defaults to the full collaborative handoff. Standalone ingestion must explicitly
    opt out; it cannot downgrade an existing collaborative run. The per-run lock
    serializes finalizers, not arbitrary external edits to evidence or result.json.
    """
    root = store.repo_root().resolve()
    path = _result_path(root, run_id)
    # Do not create a run or lock when there is no parseable result to finalize.
    _read_result(path)
    lock = _inside(root, f".oks/runs/{run_id}/.result.lock", ".oks")
    with store._file_lock(lock):
        result = _read_result(_result_path(root, run_id))
        required = _requires_collaboration(result)
        checked = _validate_result(root, run_id, result,
                                   collaboration=not source_only, review_owner=review_owner)
        if source_only and required:
            checked["errors"].append("collaboration_downgrade_not_allowed")
            checked.update(valid=False, workflow_status="incomplete")
        result["workflow_mode"] = "collaboration" if required or not source_only else "source_only"
        result["workflow_status"] = checked["workflow_status"]
        result["workflow_validation"] = checked
        result["promoted_pages"] = checked["promoted_pages"]
        if checked["valid"] and checked["candidate_paths"]:
            result["wiki_promoted"] = checked["workflow_status"] == "complete"
            result["review_status"] = "approved" if result["wiki_promoted"] else "pending"
        store._atomic_write(_result_path(root, run_id),
                            json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return checked
