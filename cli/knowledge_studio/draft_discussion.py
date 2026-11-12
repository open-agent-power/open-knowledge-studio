"""Draft-centred discussion: file nodes, recorded processing and Mail comments.

This is a read projection. Review decisions still belong to draft_review;
neither sources nor comments are copied into the Draft or Wiki.
"""
from __future__ import annotations

import difflib
import hashlib
from itertools import islice
from pathlib import Path

import yaml

from . import discussion_comments, draft_review, mail_knowledge, studio, studio_history, studio_workflow, workspace


def _source_tokens(root, file):
    if file.get('format') == 'text':
        return []
    meta, body, _ = studio._markdown(file['text'])
    return studio._references(root, file['path'], meta, body, {}) + mail_knowledge._as_list(meta.get('sources'))


def _sources(root, file, aliases):
    resolved = []
    for token in _source_tokens(root, file):
        token = token.replace('\\', '/')
        if token in aliases:
            resolved.append(aliases[token])
            continue
        try:
            path = studio._path(root, token)
            if path.suffix.lower() == '.md' and path.is_file():
                resolved.append(path.relative_to(root).as_posix())
        except ValueError:
            continue
    return list(dict.fromkeys(resolved))


def _read_source(root, relative, documents):
    info = documents.get(relative)
    source = info['body_path'] if info else relative
    if source.startswith('raw/') and Path(source).suffix.lower() == '.txt':
        path = studio._path(root, source)
        file = workspace._text_file(root, path.relative_to(root.resolve()).as_posix(), {'.txt'})
        file.update(title=path.stem, kind='raw', outline=[])
    else:
        file = studio.read_file(root, source)
    if info:
        meta, body = {}, file['text']
        if file['format'] == 'markdown':
            meta, body, _ = studio._markdown(file['text'])
        file.update(info, path=relative,
                    title=mail_knowledge._source_title(meta, body, Path(relative), file['title']))
        if file['processing_status'] == 'unknown':
            file['processing_status'] = str(meta.get('processing_status') or 'unknown')
    return file


def graph(root):
    root = Path(root).resolve()
    nodes, edges, files, warnings = [], [], {}, []
    paths = list(islice((root / 'drafts').rglob('*.md'), studio.MAX_SCAN + 1))
    if len(paths) > studio.MAX_SCAN:
        warnings.append(f'仅显示前 {studio.MAX_SCAN} 份草稿，请缩小知识库范围。')
    promotions = draft_review.promotions(root)
    for path in sorted(paths[:studio.MAX_SCAN]):
        relative = path.relative_to(root).as_posix()
        try:
            file = studio.read_file(root, relative)
            review = workspace.draft(root, relative, promotions=promotions) if len(path.relative_to(root).parts) == 2 else {}
            status = review.get('review_status', 'draft')
            files[relative] = file
            nodes.append({'id': relative, 'path': relative, 'title': file['title'],
                          'type': 'drafts', 'review_status': status})
        except (OSError, ValueError, UnicodeError, yaml.YAMLError) as error:
            warnings.append(f'{relative}: {error}')
    draft_paths = set(files)
    raw_documents, raw_aliases, raw_warnings = mail_knowledge._raw_documents(
        root, references=[token for file in files.values() for token in _source_tokens(root, file)])
    warnings.extend(raw_warnings)
    for relative in sorted(draft_paths):
        for target in _sources(root, files[relative], raw_aliases):
            if target == relative:
                continue
            if target not in files:
                try:
                    files[target] = _read_source(root, target, raw_documents)
                    nodes.append({'id': target, 'path': target, 'title': files[target]['title'],
                                  'type': 'source'})
                except (OSError, ValueError, UnicodeError, yaml.YAMLError) as error:
                    warnings.append(f'{target}: {error}')
                    continue
            edges.append({'from': relative, 'to': target, 'type': 'reference', 'label': '引用'})
    version = hashlib.sha256(repr([(n['id'], files[n['id']]['sha256'], n.get('review_status'))
                                  for n in nodes]).encode()).hexdigest()
    return {'knowledge_base': str(root), 'scope': 'drafts', 'entry': '', 'entries': sorted(draft_paths),
            'nodes': nodes, 'edges': edges, 'files': files, 'version': version, 'warnings': warnings}


def _history(root, file):
    events = []
    for path in islice((root / 'records/timeline').glob('*/*/*/*.json'), 2000):
        try:
            event = studio_history._read(root, path.relative_to(root).as_posix())
            if (event.get('path') == file['path'] and event.get('status') == 'complete'
                    and event.get('action') != 'baseline'):
                events.append(event)
        except (OSError, ValueError, UnicodeError):
            continue
    return sorted(events, key=lambda event: (event['at'], event['id']))[-30:]


def reader(root, relative):
    root = Path(root).resolve()
    if relative.startswith('raw/'):
        raw_documents, raw_aliases, raw_warnings = mail_knowledge._raw_documents(root, references=[relative])
        file = _read_source(root, raw_aliases.get(relative, relative), raw_documents)
    else:
        file = studio.read_file(root, relative)
        raw_documents, raw_aliases, raw_warnings = mail_knowledge._raw_documents(
            root, references=_source_tokens(root, file))
    result = {**file, 'knowledge_base': str(root), 'sources': [], 'steps': [], 'changes': '', 'warnings': []}
    result['warnings'].extend(raw_warnings)
    for path in _sources(root, file, raw_aliases):
        try:
            source = _read_source(root, path, raw_documents)
            result['sources'].append({'path': path, 'title': source['title'],
                'aliases': sorted(alias for alias, canonical in raw_aliases.items() if canonical == path)})
        except (OSError, ValueError, UnicodeError, yaml.YAMLError):
            result['warnings'].append(f'{path}: 无法读取来源')
    if file['kind'] != 'drafts':
        return result
    review = workspace.draft(root, relative) if len(Path(relative).parts) == 2 else {'review_status': 'draft'}
    result.update({key: review.get(key) for key in ('review_status', 'wiki_path', 'workflow_context')})
    result['promotable'] = len(Path(relative).parts) == 2
    doc = discussion_comments.document(root, relative)
    result['anchor_id'] = doc['sections'][0]['id']
    result['discussion'] = discussion_comments.read(root, relative)
    workflow = studio_workflow.processing_workflow(root, doc)
    result['steps'] = workflow['steps']
    result['warnings'].extend(workflow['warnings'])
    for event in _history(root, file):
        labels = {'create': '形成草稿', 'edit': '修改草稿', 'baseline': '首次记录', 'observed_change': '检测到文件修改'}
        result['steps'].append({'id': event['id'], 'kind': 'revision',
            'title': labels.get(event['action'], '保存草稿'), 'status': event['status'], 'at': event['at'],
            'agent': event.get('actor_reported', ''), 'detail': '已保存这一版本的 Markdown。',
            'inputs': [{'title': '修改前', 'text': studio._markdown(event['before'])[1]}] if event.get('before') else [],
            'outputs': [{'path': relative, 'title': file['title'], 'text': studio._markdown(event['after'])[1]}]})
        if event.get('before') is not None and event.get('after_sha256') == file['sha256']:
            result['changes'] = ''.join(difflib.unified_diff(
                studio._markdown(event['before'])[1].splitlines(keepends=True),
                studio._markdown(event['after'])[1].splitlines(keepends=True),
                fromfile='修改前', tofile='当前草稿'))
    return result
