"""Read-only declared references and recorded execution; never infer calls."""
from itertools import islice
import json

import yaml

from . import studio


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
        for target in studio._references(root, source, item['text'], index)[:40]:
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
