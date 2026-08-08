"""Feishu worker candidate module — state path/load/save, render/parse, fingerprint, publish.

Extracted from feishu_base_worker.py (Round 3 Phase 5).  Imports only from
feishu_worker.* leaf modules (config, io_utils, base_client) and stdlib.
Never imports feishu_base_worker.  Callers must supply *root* explicitly so
this module has zero dependency on the ROOT constant in the main worker.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from feishu_worker.config import WorkerConfig, configured_knowledge_root
from feishu_worker.io_utils import (
    atomic_write_json,
    atomic_write_text,
    scalar_cell,
    utc_now,
)
from feishu_worker.base_client import (
    LarkFn,
    base_args,
    get_record as _base_get_record,
    lark_json as _base_lark_json,
    update_record as _base_update_record,
)
from feishu_worker.notification import (  # noqa: E402 — re-export for worker compatibility
    render_candidate_review_message,
    send_candidate_review_notification,
)

# ── Candidate field projection ─────────────────────────────────────────
CANDIDATE_FIELDS = [
    "运行状态",
    "运行ID",
    "Raw Bundle",
    "Wiki状态",
    "候选ID",
    "候选内容",
    "审核动作",
    "审核意见",
    "修改类型",
    "审核时间",
    "Wiki路径",
]


# ── Document parse / render ────────────────────────────────────────────


def parse_candidate_document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("Candidate must start with YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("Candidate frontmatter is not closed")
    metadata = yaml.safe_load(parts[1].strip()) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Candidate frontmatter must be an object")
    for field in ("title", "draft_type", "draft_area"):
        if not str(metadata.get(field) or "").strip():
            raise ValueError(f"Candidate frontmatter missing {field}")
    if metadata["draft_type"] not in {"concept", "strategy", "anti-pattern"}:
        raise ValueError("Candidate draft_type must be concept, strategy, or anti-pattern")
    body = parts[2].strip()
    if len(body) < 50:
        raise ValueError("Candidate body must contain at least 50 characters")
    return metadata, body


def render_candidate_document(metadata: dict[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{frontmatter}---\n\n{body.strip()}\n"


# ── Candidate state path / load ────────────────────────────────────────


def candidate_state_path(record_id: str, *, root: Path) -> Path:
    safe_record_id = re.sub(r"[^A-Za-z0-9_-]+", "-", record_id).strip("-")
    if not safe_record_id:
        raise ValueError("record_id cannot form a Candidate state path")
    return root / ".oks" / "candidates" / f"{safe_record_id}.json"


def load_candidate_state(record_id: str, *, root: Path) -> dict[str, Any]:
    path = candidate_state_path(record_id, root=root)
    if not path.is_file():
        raise FileNotFoundError(f"Candidate state not found for Base record: {record_id}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Candidate state is not an object: {path}")
    return value


# ── Fingerprint ────────────────────────────────────────────────────────


def candidate_review_fingerprint(fields: dict[str, Any]) -> str:
    payload = {
        "action": scalar_cell(fields.get("审核动作")),
        "comment": fields.get("审核意见"),
        "change_types": fields.get("修改类型"),
        "reviewed_at": fields.get("审核时间"),
        "candidate": fields.get("候选内容"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ── Publish candidate ──────────────────────────────────────────────────


def publish_candidate(
    # .. deprecated:: 0.4.0
    #    Candidate publication belongs to the Knowledge Plane and should be
    #    performed by the Agent via ``observation_to_candidate()``, not by
    #    the Feishu Worker.  In Phase 6 this function is decomposed:
    #    - draft writing → Agent ingest skill
    #    - notification → stays in feishu_worker/notification.py
    #    - state update → stays as a thin Base write-back helper
    config: WorkerConfig,
    record_id: str,
    candidate_file: Path,
    *,
    root: Path,
    _get_fn: LarkFn | None = None,
    _update_fn: LarkFn | None = None,
    _lark_fn: LarkFn | None = None,
    _send_notification_fn: LarkFn | None = None,
) -> dict[str, Any]:
    _get = _get_fn if _get_fn is not None else functools.partial(_base_get_record, root=root)
    _update = _update_fn if _update_fn is not None else functools.partial(_base_update_record, root=root)
    _lark = _lark_fn if _lark_fn is not None else functools.partial(_base_lark_json, root=root)
    _send_notification = _send_notification_fn if _send_notification_fn is not None else send_candidate_review_notification

    record = _get(config, record_id, [*CANDIDATE_FIELDS, "内容", "思考"])
    fields = record["fields"]
    status = scalar_cell(fields.get("运行状态"))
    if status not in {"Raw就绪", "候选待审", "需人工"}:
        raise RuntimeError(f"Base record is not ready for Candidate publication: {status!r}")
    raw_bundle = scalar_cell(fields.get("Raw Bundle"))
    if not isinstance(raw_bundle, str) or not raw_bundle.strip():
        raise RuntimeError("Base record has no Raw Bundle; refusing to publish Candidate")
    raw_path = Path(raw_bundle).expanduser().resolve()
    if not raw_path.is_dir() or not (raw_path / "bundle.json").is_file():
        raise RuntimeError(f"Raw Bundle is not locally verifiable: {raw_path}")

    source = candidate_file.expanduser().resolve()
    metadata, body = parse_candidate_document(source.read_text(encoding="utf-8"))
    candidate_id = re.sub(r"[^a-z0-9-]+", "-", source.stem.lower()).strip("-")
    if not candidate_id:
        candidate_id = f"feishu-{record_id.lower()}"
    knowledge_root = configured_knowledge_root(config, root=root)
    target = knowledge_root / "drafts" / f"{candidate_id}.md"
    metadata["status"] = "draft"
    source_pages = metadata.get("source_pages", [])
    if not isinstance(source_pages, list):
        source_pages = [str(source_pages)] if source_pages else []
    metadata["source_pages"] = list(dict.fromkeys([
        *source_pages,
        f"feishu:{record_id}",
    ]))
    traces = metadata.get("traces")
    if not isinstance(traces, list):
        traces = []
    manifest = json.loads((raw_path / "bundle.json").read_text(encoding="utf-8"))
    execution_trace: dict[str, Any] = {
        "kind": "execution",
        "id": str(scalar_cell(fields.get("运行ID")) or ""),
    }
    for key in ("capture_id", "bundle_id"):
        value = str(manifest.get(key) or "").strip()
        if value:
            execution_trace[key] = value
    try:
        execution_trace["path"] = raw_path.relative_to(knowledge_root).as_posix()
    except ValueError:
        pass
    trace_values = [
        execution_trace,
        {"kind": "external", "id": f"feishu-base:{record_id}"},
    ]
    for trace in trace_values:
        if trace not in traces:
            traces.append(trace)
    metadata["traces"] = traces
    document = render_candidate_document(metadata, body)
    atomic_write_text(target, document)

    state_path = candidate_state_path(record_id, root=root)
    previous: dict[str, Any] = {}
    if state_path.is_file():
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            previous = loaded
    state = {
        "schema_version": "oks-feishu-candidate/v0.1",
        "record_id": record_id,
        "candidate_id": candidate_id,
        "candidate_path": (
            target.relative_to(root.resolve()).as_posix()
            if knowledge_root == root.resolve()
            else str(target)
        ),
        "candidate_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "raw_bundle": str(raw_path),
        "run_id": scalar_cell(fields.get("运行ID")),
        "revision": int(previous.get("revision", 0)) + 1,
        "published_at": utc_now(),
        "review_history": previous.get("review_history", []),
        "last_review_fingerprint": None,
    }
    atomic_write_json(state_path, state)
    _update(
        config,
        record_id,
        {
            "候选ID": candidate_id,
            "候选内容": body,
            "审核动作": None,
            "审核意见": None,
            "修改类型": None,
            "审核时间": None,
            "Wiki路径": None,
            "Wiki状态": "review_pending",
            "运行状态": "候选待审",
        },
    )
    state["review_notification"] = _send_notification(
        config,
        record_id=record_id,
        state=state,
        metadata=metadata,
        body=body,
        fields=fields,
        root=root,
        _lark_fn=_lark,
    )
    atomic_write_json(state_path, state)
    return state
