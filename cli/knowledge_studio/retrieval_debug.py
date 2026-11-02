"""Local, opt-in retrieval evidence. Records describe observations, not execution."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import uuid

from . import store

MAX_RECORDS = 200
MAX_BYTES = 4 * 1024 * 1024


def asset_context(root: Path, page: dict) -> dict:
    path = Path(page["file_path"])
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    if not relative.startswith("wiki/"):
        raise ValueError("Asset must belong to Wiki")
    return {"source_path": relative, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "artifact_kind": page.get("artifact_kind", "wiki"),
            "skill_id": page.get("skill_id"), "skill_version": page.get("skill_version"),
            "skill_category": page.get("skill_category"), "options": page.get("options", [])}


def agreement_context(root: Path, agreement: dict | None, scope: str | None) -> dict | None:
    if agreement is None:
        return None
    from .tasks import require_active_scope
    require_active_scope(root, scope)
    from .handoff import check
    result = check(root, agreement, scope or "")
    if result["status"] != "current":
        raise ValueError("Task agreement needs review: " + ", ".join(i["code"] for i in result["issues"]))
    return {"sha256": agreement["sha256"], "scope": scope,
            "goal_path": agreement["goal"]["path"], "goal_sha256": agreement["goal"]["sha256"],
            "status": "current", "execution_verified": False}


def _path(root: Path) -> Path:
    path = root / ".oks" / "retrieval-debug.json"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Debug storage escapes knowledge root")
    return path


def read_records(root: Path) -> dict:
    path = _path(root)
    if not path.exists():
        return {"schema_version": "retrieval-debug/v1", "records": [], "status": "empty"}
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Debug record store exceeds size limit")
        records = json.loads(data)
        if not isinstance(records, list) or len(records) > MAX_RECORDS or any(not isinstance(r, dict) for r in records):
            raise ValueError("Invalid debug record store")
        for item in records:
            if not isinstance(item.get("diagnostics"), dict) or not isinstance(item.get("stage"), str):
                raise ValueError("Invalid debug record")
            for key in ("hits", "emitted"):
                if not isinstance(item.get(key), list) or any(not isinstance(v, dict) for v in item[key]):
                    raise ValueError("Invalid debug record items")
        return {"schema_version": "retrieval-debug/v1", "records": records, "status": "ok"}
    except (OSError, ValueError, UnicodeError):
        return {"schema_version": "retrieval-debug/v1", "records": [], "status": "error",
                "error": "Cannot read debug records; existing data was preserved"}


def query_record(root: Path, identifier: str) -> dict:
    """Resolve an explicit retained query, never infer the latest query."""
    if not isinstance(identifier, str) or not identifier or len(identifier) > 64:
        raise ValueError("Invalid retrieval record ID")
    data = read_records(root)
    if data['status'] == 'error':
        raise ValueError(data['error'])
    found = next((r for r in data['records'] if r.get('id') == identifier), None)
    if found is None:
        raise ValueError("Retrieval record is missing or expired; query again")
    return found


def source_hit(root: Path, identifier: str, source: str) -> dict:
    from .handoff import _read
    item = query_record(root, identifier)
    hit = next((h for h in item['hits'] if h.get('source_path') == source), None)
    if hit is None:
        raise ValueError("Source was not returned by this query")
    if hashlib.sha256(_read(root, source, 'wiki')).hexdigest() != hit.get('source_sha256'):
        raise ValueError("Retrieved source changed; query its current version again")
    return hit


def record_load(root: Path, identifier: str, source: str, version: str, mode: str) -> dict:
    """Record that this CLI returned a pinned Skill; not host consumption."""
    with store._file_lock(root / '.oks/locks/retrieval-debug.lock'):
        hit = source_hit(root, identifier, source)
        if hit.get('artifact_kind') != 'skill' or hit.get('skill_version') != version:
            raise ValueError('Loaded Skill differs from the retrieved version')
        data = read_records(root)
        item = next(r for r in data['records'] if r['id'] == identifier)
        receipt = {'source_path': source, 'source_sha256': hit['source_sha256'],
                   'skill_version': version, 'at': datetime.now(UTC).isoformat(),
                   'mode': mode, 'host_consumed': 'unknown', 'executed': False}
        item['loads'] = [receipt, *[v for v in item.get('loads', []) if v.get('source_path') != source]][:100]
        encoded = json.dumps(data['records'], ensure_ascii=False) + '\n'
        if len(encoded.encode()) > MAX_BYTES:
            raise ValueError('Debug capacity reached; existing records preserved')
        store._atomic_write(_path(root), encoded)
    return receipt


def record(root: Path, query: str, diagnostics: dict, hits: list[dict], *, stage="retrieved", emitted=(), skipped=None) -> str:
    """Keep bounded metadata; never persist prompts, bodies or Goal snapshot text."""
    identifier = uuid.uuid4().hex
    fields = ("slug", "title", "backend", "relevance", "source_path", "source_sha256",
              "artifact_kind", "skill_id", "skill_version", "skill_category", "load_command", "options", "score_components")
    item = {"id": identifier, "at": datetime.now(UTC).isoformat(), "stage": stage,
            "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "diagnostics": diagnostics, "hits": [{k: h[k] for k in fields if k in h} for h in hits[:100]],
            "emitted": list(emitted), "skipped": skipped or {}, "host_consumed": "unknown", "executed": False}
    if len(json.dumps(item, ensure_ascii=False).encode()) > MAX_BYTES // 2:
        raise ValueError("Debug record too large")
    path = _path(root)
    with store._file_lock(root / ".oks/locks/retrieval-debug.lock"):
        previous = read_records(root)
        if previous["status"] == "error":
            raise ValueError(previous["error"])
        items = [item, *previous["records"]][:MAX_RECORDS]
        while len((encoded := json.dumps(items, ensure_ascii=False, default=str)).encode()) + 1 > MAX_BYTES:
            items.pop()
        store._atomic_write(path, encoded + "\n")
    return identifier


def overview(root: Path) -> dict:
    result = read_records(root)
    # Task checkpoints are caller-reported associations, not execution receipts.
    from . import tasks
    by_id = {r.get('id'): r for r in result['records']}
    for record in by_id.values():
        record['usage'] = []
    for path in sorted((root / '.oks/tasks').glob('*.json'))[:100]:
        try:
            task = tasks._load(root, path.stem)
            for revision in [task, *reversed(task['history'])]:
                for use in revision.get('uses', []):
                    record = by_id.get(use['retrieval_id'])
                    if record is None or len(record['usage']) >= 20:
                        continue
                    assets = []
                    for asset in use['artifacts']:
                        try:
                            status = 'unchanged' if tasks._artifact(root, asset['path']) == asset else 'changed'
                        except (OSError, ValueError):
                            status = 'unavailable'
                        assets.append({**asset, 'status': status})
                    record['usage'].append({**use, 'task_id': task['task_id'],
                                            'revision': revision['revision'], 'artifacts': assets})
        except (OSError, ValueError, KeyError, TypeError):
            result['usage_error'] = 'Some task usage records could not be read'
    # Deployment is its own observed fact, never inferred from a search hit.
    receipts = root / ".oks/skill-loads.json"
    result["deployments"] = []
    if receipts.exists() and receipts.resolve().is_relative_to(root.resolve()):
        try:
            with receipts.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Deployment receipt too large")
            values = json.loads(data)
            result["deployments"] = [{"host_skill": k, "version": v.get("version"), "loaded_at": v.get("loaded_at"),
                                       "stage": "deployed_receipt", "host_loaded": "unknown"}
                                      for k, v in values.items() if isinstance(v, dict)]
        except (OSError, ValueError, AttributeError):
            result["deployment_error"] = "Cannot read deployment receipts"
    return result
