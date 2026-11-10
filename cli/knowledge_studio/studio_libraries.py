"""Studio connection settings; repositories keep separate content and history."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

import yaml

from . import config, linked_sources, store, tasks
from .mail_setup import validate_root


def _version(root):
    path = tasks._inside(root, 'settings/sources.yaml')
    return hashlib.sha256(path.read_bytes() if path.is_file() else b'').hexdigest()


def libraries(root):
    return {
        'knowledge_base': str(root),
        'personal_path': str(root),
        'sources': linked_sources.configuration(root),
        'sources_version': _version(root),
    }


def save_sources(root, request):
    rows = request.get('sources')
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError('团队知识库最多关联 20 个')
    previous = {str(Path(row["path"]).expanduser().resolve()): row["name"]
                for row in linked_sources.configuration(root)}
    reserved = set(previous.values())
    validated, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('团队知识库配置无效')
        value = row.get('path')
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError('请填写团队知识库目录')
        path = Path(value.strip()).expanduser().resolve()
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise ValueError('团队库与个人库必须是独立目录')
        # Folder names are the display labels. Keep existing namespace IDs so
        # changing this form never breaks team:<id>/knowledge references.
        name = previous.get(str(path))
        if name is None:
            base = re.sub(r'[^a-zA-Z0-9_-]+', '-', path.name).strip('-')[:48] or 'team'
            name = base
            if name in reserved or name in seen or base == 'team':
                name = base + '-' + hashlib.sha256(str(path).encode()).hexdigest()[:10]
            number = 2
            initial = name
            while name in reserved or name in seen:
                name = initial + '-' + str(number)
                number += 1
        seen.add(name)
        revision = row.get('revision', 'HEAD')
        if not isinstance(revision, str) or (revision != 'HEAD' and not re.fullmatch(r'[0-9a-f]{40}', revision)):
            raise ValueError('版本必须为 HEAD 或完整 commit SHA')
        # Read committed data only; do not import or run linked repository code.
        repository = linked_sources.repository_at(path, revision)
        item = {'name': name, 'path': str(path), 'repository': repository, 'revision': revision}
        linked_sources.snapshot(item)
        if any(v['path'] == str(path) for v in validated):
            raise ValueError('同一个团队库不能重复关联')
        validated.append(item)
    # Validate the whole replacement before writing, and reject stale dialogs.
    with store._file_lock(tasks._inside(root, '.oks/locks/sources.lock')):
        if request.get('sources_version') != _version(root):
            raise ValueError('关联配置已有更新，请重新打开')
        store._atomic_write(tasks._inside(root, 'settings/sources.yaml'), yaml.safe_dump(
            {'schema_version': 1, 'sources': validated}, allow_unicode=True, sort_keys=False))
    return libraries(root)


def switch_personal(server, request):
    value = request.get('personal_path')
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError('请选择已有的个人知识库目录')
    try:
        new_root = validate_root(Path(value.strip()))
    except ValueError as exc:
        raise ValueError('请选择已有的 OKS 个人知识库目录（包含 wiki/ 和 mail/）') from exc
    with server.library_lock:
        if request.get('expected_knowledge_base') != str(server.kb_root):
            raise ValueError('知识库已切换，请重新打开')
        if new_root == server.kb_root:
            return libraries(new_root)
        # Check configuration before moving the session to another repository.
        libraries(new_root)
        from .studio_history import Watcher
        history = Watcher(new_root)
        daily = None
        if (new_root / 'settings/daily-capture.json').is_file():
            from .daily_learning import CaptureService
            daily = CaptureService(new_root)
        current_config = config.load_config()
        current_config['knowledge_base_path'] = str(new_root)
        try:
            history.start()
            if daily is not None:
                daily.start()
            config.save_config(current_config)
        except Exception:
            history.stop()
            if daily is not None:
                daily.stop()
            raise
        for key in ('history_service', 'daily_service'):
            service = getattr(server, key, None)
            if service is not None:
                service.stop()
            setattr(server, key, None)
        server.kb_root = new_root
        server.history_service = history
        if daily is not None:
            server.daily_service = daily
        return libraries(new_root)
