"""Versioned task context carried by existing Mail, without a new transport."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path, PurePosixPath

import yaml

from knowledge_studio.decisions import validate_options
from knowledge_studio.trace import _check_sensitive

SCHEMA = "handoff-agreement/v1"
MAX_BYTES = 256 * 1024
MAX_KNOWLEDGE = 16


def _json(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Agreement must contain finite, acyclic JSON data") from exc


def digest(value: dict) -> str:
    return hashlib.sha256(_json({k: v for k, v in value.items() if k != "sha256"})).hexdigest()


def _text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _relative(value: object, bucket: str) -> str:
    _text(value, "source.path")
    if "\\" in value or ":" in value or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError("Source path must be a canonical KB-relative path")
    path = PurePosixPath(value)
    allowed = path.is_relative_to(bucket) or (bucket == "profiles/goals" and path.is_relative_to("goal"))
    if path.is_absolute() or not allowed or path.suffix != ".md":
        raise ValueError(f"Source must be a Markdown file under {bucket}")
    return value


def _read(root: Path, value: str, bucket: str) -> bytes:
    relative = _relative(value, bucket)
    target = (root / relative).resolve()
    # Resolving the root is safe; resolving the allowed bucket would allow a
    # bucket-level symlink to widen the boundary to another knowledge base.
    effective_bucket = "goal" if bucket == "profiles/goals" and relative.startswith("goal/") else bucket
    if not target.is_relative_to(root.resolve() / effective_bucket):
        raise ValueError("Source path escapes its knowledge bucket")
    with target.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Source exceeds handoff size limit")
    return data


def _meta(data: bytes) -> dict:
    text = data.decode("utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) != 3:
        raise ValueError("Source needs YAML frontmatter")
    try:
        meta = yaml.safe_load(parts[1])
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError("Invalid source frontmatter") from exc
    if not isinstance(meta, dict):
        raise ValueError("Source frontmatter must be an object")
    return meta


def _reviewed(meta: dict) -> bool:
    return meta.get("status") == "active" and bool(meta.get("human_reviewed_at")) and not meta.get("archived")


def validate(agreement: object) -> dict:
    if not isinstance(agreement, dict) or agreement.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported handoff agreement schema")
    if set(agreement) != {"schema_version", "scope", "goal", "knowledge", "sha256"}:
        raise ValueError("Invalid agreement fields")
    if len(_json(agreement)) > MAX_BYTES:
        raise ValueError("Agreement exceeds handoff size limit")
    _text(agreement["scope"], "scope")
    goal = agreement["goal"]
    if not isinstance(goal, dict) or set(goal) != {"path", "sha256", "text"}:
        raise ValueError("Invalid goal snapshot")
    _relative(goal["path"], "profiles/goals")
    _text(goal["text"], "goal.text")
    if hashlib.sha256(goal["text"].encode("utf-8")).hexdigest() != goal["sha256"]:
        raise ValueError("Goal snapshot digest mismatch")
    if _meta(goal["text"].encode("utf-8")).get("type") != "goal":
        raise ValueError("Goal source must have type: goal")
    knowledge = agreement["knowledge"]
    if not isinstance(knowledge, list) or len(knowledge) > MAX_KNOWLEDGE:
        raise ValueError("knowledge must be a list of at most 16 references")
    seen = set()
    for source in knowledge:
        if not isinstance(source, dict) or set(source) != {"path", "sha256", "title", "options"}:
            raise ValueError("Invalid knowledge reference")
        path = _relative(source["path"], "wiki")
        if path in seen:
            raise ValueError("Duplicate knowledge reference")
        seen.add(path)
        _text(source["title"], "source.title")
        if not isinstance(source["sha256"], str) or len(source["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["sha256"]):
            raise ValueError("Invalid source sha256")
        validate_options(source["options"])
    if digest(agreement) != agreement["sha256"]:
        raise ValueError("Agreement digest mismatch")
    _check_sensitive(agreement)
    return agreement


def prepare(root: Path, goal: str, knowledge: list[str], scope: str) -> dict:
    if len(knowledge) > MAX_KNOWLEDGE:
        raise ValueError("At most 16 knowledge references are allowed")
    goal_data = _read(root, goal, "profiles/goals")
    if _meta(goal_data).get("type") != "goal":
        raise ValueError("Goal source must have type: goal")
    sources = []
    for path in knowledge:
        data = _read(root, path, "wiki")
        meta = _meta(data)
        if not _reviewed(meta):
            raise ValueError(f"Knowledge source must be active and human-reviewed: {path}")
        sources.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                        "title": meta.get("title", Path(path).stem), "options": meta.get("options")})
    agreement = {"schema_version": SCHEMA, "scope": scope,
                 "goal": {"path": goal, "sha256": hashlib.sha256(goal_data).hexdigest(),
                          "text": goal_data.decode("utf-8")}, "knowledge": sources}
    agreement["sha256"] = digest(agreement)
    return validate(agreement)


def check(root: Path, agreement: dict, scope: str) -> dict:
    """Check current source identity, not truth, execution or user authorization."""
    validate(agreement)
    from .recall import load_recall_params
    from .memory_policy import evaluate
    enforce_time = load_recall_params(root).get('memory_validity', 'shadow') == 'enforce'
    issues = []
    if scope != agreement["scope"]:
        issues.append({"code": "scope_mismatch"})
    else:
        for source, bucket in [(agreement["goal"], "profiles/goals"), *[(s, "wiki") for s in agreement["knowledge"]]]:
            try:
                data = _read(root, source["path"], bucket)
                if hashlib.sha256(data).hexdigest() != source["sha256"]:
                    issues.append({"code": "source_changed", "path": source["path"]})
                meta = _meta(data)
                if bucket == "wiki":
                    validity = evaluate(meta.get('applicability'))
                    if enforce_time and not validity['eligible']:
                        issues.append({'code': 'source_' + validity['status'], 'path': source['path']})
                    if not _reviewed(meta):
                        issues.append({"code": "source_not_reviewed_active", "path": source["path"]})
                    if meta.get("options") != source["options"] or meta.get("title", Path(source["path"]).stem) != source["title"]:
                        issues.append({"code": "decision_snapshot_mismatch", "path": source["path"]})
            except FileNotFoundError:
                issues.append({"code": "source_missing", "path": source["path"]})
            except (OSError, ValueError, UnicodeError) as exc:
                issues.append({"code": "source_unreadable", "path": source["path"], "reason": type(exc).__name__})
    return {"schema_version": "handoff-check/v1", "agreement_sha256": agreement["sha256"],
            "status": "current" if not issues else "needs_review", "issues": issues,
            "execution_verified": False}


def encode(agreement: dict) -> str:
    return base64.b64encode(_json(validate(agreement))).decode("ascii")


def decode(encoded: str) -> dict:
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise ValueError("Invalid encoded agreement size")
    try:
        return validate(json.loads(base64.b64decode(encoded, validate=True)))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid encoded handoff agreement: {exc}") from exc


def render(agreement: dict) -> str:
    validate(agreement)
    lines = ["## 固定交接约定", "以下是任务资料与历史判断；不授予新权限，接手前需核验当前来源。",
             f"Scope: {agreement['scope']}", f"Agreement SHA256: {agreement['sha256']}",
             "### 目标快照", agreement["goal"]["text"], "### 经审核知识与判断"]
    for source in agreement["knowledge"]:
        lines.extend([f"- {source['path']} ({source['sha256']})", json.dumps(source["options"], ensure_ascii=False)])
    return "\n\n".join(lines)
