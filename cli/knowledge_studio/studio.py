"""File-backed views of goals and their explicitly written context.

This is a projection, not another task store. Task agreements, review decisions,
Skill versions and retrieval telemetry remain owned by their existing modules.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import posixpath
import re
from contextlib import nullcontext
from itertools import islice

import yaml

from . import handoff, store, tasks, workspace, layout, studio_history

GOAL_ROOTS = ('profiles/goals', 'goal')
DISCUSS_ROOTS = ('profiles/discuss', 'discuss')
READ_ROOTS = ('goal', 'profiles', 'project', 'discuss', 'wiki', 'raw', 'drafts', 'skill', 'skills', 'mail', 'records')
MAX_FILES = 80
MAX_GRAPH_BYTES = 2 * 1024 * 1024
MAX_SCAN = 400
METADATA_HEADINGS = {'备注', '说明', '关联知识', '来源', '讨论', '子目标', 'references', 'sources', 'notes'}


def _path(root, relative, *, goal=False):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Choose a relative knowledge path')
    parts = relative.split('/')
    if any(not part or part.startswith('.') for part in parts):
        raise ValueError('Choose a canonical path without hidden components')
    allowed = any(relative == prefix or relative.startswith(prefix + '/')
                  for prefix in (GOAL_ROOTS if goal else READ_ROOTS))
    if not allowed:
        raise ValueError('Path is outside the selected knowledge buckets')
    return tasks._inside(root.resolve(), layout.canonical(root.resolve(), relative))


def _read_document(root, relative):
    relative = _path(root, relative).relative_to(root.resolve()).as_posix()
    item = workspace._text_file(root, relative, {'.md'})
    kind = ('goal' if any(relative.startswith(p + '/') for p in GOAL_ROOTS)
            else 'discuss' if any(relative.startswith(p + '/') for p in DISCUSS_ROOTS)
            else relative.split('/')[0])
    if kind == 'mail':
        from .mail import parse_message_text
        meta = parse_message_text(root / relative, item['text'])['meta']
        # Keep the original Markdown heading, whitespace and source line identities.
        front = re.match(r'\A\ufeff?---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)', item['text'])
        body = item['text'][front.end():] if front else item['text']
        offset = item['text'][:len(item['text']) - len(body)].count('\n')
    else:
        meta, body, offset = _markdown(item['text'])
    title = _title(body, str(meta.get('title') or Path(relative).stem)) if kind == 'goal' else str(meta.get('title') or _title(body, Path(relative).stem))
    return {**item, 'title': title, 'kind': kind}, meta, body, offset


def read_file(root, relative):
    item, _, body, offset = _read_document(root, relative)
    return {**item, 'outline': _outline(body, offset)}


def _markdown(text):
    match = re.match(r'\A\ufeff?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)', text)
    if not match:
        return {}, text, 0
    meta = yaml.safe_load(match[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError('Markdown frontmatter must be a mapping')
    return meta, text[match.end():], text[:match.end()].count('\n')


def _title(body, fallback):
    match = re.search(r'^#\s+(?:\[[ xX]\]\s*)?(.+?)\s*#*\s*$', _visible_markdown(body), re.M)
    return match[1] if match else fallback


def _visible_markdown(body):
    """Code samples/comments are source text, not written graph relationships."""
    lines, fence = [], None
    for line in body.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            if fence is None:
                fence = (match[1][0], len(match[1]))
            elif match[1][0] == fence[0] and len(match[1]) >= fence[1]:
                fence = None
            lines.append('')
        else:
            lines.append('' if fence else line)
    visible = re.sub(r'<!--[\s\S]*?-->', '', '\n'.join(lines))
    return re.sub(r'(`+)[^\n]*?\1', '', visible)


def outline(text):
    """Keep source line identities; descriptions and fenced code are never TODOs."""
    _, body, offset = _markdown(text)
    return _outline(body, offset)


def _outline(body, offset):
    rows, stack = [], []
    level, fenced, metadata = 1, None, False
    for number, line in enumerate(body.splitlines(), offset):
        fence = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            if fenced is None:
                fenced = fence[1][0]
            elif fence[1][0] == fenced:
                fenced = None
            continue
        if fenced or not line.strip():
            continue
        heading = re.match(r'^(#{1,6})\s+(?:\[([ xX])\]\s*)?(.+?)\s*#*\s*$', line)
        task = re.match(r'^(\s*)[-*+]\s+\[([ xX])\]\s*(.*)$', line)
        if heading:
            level = len(heading[1])
            metadata = heading[3].lower().strip() in METADATA_HEADINGS
            row = {'kind': 'metadata' if metadata else 'heading', 'level': level,
                   'text': heading[3], 'checked': (heading[2] or '').lower() == 'x'}
        elif task and not metadata:
            row = {'kind': 'task', 'level': level + 1 + len(task[1].expandtabs(4)) // 2,
                   'text': task[3], 'checked': task[2].lower() == 'x'}
        else:
            row = {'kind': 'note', 'level': level + 1, 'text': line.strip()}
        while stack and stack[-1]['level'] >= row['level']:
            stack.pop()
        row.update(line=number, parent=stack[-1]['line'] if stack else None)
        rows.append(row)
        if row['kind'] in {'heading', 'task', 'metadata'}:
            stack.append(row)
    return rows


def scopes(root, kind="goal"):
    result, warnings = [], []
    if kind not in {"goal", "discuss"}:
        raise ValueError("Choose goal or discuss")
    for bucket in (DISCUSS_ROOTS if kind == "discuss" else GOAL_ROOTS):
        base = root / bucket
        if not base.is_dir():
            continue
        paths = list(islice(base.rglob('*.md'), MAX_SCAN + 1))
        if len(paths) > MAX_SCAN:
            warnings.append(f'{bucket}: listing limited to {MAX_SCAN} files')
        grouped = {}
        for path in sorted(paths[:MAX_SCAN]):
            relative = path.relative_to(root).as_posix()
            try:
                _path(root, relative, goal=kind != "discuss")
                read, _, _, _ = _read_document(root, relative)
            except (OSError, ValueError, UnicodeError, yaml.YAMLError):
                warnings.append(relative + ': unavailable')
                continue
            scope = path.parent.relative_to(root).as_posix() if path.parent != base else relative
            grouped.setdefault(scope, []).append(read)
        for scope, items in grouped.items():
            first = next((p for p in items if Path(p['path']).stem.lower() in {'index', 'readme'}), items[0])
            result.append({'path': scope, 'title': first['title'], 'entry': first['path'],
                           'files': [{'path': p['path'], 'title': p['title'], 'date': document_date(p['path'])} for p in items]})
    return {'scopes': result, 'warnings': warnings}


def document_path(root, path):
    discussion = isinstance(path, str) and any(path == p or path.startswith(p + '/') for p in (*DISCUSS_ROOTS, 'drafts'))
    return _path(root, path, goal=not discussion)


def document_date(path):
    match = re.match(r'^(?:goal|discuss|profiles/goals|profiles/discuss)/(\d{4})/(\d{2})/(\d{2})(?:/|$)', path)
    if match:
        from datetime import date
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def context_catalog(root):
    """Project real context files, not inferred user identities or approved Wiki."""
    entries, warnings, documents = [], [], {}
    buckets = ('profiles', 'project', 'goal', 'discuss')
    for bucket in buckets:
        base = root / bucket
        if not base.is_dir():
            continue
        paths = list(islice(base.rglob('*.md'), MAX_SCAN + 1))
        if len(paths) > MAX_SCAN:
            warnings.append(bucket + ': listing truncated')
        for path in sorted(paths[:MAX_SCAN]):
            relative = path.relative_to(root).as_posix()
            if relative.startswith('profiles/projects/') or relative.startswith('project/'):
                kind = 'project'
            elif relative.startswith('profiles/goals/') or bucket == 'goal':
                kind = 'goal'
            elif any(relative.startswith(p + '/') for p in DISCUSS_ROOTS):
                kind = 'discuss'
            else:
                kind = 'profile'
            try:
                item, meta, body, _ = _read_document(root, relative)
                documents[relative] = (meta, body)
                entries.append({'id': relative, 'path': relative, 'title': item['title'], 'type': kind,
                    'body': body[:12000], 'body_truncated': len(body) > 12000,
                    'date': document_date(relative), 'group': str(Path(relative).parent),
                    'metadata': {key: str(value) for key, value in meta.items()}})
            except (OSError, ValueError, UnicodeError, yaml.YAMLError):
                warnings.append(relative + ': unavailable')
    # Only written, resolvable references become graph relations.
    index = {}
    for path in islice((root / 'wiki').rglob('*.md'), 3001):
        index.setdefault(path.stem, []).append(path.relative_to(root).as_posix())
    edges = []
    for entry in entries:
        meta, body = documents[entry['path']]
        for target in _references(root, entry['path'], meta, body, index):
            edges.append({'a': entry['id'], 'b': target, 'type': 'cites'})
    from . import linked_sources, mail
    teams = linked_sources.catalog(root)
    warnings.extend(teams['warnings'])
    for source in teams['sources']:
        entries.extend({**e, 'body': e['body'][:12000], 'body_truncated': len(e['body']) > 12000}
                       for e in source['entries'])
    for message in islice(mail.iter_messages(root, 'human'), 200):
        meta = message['meta']
        identifier = 'mail:' + str(meta['message_id'])
        body = message.get('body', '')
        entries.append({'id': identifier, 'type': 'mail', 'family': 'mail', 'title': message['title'],
            'group': str(meta.get('thread_id') or 'Mail'), 'path': message['path'].relative_to(root).as_posix(),
            'body': body[:12000], 'body_truncated': len(body) > 12000,
            'metadata': {**{key:str(meta.get(key,'')) for key in ('from','to','thread_id','reply_to','record_kind')},
                         **{key:str(value) for key,value in message.get('state',{}).items()}}})
        message_meta, message_body, _ = _markdown(body)
        for target in _references(root, entries[-1]['path'], message_meta, message_body, index):
            edges.append({'a': identifier, 'b': target, 'type': 'cites'})
        if meta.get('reply_to'):
            edges.append({'a': identifier, 'b':'mail:'+str(meta['reply_to']), 'type':'reply_to'})
    edges.extend(linked_sources.relations(entries))
    return {'entries': entries, 'edges': edges, 'warnings': warnings}


def _references(root, path, meta, body, wiki_index):
    body = _visible_markdown(body)
    tokens = re.findall(r'(?<!\\)\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', body)
    tokens += re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)', body)
    for key in ('sources', 'source_refs', 'goals', 'knowledge', 'skills', 'relates_to', 'related'):
        values = meta.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            tokens += [v for v in values if isinstance(v, str)]
    resolved = []
    for token in tokens:
        token = token.split('#')[0].strip().strip('`')
        if not token or token.startswith(('#', 'http:', 'https:', 'mailto:')):
            continue
        options = [token, token + '.md']
        local = posixpath.normpath(str(PurePosixPath(path).parent / token))
        options += [local, local + '.md']
        if token in wiki_index and len(wiki_index[token]) == 1:
            options.append(wiki_index[token][0])
        for candidate in options:
            try:
                target = _path(root, candidate)
                if target.suffix.lower() == '.md' and target.is_file():
                    resolved.append(target.relative_to(root.resolve()).as_posix())
                    break
            except ValueError:
                continue
    return list(dict.fromkeys(resolved))


def view(root, scope, *, seed_paths=None):
    target = document_path(root, scope)
    if seed_paths is not None:
        seeds = seed_paths
    elif target.is_dir():
        seeds = sorted(p.relative_to(root).as_posix() for p in islice(target.rglob('*.md'), MAX_FILES + 1))
    elif target.suffix.lower() == '.md':
        seeds = [scope]
    else:
        raise ValueError('Choose a Goal Markdown file or folder')
    if not seeds:
        raise ValueError('No Goal Markdown files in this scope')
    warnings, files, edges, discussion_context, total = [], {}, [], [], 0
    if len(seeds) > MAX_FILES:
        warnings.append('Goal scope exceeds file limit')
    wiki_index = {}
    wiki_paths = list(islice((root / 'wiki').rglob('*.md'), 3001))
    if len(wiki_paths) > 3000:
        warnings.append('Wiki slug lookup limited to 3000 files; explicit paths remain available')
    for p in wiki_paths[:3000]:
        wiki_index.setdefault(p.stem, []).append(p.relative_to(root).as_posix())
    queue = seeds[:MAX_FILES]
    # Written discussion links can point into the chosen Goal scope. Do not
    # infer current chat/session or relevance from file modification times.
    discussions = list(islice((path for bucket in DISCUSS_ROOTS
                              for path in (root / bucket).rglob('*.md')), MAX_SCAN + 1))
    if len(discussions) > MAX_SCAN:
        warnings.append(f'Discussion reverse lookup limited to {MAX_SCAN} files')
    documents = {}
    for p in discussions[:MAX_SCAN]:
        rel = p.relative_to(root).as_posix()
        try:
            item, meta, body, offset = _read_document(root, rel)
            if any(ref in seeds for ref in _references(root, rel, meta, body, wiki_index)):
                queue.append(rel)
                if len(documents) < MAX_FILES:
                    documents[rel] = item, meta, body, offset
        except (OSError, ValueError, UnicodeError, yaml.YAMLError):
            warnings.append(rel + ': unavailable')
    while queue and len(files) < MAX_FILES:
        path = queue.pop(0)
        if path in files:
            continue
        try:
            item, meta, body, offset = documents.pop(path) if path in documents else _read_document(root, path)
        except (OSError, ValueError, UnicodeError, yaml.YAMLError):
            warnings.append(path + ': unavailable')
            continue
        total += len(item['text'].encode('utf-8'))
        if total > MAX_GRAPH_BYTES:
            warnings.append('Context byte limit reached')
            break
        files[path] = {**item, 'outline': _outline(body, offset)}
        if item['kind'] == 'discuss':
            discussion_context.append((path, meta, body))
        child_refs = set()
        if item['kind'] == 'goal':
            for section in re.finditer(r'^#{1,6}\s+(?:子目标|任务分解|Subgoals)\s*\n([\s\S]*?)(?=^#{1,6}\s|\Z)', _visible_markdown(item['text']), re.M | re.I):
                section_meta, section_body, _ = _markdown(section[1])
                child_refs.update(_references(root, path, section_meta, section_body, wiki_index))
        for ref in _references(root, path, meta, body, wiki_index):
            relation = 'contains' if ref in child_refs else 'source' if ref.startswith(('raw/', 'records/')) else 'cites'
            edges.append({'from': path, 'to': ref, 'type': relation,
                          'evidence': path, 'origin': 'written_reference'})
            if ref not in files:
                queue.append(ref)
    if queue:
        warnings.append('Context file limit reached')
    nodes = [{'id': p, 'path': p, 'type': item['kind'], 'title': item['title'], 'sha256': item['sha256']}
             for p, item in files.items()]
    for p, meta, body in discussion_context:
        body = _visible_markdown(body)
        for label, kind in [('人的判断', 'human_judgment'), ('AI 理解', 'agent_understanding'), ('待确认', 'open_question')]:
            match = re.search(r'^##\s+' + re.escape(label) + r'\s*\n([\s\S]*?)(?=^##\s|\Z)', body, re.M)
            if match and match[1].strip():
                identity = p + '#' + kind
                nodes.append({'id': identity, 'path': p, 'type': kind, 'title': label,
                              'text': match[1].strip(), 'alignment': meta.get('alignment', 'unspecified')})
                edges.append({'from': p, 'to': identity, 'type': 'states', 'evidence': p, 'origin': 'written_section'})
    ids = {n['id'] for n in nodes}
    edges = [e for e in edges if e['from'] in ids and e['to'] in ids]
    version = hashlib.sha256(json.dumps([(p, i['sha256']) for p, i in files.items()], ensure_ascii=False).encode()).hexdigest()
    readable_goals = [p for p in seeds if p in files]
    if not readable_goals:
        raise ValueError('No readable Goal files in this scope')
    entry = next((p for p in readable_goals if Path(p).stem.lower() in {'index', 'readme'}), readable_goals[0])
    return {'scope': scope, 'entry': entry, 'entries': readable_goals, 'files': files, 'nodes': nodes, 'edges': edges,
            'version': version, 'warnings': list(dict.fromkeys(warnings)),
            'replay': 'current_projection_only', 'knowledge_base': str(root)}


def save_file(root, request):
    path, text = request.get('path'), request.get('text')
    target = document_path(root, path)
    path = target.relative_to(root.resolve()).as_posix()
    if target.suffix.lower() != '.md' or not isinstance(text, str) or not text.strip():
        raise ValueError('Provide a nonempty Goal Markdown document')
    if len(text.encode('utf-8')) > 60000 or '\x00' in text:
        raise ValueError('Goal exceeds the editor limit')
    _markdown(text)  # validate frontmatter before any write
    lock = tasks._inside(root, '.oks/locks/goal-' + hashlib.sha256(path.encode()).hexdigest() + '.lock')
    from .draft_review import review_lock
    review_guard = review_lock(root, Path(path).stem) if path.startswith('drafts/') and len(Path(path).parts) == 2 else nullcontext()
    with review_guard, store._file_lock(lock):
        document_path(root, path)  # recheck after acquiring the writer lock
        before = None
        if request.get('create') is True:
            if target.exists() or request.get('expected_sha256') is not None:
                raise ValueError('Goal already exists; read it before editing')
        else:
            current = read_file(root, path)
            before = current['text']
            if current['sha256'] != request.get('expected_sha256'):
                raise ValueError('Goal changed; reload before saving')
        if before != text:
            event=studio_history.record(root,path,before,text,action='create' if before is None else 'edit',actor=str(request.get('actor','unspecified'))[:100],status='prepared')
            try:
                store._atomic_write(target, text)
            except OSError:
                studio_history.finish(root,event,'failed')
                raise
            studio_history.finish(root,event)
            studio_history.checkpoint(root,path,text)
    return read_file(root, path)


def day_view(root, selected_kind, date):
    from datetime import datetime
    datetime.strptime(date,'%Y-%m-%d')
    if selected_kind not in {'goal','discuss'}:raise ValueError('Choose goal or discuss')
    activity=studio_history.events(root,date,selected_kind)
    listing=scopes(root,selected_kind)
    paths=[f['path'] for scope in listing['scopes'] for f in scope['files'] if f['date']==date]
    paths += [e['path'] for e in activity if (root/e['path']).is_file()]
    paths=list(dict.fromkeys(paths))
    scope=(layout.GOALS if selected_kind=='goal' else layout.DISCUSS)+'/'+date.replace('-','/')
    if not paths:
        return {'scope':scope,'date':date,'entry':'','entries':[],'files':{},'nodes':[],'edges':[],
                'timeline':activity,'version':date,'warnings':listing['warnings'],'knowledge_base':str(root)}
    result=view(root,scope,seed_paths=paths)
    result.update(date=date,timeline=studio_history.events(root,date,selected_kind))
    result['version'] += ':' + hashlib.sha256(json.dumps(result['timeline'],sort_keys=True).encode()).hexdigest()
    return result


def revision_view(root, identifier):
    """Reconstruct only documents actually retained by this point that day."""
    from datetime import datetime
    event = studio_history.snapshot(root, identifier)
    date = datetime.fromisoformat(event['at']).date().isoformat()
    retained = {}
    for row in studio_history.events(root, date, event['kind'], snapshots=True):
        if row.get('status', 'complete') != 'complete':
            continue
        retained[row['path']] = row
        if row['id'] == identifier:
            break
    files, nodes, edges = {}, [], []
    for path, row in retained.items():
        text = row['after']
        meta, body, _ = _markdown(text)
        file = {'path': path, 'text': text, 'sha256': row['after_sha256'], 'kind': row['kind'],
                'title': _title(body, str(meta.get('title') or Path(path).stem)) if row['kind']=='goal' else str(meta.get('title') or _title(body, Path(path).stem)), 'outline': outline(text)}
        files[path] = file
        nodes.append({'id': path, 'path': path, 'type': row['kind'], 'title': file['title']})
        if row['kind'] == 'discuss':
            for label, kind in [('人的判断', 'human_judgment'), ('AI 理解', 'agent_understanding'), ('待确认', 'open_question')]:
                match = re.search(r'^##\s+' + label + r'\s*\n([\s\S]*?)(?=^##\s|\Z)', _visible_markdown(body), re.M)
                if match and match[1].strip():
                    identity = path + '#' + kind
                    nodes.append({'id': identity, 'path': path, 'type': kind, 'title': label, 'text': match[1].strip()})
                    edges.append({'from': path, 'to': identity, 'type': 'states'})
    return {'entry': event['path'], 'entries': list(files), 'files': files, 'nodes': nodes, 'edges': edges,
            'revision': event, 'knowledge_base': str(root), 'read_only': True,
            'coverage': 'Only retained documents at or before this recorded point; no reconstruction of unknown past'}


def local_skills(root):
    result, warnings = [], []
    bases = ('skills',) if (root/'skills').is_dir() else ('skill',)
    for p in islice((p for base in bases for p in (root/base).rglob('SKILL.md')), MAX_SCAN):
        rel = p.relative_to(root).as_posix()
        try:
            item, meta, _, _ = _read_document(root, rel)
            result.append({'path': rel, 'title': str(meta.get('name') or p.parent.name), 'sha256': item['sha256']})
        except (OSError, ValueError, UnicodeError, yaml.YAMLError):
            warnings.append(rel + ': unavailable')
    return {'skills': result, 'warnings': warnings}


def usage(root):
    """Project existing explicit-use counters; never treat recall as adoption."""
    path = tasks._inside(root, '.oks/access.json')
    warnings, counts = [], {}
    if path.exists():
        with path.open('rb') as stream:
            raw = stream.read(workspace.TEXT_LIMIT + 1)
        try:
            if len(raw) > workspace.TEXT_LIMIT:
                raise ValueError('Use counter limit reached')
            counts = json.loads(raw)
            if not isinstance(counts, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in counts.items()):
                raise ValueError('Invalid use counters')
        except (ValueError, UnicodeError):
            counts = {}
            warnings.append('显式使用计数无法完整读取；原记录保留。')
    return {'source': '.oks/access.json', 'entries': [{'slug': slug, 'count': count}
            for slug, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))],
            'warnings': warnings, 'timing_recorded': False,
            'meaning': 'Explicit oks wiki use counts; not task success, human approval, or a timestamped call trace'}


PARAMS = {
    'search_backend': ((None, 'search_backend'), str),
    'recall_topn': (('recall', 'topn'), int), 'recall_floor': (('recall', 'floor'), float),
    'recall_minlen': (('recall', 'minlen'), int), 'recall_cooldown': (('recall', 'cooldown'), int),
    'embedding_fallback': ((None, 'embedding_fallback'), bool),
    'posttool_mode': (('posttool', 'mode'), str),
    'posttool_signal_rel_floor': (('posttool', 'signal_rel_floor'), float),
    'conflict_window': (('conflict', 'window'), int), 'mail_topn': ((None, 'mail_topn'), int),
    'inject_budget_chars': (('inject', 'budget_chars'), int),
    'inject_per_page_chars': (('inject', 'per_page_chars'), int),
    'inject_title_only_floor': (('inject', 'title_only_floor'), float),
    'debug_record': ((None, 'debug_record'), bool), 'memory_validity': ((None, 'memory_validity'), str),
}


def settings(root):
    from .recall import load_recall_params
    path = tasks._inside(root, 'settings/recall.yaml')
    if path.exists():
        with path.open('rb') as stream:
            raw = stream.read(workspace.TEXT_LIMIT + 1)
    else:
        raw = b''
    if len(raw) > workspace.TEXT_LIMIT:
        raise ValueError('Recall settings exceed the reader limit')
    return {'values': load_recall_params(root), 'sha256': hashlib.sha256(raw).hexdigest(),
            'path': 'settings/recall.yaml', 'fixed': {'decay_lambda': store.DECAY_LAMBDA,
                    'decay_defaults': store.DEFAULT_CONFIG['decay'], 'access_bonus': '0.5 * ln(1 + access_count)'}}


def save_settings(root, request):
    updates = request.get('values')
    if not isinstance(updates, dict) or not updates or set(updates) - PARAMS.keys():
        raise ValueError('Choose supported recall parameters')
    choices = {'memory_validity': {'shadow', 'enforce'}, 'posttool_mode': {'signal', 'full'}}
    for key, value in updates.items():
        kind = PARAMS[key][1]
        if ((kind in {int, bool, str} and type(value) is not kind)
                or (kind is float and (type(value) not in {int, float} or not math.isfinite(value)))
                or (kind in {int, float} and not 0 <= value <= 1_000_000)
                or (kind is str and (not value or len(value) > 80))
                or (key in choices and value not in choices[key])):
            raise ValueError('Invalid recall parameter: ' + key)
    path = tasks._inside(root, 'settings/recall.yaml')
    with store._file_lock(tasks._inside(root, '.oks/locks/studio-recall.lock')):
        current = settings(root)
        if current['sha256'] != request.get('expected_sha256'):
            raise ValueError('Settings changed; reload before saving')
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        if not isinstance(data or {}, dict):
            raise ValueError('Recall settings must be a mapping')
        data = data or {}
        for key, value in updates.items():
            section, field = PARAMS[key][0]
            if section:
                if not isinstance(data.setdefault(section, {}), dict):
                    raise ValueError('Recall settings section must be a mapping')
                data[section][field] = value
            else:
                data[field] = value
        store._atomic_write(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return settings(root)


def activity(root,date):
    from datetime import datetime
    from .vfs_observation import history
    datetime.strptime(date,'%Y-%m-%d')
    def on_day(value):
        try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone().date().isoformat()==date
        except (ValueError,TypeError,AttributeError):return False
    queried=set();used=[]
    for row in history(root,'recall')['records']:
        if on_day(row.get('at')):
            queried.update(hit.get('source_path') for hit in row.get('hits',[]) if hit.get('source_path'))
    base=tasks._inside(root,'records/evaluation/use-events')
    for p in base.glob('*.json'):
        row=json.loads(tasks._inside(root,p.relative_to(root).as_posix()).read_text())
        if on_day(row.get('at')):used.append(row['slug'])
    return {'date':date,'queried_paths':sorted(queried),'used_slugs':used,
            'edited_paths':sorted({e['path'] for e in studio_history.events(root,date)}),
            'meaning':'Dated observed activity only; query is not adoption; historical counters have no date'}
