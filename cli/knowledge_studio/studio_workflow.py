"""Read-only declared references and recorded execution; never infer calls."""
from itertools import islice
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

import yaml

from . import studio

MAX_PROCESS_RECORDS = 32
MAX_PROCESS_TEXT = 8000
PROCESS_TEXT_SUFFIXES = {'.md', '.txt', '.json', '.jsonl', '.yaml', '.yml', '.csv', '.log'}


def _process_json(root, relative, warnings):
    try:
        path = studio._path(root, relative)
        if path.stat().st_size > studio.MAX_GRAPH_BYTES:
            raise ValueError('record exceeds the reading limit')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('record must be a JSON object')
        return value
    except (OSError, ValueError, UnicodeError) as error:
        warnings.append(f'{relative}: {error}')
        return {}


def _process_artifact(root, relative, warnings, *, title='', expected=None):
    record = {'path': relative, 'title': title or PurePosixPath(relative).name, 'verification': 'unavailable'}
    try:
        path = studio._path(root, relative)
        if path.stat().st_size > studio.MAX_GRAPH_BYTES:
            raise ValueError('artifact exceeds the reading limit')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        record.update(sha256=digest, verification='verified' if expected == digest else 'changed' if expected else 'recorded')
        if expected:
            record['expected_sha256'] = expected
        if path.suffix.lower() in PROCESS_TEXT_SUFFIXES:
            text = raw.decode('utf-8-sig')
            record.update(text=text[:MAX_PROCESS_TEXT], truncated=len(text) > MAX_PROCESS_TEXT)
        if record['verification'] == 'changed':
            warnings.append(relative + ': artifact differs from the retained record')
    except (OSError, ValueError, UnicodeError) as error:
        warnings.append(f'{relative}: {error}')
    return record


def _process_references(root, owner, meta, body):
    """Only explicit local Raw/Draft references; code examples are not links."""
    visible = studio._visible_markdown(body)
    tokens = re.findall(r'(?<!\\)\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', visible)
    tokens += re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)', visible)
    for key in ('sources', 'source_refs'):
        values = meta.get(key, [])
        tokens += [values] if isinstance(values, str) else values if isinstance(values, list) else []
    references = []
    for token in tokens:
        if not isinstance(token, str):
            continue
        token = token.split('#')[0].strip()
        local = posixpath.normpath(str(PurePosixPath(owner).parent / token))
        for candidate in (token, token + '.md', local, local + '.md'):
            if not candidate.startswith(('raw/', 'drafts/')):
                continue
            try:
                path = studio._path(root, candidate)
                if path.exists():
                    canonical = path.relative_to(root).as_posix()
                    if canonical not in references:
                        references.append(canonical)
                    break
            except ValueError:
                continue
    return references[:MAX_PROCESS_RECORDS]


def _process_sources(root, document, warnings):
    meta, body, _ = studio._markdown(document['text'])
    sources = []
    for reference in _process_references(root, document['path'], meta, body):
        anchor = next((section for section in document['sections']
                       if reference in _process_references(root, document['path'], {}, section['markdown'])), None)
        if reference.startswith('raw/'):
            sources.append((reference, anchor))
        elif reference.startswith('drafts/'):
            try:
                draft = studio.read_file(root, reference)
                draft_meta, draft_body, _ = studio._markdown(draft['text'])
                sources.extend((target, anchor) for target in _process_references(root, reference, draft_meta, draft_body)
                               if target.startswith('raw/'))
            except (OSError, ValueError, UnicodeError, yaml.YAMLError) as error:
                warnings.append(f'{reference}: {error}')
    return sources[:MAX_PROCESS_RECORDS]


def _process_bundle(root, relative, warnings):
    """A nearby bundle counts only when the cited file belongs to its declared layout."""
    target = studio._path(root, relative)
    parents = [PurePosixPath(relative)] if target.is_dir() else []
    parents += list(PurePosixPath(relative).parents)
    for parent in parents:
        if str(parent) == 'raw':
            break
        manifest_path = str(parent / 'bundle.json')
        if not studio._path(root, manifest_path).is_file():
            continue
        bundle = _process_json(root, manifest_path, warnings)
        if bundle.get('schema_version') != 'raw-multimodal/v0.2' or not isinstance(bundle.get('capture_id'), str):
            return None
        members = {'raw.md', 'bundle.json'}
        members.update(value for value in bundle.get('files', {}).values() if isinstance(value, str))
        for collection in ('sources', 'derived'):
            members.update(item['path'] for item in bundle.get(collection, [])
                           if isinstance(item, dict) and isinstance(item.get('path'), str))
        if relative != str(parent) and relative not in {str(parent / member) for member in members}:
            return None
        return parent, bundle
    return None


def _process_base(document, anchor):
    return {'source_sha256': document['sha256'], 'anchor_id': anchor['id'] if anchor else None,
            'anchor_title': anchor['title'] if anchor else None, 'agent': '', 'extractor': None}


def _comment_steps(root, document):
    from . import discussion_comments
    steps = []
    for comment in discussion_comments.read(root, document['path'])['comments']:
        replies = comment['replies']
        result = next((reply['result'] for reply in reversed(replies) if reply.get('result')), None)
        inputs = [{'path': document['path'], 'title': comment['anchor_title'], 'text': comment['anchor_md'],
                   'sha256': comment['source_sha256'],
                   'verification': 'verified' if comment['source_sha256'] == document['sha256'] else 'changed'}]
        inputs.extend({**image, 'title': image['name'], 'verification': 'recorded'} for image in comment['images'])
        outputs = [{'title': reply['from'] + ' 回信', 'text': reply['body'], 'message_id': reply['message_id'],
                    'verification': 'recorded'} for reply in replies]
        if result and result['changed']:
            outputs.append({'path': document['path'], 'title': '原文写回', 'sha256': result['result_sha256'],
                            'verification': 'verified' if result['result_sha256'] == document['sha256'] else 'changed'})
        steps.append({'id': 'comment:' + comment['message_id'], 'kind': 'comment', 'title': '批注处理',
                      'status': result['status'] if result else 'answered' if replies else 'received' if comment['received'] else 'pending',
                      'record_id': comment['message_id'], 'record_path': f"mail/messages/{comment['message_id']}.md",
                      'thread_id': comment['thread_id'], 'source_sha256': comment['source_sha256'],
                      'anchor_id': comment['anchor_id'], 'anchor_title': comment['anchor_title'],
                      'agent': comment['agent'], 'extractor': None, 'inputs': inputs, 'outputs': outputs,
                      'detail': comment['text'], 'received': comment['received']})
    return steps


def _bundle_path(parent, relative):
    if (not isinstance(relative, str) or not relative or ':' in relative or '\\' in relative
            or any(not part or part in {'.', '..'} for part in relative.split('/'))):
        raise ValueError('Choose a path inside the referenced Raw Bundle')
    return str(parent / relative)


def _bundle_inputs(root, parent, bundle, warnings):
    inputs = []
    envelope_path = str(parent / 'source-envelope.json')
    if studio._path(root, envelope_path).is_file():
        envelope = _process_json(root, envelope_path, warnings)
        if envelope.get('source_id') == bundle['capture_id'] and isinstance(envelope.get('source_uri'), str):
            inputs.append({'title': str(envelope.get('title') or '记录来源'),
                           'uri': envelope['source_uri'], 'verification': 'recorded'})
    sources = bundle.get('sources', [])
    for source in sources[:MAX_PROCESS_RECORDS] if isinstance(sources, list) else []:
        if not isinstance(source, dict) or not isinstance(source.get('sha256'), str):
            continue
        relative = _bundle_path(parent, source.get('path'))
        inputs.append(_process_artifact(root, relative, warnings, title='来源快照', expected=source['sha256']))
    return inputs


def _fragment_steps(root, document, anchor, parent, bundle, warnings):
    manifest_path = str(parent / 'evidence-manifest.json')
    if not studio._path(root, manifest_path).is_file():
        return []
    manifest = _process_json(root, manifest_path, warnings)
    if manifest.get('schema_version') != 'oks-evidence-manifest/v0.1' or manifest.get('source_id') != bundle['capture_id']:
        warnings.append(manifest_path + ': source identity does not match the referenced bundle')
        return []
    primary = manifest.get('primary_artifact', {})
    declared = {primary.get('artifact_id'): ('source/', primary)} if isinstance(primary, dict) else {}
    supplementary = manifest.get('supplementary_artifacts', [])
    for artifact in supplementary if isinstance(supplementary, list) else []:
        if isinstance(artifact, dict) and isinstance(artifact.get('artifact_id'), str):
            declared[artifact['artifact_id']] = ('derived/', artifact)
    steps, fragment_ids = [], manifest.get('fragment_refs', [])
    for fragment_id in fragment_ids[:MAX_PROCESS_RECORDS] if isinstance(fragment_ids, list) else []:
        if not isinstance(fragment_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', fragment_id):
            continue
        record_path = str(parent / 'derived/fragments' / (fragment_id + '.json'))
        fragment = _process_json(root, record_path, warnings)
        producer = fragment.get('producer', {})
        if (fragment.get('schema_version') != 'oks-evidence-fragment/v0.1'
                or fragment.get('fragment_id') != fragment_id or fragment.get('source_id') != bundle['capture_id']
                or not isinstance(producer, dict) or not isinstance(producer.get('provider'), str)
                or not isinstance(producer.get('tool'), str)
                or fragment.get('status') not in {'succeeded', 'partial', 'degraded', 'failed', 'skipped'}):
            warnings.append(record_path + ': fragment identity or producer is unavailable')
            continue
        outputs, valid = [], True
        artifacts = fragment.get('artifacts', [])
        for artifact in artifacts[:MAX_PROCESS_RECORDS] if isinstance(artifacts, list) else []:
            expected = declared.get(artifact.get('artifact_id')) if isinstance(artifact, dict) else None
            if (expected is None or artifact.get('path') != expected[1].get('path')
                    or not isinstance(artifact.get('sha256'), str)
                    or artifact['sha256'] != expected[1].get('sha256')):
                valid = False
                break
            outputs.append(_process_artifact(root, _bundle_path(parent, expected[0] + artifact['path']),
                                             warnings, expected=artifact['sha256']))
        if not valid:
            warnings.append(record_path + ': output artifact does not match the retained manifest')
            continue
        attempts = manifest.get('steps', [])
        matched = [item for item in attempts if isinstance(item, dict) and item.get('provider') == producer['provider']] if isinstance(attempts, list) else []
        capability = matched[0].get('capability') if len(matched) == 1 else None
        steps.append({**_process_base(document, anchor), 'id': 'fragment:' + record_path, 'kind': 'extraction',
                      'title': producer['tool'], 'status': fragment['status'], 'record_path': record_path,
                      'record_id': fragment_id,
                      'extractor': {**producer, 'capability': capability},
                      'inputs': _bundle_inputs(root, parent, bundle, warnings), 'outputs': outputs,
                      'detail': str(matched[0].get('reason') or '') if len(matched) == 1 else '',
                      'verification': 'retained_fragment'})
    return steps


def _run_datasets(root, parent, datasets, warnings):
    records = []
    for dataset in datasets[:MAX_PROCESS_RECORDS] if isinstance(datasets, list) else []:
        if not isinstance(dataset, dict) or not isinstance(dataset.get('uri'), str):
            continue
        uri = dataset['uri']
        record = {'uri': uri, 'title': str(dataset.get('dataset_id') or uri), 'verification': 'recorded'}
        relative = uri[len(str(parent)) + 1:] if uri.startswith(str(parent) + '/') else uri
        if ':' not in relative and not relative.startswith('/') and uri != str(parent):
            try:
                record = _process_artifact(root, _bundle_path(parent, relative), warnings,
                                           title=record['title'], expected=dataset.get('sha256'))
            except ValueError:
                record['verification'] = 'unavailable'
        records.append(record)
    return records


def _processing_steps(root, document, anchor, parent, bundle, warnings):
    record_path = str(parent / 'processing-runs.jsonl')
    checked = studio._path(root, record_path)
    if not checked.is_file():
        return []
    if checked.stat().st_size > studio.MAX_GRAPH_BYTES:
        warnings.append(record_path + ': record exceeds the reading limit')
        return []
    steps = []
    for line in checked.read_text(encoding='utf-8-sig').splitlines()[:MAX_PROCESS_RECORDS]:
        if not line.strip():
            continue
        try:
            run = json.loads(line)
            if not isinstance(run, dict) or run.get('schema_version') != 'oks-processing-run/v0.2':
                continue  # Agent-native raw-commit's summary is not another extractor invocation.
            job = run.get('job', {})
            if (run.get('capture_id') != bundle['capture_id'] or not isinstance(run.get('run_id'), str)
                    or not isinstance(job, dict) or not isinstance(job.get('name'), str)
                    or run.get('status') not in {'queued', 'running', 'complete', 'partial', 'failed', 'cancelled'}):
                warnings.append(record_path + ': processing run identity does not match the referenced bundle')
                continue
            steps.append({**_process_base(document, anchor), 'id': f"run:{record_path}#{run['run_id']}",
                          'kind': 'extraction', 'title': job['name'], 'status': run['status'],
                          'at': run.get('finished_at') or run.get('started_at'),
                          'simulated': job.get('namespace') == 'oks-experience-fixture',
                          'record_path': record_path, 'record_id': run['run_id'],
                          'extractor': {'provider': job['name'], 'tool': job['name'],
                                        'runtime': job.get('namespace'), 'version': job.get('version'),
                                        'capability': job.get('capability')},
                          'inputs': _run_datasets(root, parent, run.get('inputs', []), warnings),
                          'outputs': _run_datasets(root, parent, run.get('outputs', []), warnings),
                          'detail': '\n'.join(str(error.get('message') or '') for error in run.get('errors', []) if isinstance(error, dict)),
                          'verification': 'retained_processing_run'})
        except (ValueError, TypeError) as error:
            warnings.append(f'{record_path}: {error}')
    return steps


def processing_workflow(root, document):
    """Project retained extraction records for an already-read document."""
    root = Path(root).resolve()
    warnings, steps, seen = [], [], set()
    for reference, anchor in _process_sources(root, document, warnings):
        try:
            match = _process_bundle(root, reference, warnings)
            if match is None:
                continue
            parent, bundle = match
            if str(parent) in seen:
                continue
            seen.add(str(parent))
            fragments = _fragment_steps(root, document, anchor, parent, bundle, warnings)
            processing = _processing_steps(root, document, anchor, parent, bundle, warnings)
            steps.extend(fragments + processing)
            if not fragments and not processing:
                warnings.append(str(parent) + ': no matching retained extraction records')
        except (OSError, ValueError, TypeError, UnicodeError) as error:
            warnings.append(f'{reference}: {error}')
    if len(steps) > MAX_PROCESS_RECORDS:
        warnings.append(f'Only the first {MAX_PROCESS_RECORDS} process records are shown')
    return {'knowledge_base': str(root), 'path': document['path'], 'title': document['title'],
            'sha256': document['sha256'], 'steps': steps[:MAX_PROCESS_RECORDS],
            'warnings': list(dict.fromkeys(warnings))}


def discussion_workflow(root, relative):
    """Combine recorded extraction with this document's canonical Mail."""
    from . import discussion_comments
    document = discussion_comments.document(root, relative)
    result = processing_workflow(root, document)
    steps = result['steps'] + _comment_steps(root, document)
    if len(steps) > MAX_PROCESS_RECORDS:
        result['warnings'].append(f'Only the first {MAX_PROCESS_RECORDS} process records are shown')
    result['steps'] = steps[:MAX_PROCESS_RECORDS]
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    return result


def workflow(root, relative):
    document = studio.read_file(root, relative)
    path = document['path']
    meta, _, _ = studio._markdown(document['text'])
    index = {}
    for candidate in islice((root / 'wiki').rglob('*.md'), 3000):
        index.setdefault(candidate.stem, []).append(candidate.relative_to(root).as_posix())
    references, warnings = [], []
    total_bytes = len(document['text'].encode('utf-8'))
    # Two hops make Goal -> Skill -> Wiki visible without crawling the library.
    queue, seen = [(path, document, 0)], {path}
    while queue and len(seen) <= 40:
        source, item, depth = queue.pop(0)
        item_meta, body, _ = studio._markdown(item['text'])
        for target in studio._references(root, source, item_meta, body, index)[:40]:
            references.append({'from': source, 'to': target, 'kind': 'written_reference'})
            if target not in seen and depth < 1 and len(seen) < 40:
                seen.add(target)
                try:
                    child = studio.read_file(root, target)
                    total_bytes += len(child['text'].encode('utf-8'))
                    if total_bytes > studio.MAX_GRAPH_BYTES:
                        warnings.append('Reference content byte limit reached')
                        continue
                    queue.append((target, child, depth + 1))
                except (OSError, ValueError, UnicodeError, yaml.YAMLError):
                    warnings.append(target + ': unavailable')
    identities = {path}
    if isinstance(meta.get('id'), str):
        identities.add(meta['id'])
    runs = []
    is_skill = path.startswith(('skills/', 'skill/')) and path.endswith('/SKILL.md')
    directory = root / 'raw' / 'executions'
    manifests = list(islice(directory.glob('*/run.json'), 101))
    if len(manifests) > 100:
        warnings.append('Only the first 100 execution manifests were inspected')
    for manifest in manifests[:100]:
        try:
            # Use the same root-boundary validation as all other Studio reads.
            checked = studio._path(root, manifest.relative_to(root).as_posix())
            if checked.stat().st_size > 65536:
                raise ValueError('Manifest too large')
            run = json.loads(checked.read_text())
            if not isinstance(run, dict):
                raise ValueError('Invalid run manifest')
            goal_matches = isinstance(run.get('goal_id'), str) and run['goal_id'] in identities
            if not goal_matches and not is_skill:
                continue
            if run.get('run_id') != manifest.parent.name:
                raise ValueError('Manifest run identity mismatch')
            events_path = studio._path(root, (manifest.parent / 'events.jsonl').relative_to(root).as_posix())
            if events_path.stat().st_size > 512 * 1024:
                raise ValueError('Event stream too large')
            events = []
            lines = events_path.read_text().splitlines()
            if len(lines) > 500:
                warnings.append(manifest.parent.name + ': only the first 500 event lines were inspected')
            for line in lines[:500]:
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict) or event.get('run_id') != run.get('run_id'):
                    raise ValueError('Event run identity mismatch')
                payload = event.get('payload', {})
                if not isinstance(payload, dict):
                    raise ValueError('Invalid event payload')
                events.append({key: event.get(key) for key in ('event_id', 'timestamp', 'event_type', 'actor', 'sequence')}
                              | {'payload': {key: str(payload[key])[:1000] for key in ('title', 'summary', 'step_id', 'skill_path') if key in payload}})
            if not goal_matches:
                events = [event for event in events if event['payload'].get('skill_path') == path]
                if not events:
                    continue
            runs.append({'run_id': run.get('run_id'), 'status': run.get('status'), 'events': events, 'skill_only': not goal_matches,
                         'truncated': len(lines) > 500})
        except (OSError, ValueError, TypeError, UnicodeError):
            warnings.append(manifest.relative_to(root).as_posix() + ': unavailable')
    return {'path': path, 'outline': [row for row in document['outline'] if row['kind'] in ('heading', 'task')],
            'references': references, 'runs': runs, 'warnings': warnings}
