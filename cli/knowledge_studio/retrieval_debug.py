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


def overview(root: Path, task_id: str | None = None) -> dict:
    result = read_records(root)
    if task_id is not None:
        from .tasks import _id
        task_id = _id(task_id)
    result['knowledge_base'] = str(Path(root).resolve())
    result['task_filter'] = task_id
    result['native_reads'] = []
    native_runs = []
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
    # Native Read receipts are independent of retrieval records. They say only
    # that the host reported a successful Read of this exact reviewed Wiki file.
    folder = root / '.oks/workflow-runs'
    if folder.is_dir() and folder.resolve().is_relative_to(root.resolve()):
        seen = set()
        for path in sorted(folder.glob('*.json'))[:100]:
            try:
                run = tasks._read(tasks._inside(root, path.relative_to(root).as_posix()))
                if run.get('private_scope') is True or (task_id and run.get('task_id') != task_id):
                    continue
                if run.get('run_id') == path.stem:
                    native_runs.append(run)
                reads = run.get('native_reads', [])
                if not isinstance(reads, list):
                    continue
                for item in reads[:100]:
                    if not isinstance(item, dict):
                        continue
                    event_id = item.get('event_id')
                    identity = (run.get('run_id'), event_id)
                    if not isinstance(event_id, str) or not event_id or identity in seen:
                        continue
                    row = {key: item.get(key) for key in (
                        'event_id', 'task_id', 'run_id', 'host', 'revision',
                        'source_path', 'source_sha256', 'title', 'observed_at')}
                    if (row['task_id'] != run.get('task_id')
                            or row['run_id'] != run.get('run_id')
                            or row['host'] != run.get('host')):
                        continue
                    seen.add(identity)
                    result['native_reads'].append(row)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    result['native_reads'].sort(key=lambda item: str(item.get('observed_at') or ''), reverse=True)
    # Link only a current, registered returned artifact that visibly cites a
    # source read in the same native task. The response contains metadata only.
    result['native_uses'] = []
    from . import workspace, tasks
    current_by_task = {}
    reads_by_task = {}
    checked_outputs, seen_native_uses = set(), set()
    for read in result['native_reads']:
        reads_by_task.setdefault(read['task_id'], []).append(read)
    for run in sorted(native_runs, key=lambda item: str(item.get('updated_at') or ''), reverse=True):
        if len(checked_outputs) >= 100:
            result['native_uses_truncated'] = True
            break
        tid, run_id, revision = run.get('task_id'), run.get('run_id'), run.get('task_revision')
        if (not isinstance(tid, str) or not isinstance(run_id, str) or type(revision) is not int
                or revision < 1 or run.get('phase') != 'returned' or run.get('status') != 'returned'):
            continue
        reads = reads_by_task.get(tid, [])
        if not reads:
            continue
        try:
            if tid not in current_by_task:
                task = tasks._load(root, tid)
                current_by_task[tid] = tasks._current_artifacts(root, tid, task['artifacts'])
            current = {(ref['path'], ref['sha256']) for ref in current_by_task[tid]}
            refs = run.get('artifacts', [])
            if not isinstance(refs, list):
                continue
            for ref in refs[:16]:
                if not isinstance(ref, dict) or (ref.get('path'), ref.get('sha256')) not in current:
                    continue
                output_key = (tid, ref['path'], ref['sha256'])
                if output_key in checked_outputs:
                    continue
                if len(checked_outputs) >= 100:
                    result['native_uses_truncated'] = True
                    break
                checked_outputs.add(output_key)
                if tasks._artifact(root, ref['path']) != ref:
                    continue
                artifact = workspace.artifact(root, tid, ref['path'], revision)
                if artifact['status'] != 'unchanged':
                    continue
                linked = set(workspace.artifact_source_links(root, ref['path'], artifact['text']).values())
                for read in reads:
                    source = read.get('source_path')
                    if (source not in linked or not isinstance(source, str) or not source.startswith('wiki/')
                            or tasks._artifact(root, source)['sha256'] != read.get('source_sha256')):
                        continue
                    identity = (tid, ref['path'], ref['sha256'], source, read['source_sha256'])
                    if identity in seen_native_uses:
                        continue
                    seen_native_uses.add(identity)
                    event_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                    result['native_uses'].append({'event_id': event_id, 'task_id': tid,
                        'revision': revision, 'source_path': source, 'source_sha256': read['source_sha256'],
                        'title': read['title'], 'artifact': {'path': ref['path'], 'sha256': ref['sha256']},
                        'verification': 'output_citation'})
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            continue
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
    if task_id is not None:
        result['records'] = [record for record in result['records']
                             if ((record.get('diagnostics') or {}).get('task') or {}).get('scope') == task_id
                             or any(item.get('task_id') == task_id for item in record.get('usage', []) if isinstance(item, dict))]
    return result
