"""File-backed evaluation catalog, bounded imports and background CLI jobs.

Uploaded material is data, never executable evaluator code. The recall adapter
reuses evaluation.run_evaluation; each benchmark corpus stays under records/.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, UTC
from itertools import islice
from uuid import uuid4
import yaml
from . import evaluation, store, tasks

BASE = 'records/evaluation'
METHODS = {'fts5', 'native', 'fusion'}
MAX_UPLOAD = 8 * 1024 * 1024


def path(root, relative):
    return tasks._inside(root.resolve(), BASE + '/' + relative)


def read(root, relative):
    target = path(root, relative)
    with target.open('rb') as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('Evaluation record exceeds reader limit')
    return json.loads(data)


def write(root, relative, value):
    store._atomic_write(path(root, relative), json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value):
        raise ValueError('Choose an evaluation identifier')
    return value


def _registry(root):
    target = path(root, 'datasets/catalog.json')
    return read(root, 'datasets/catalog.json') if target.is_file() else {'datasets': []}


def dataset(root, dataset_id):
    item = next((d for d in _registry(root)['datasets'] if d['id'] == identifier(dataset_id)), None)
    if item is None:
        raise ValueError('Unknown dataset')
    return item


def corpus_root(root, item):
    return root if item.get('corpus', 'current') == 'current' else path(root, item['corpus'])


def coverage(root, item, data=None):
    data = data or evaluation.load_dataset(path(root, item['path']))
    present = {p.stem for p in islice((corpus_root(root, item) / 'wiki').rglob('*.md'), 10001)
               if p.is_file() and not p.is_symlink()}
    gold = {slug for case in data['cases'] for slug in case['relevant']}
    missing = sorted(gold - present)
    return {'gold_count': len(gold), 'missing_count': len(missing), 'missing': missing}


def catalog(root):
    datasets = []
    for item in _registry(root)['datasets'][:100]:
        try:
            data = evaluation.load_dataset(path(root, item['path']))
            splits = sorted({case['split'] for case in data['cases'] if 'split' in case})
            datasets.append({**item, 'case_count': len(data['cases']), 'schema': data['schema_version'], 'dataset_id':data['dataset_id'],
                             'splits': splits, 'coverage': coverage(root, item, data)})
        except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
            datasets.append({**item, 'error': str(exc)})
    runs, jobs, warnings = [], [], []
    for target in islice(path(root, 'runs').glob('*.json'), 300):
        try:
            result = run(root, target.stem)
            runs.append({key: value for key, value in result.items() if key != 'cases'})
        except (OSError, ValueError, KeyError) as exc:
            warnings.append(target.name + ': ' + str(exc))
    for target in islice(path(root, 'jobs').glob('*.json'), 100):
        try:
            jobs.append(read(root, 'jobs/' + target.name))
        except (OSError, ValueError):
            warnings.append(target.name + ': unreadable')
    references = read(root, 'references.json') if path(root, 'references.json').is_file() else []
    return {'datasets': datasets, 'runs': sorted(runs, key=lambda r:r.get('generated_at',''), reverse=True),
            'jobs': sorted(jobs, key=lambda r:r.get('created_at',''), reverse=True),
            'references': references, 'warnings': warnings, 'methods': sorted(METHODS)}


def run(root, run_id):
    value = read(root, 'runs/' + identifier(run_id) + '.json')
    evaluation._validate_run(value)
    warnings = [] if value["manifest"].get("comparison_context") else ["历史记录缺少配置与代码对照信息"]
    # Historical results stay intact; limitations travel alongside the originals.
    return {**value, 'id': run_id, 'validation_warnings': warnings}


def import_dataset(root, payload):
    text, filename = payload.get('text'), payload.get('filename')
    if not isinstance(text, str) or not 1 <= len(text.encode()) <= MAX_UPLOAD:
        raise ValueError('Upload a YAML/JSON dataset up to 8 MiB')
    if not isinstance(filename, str) or Path(filename).suffix.lower() not in {'.yaml','.yml','.json'}:
        raise ValueError('Upload YAML or JSON')
    if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(text)):
        raise ValueError('YAML aliases are not supported in uploaded datasets')
    value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError('Dataset must be an object')
    data = value.get('dataset', value)
    corpus = value.get('corpus') if 'dataset' in value else None
    if not isinstance(data, dict) or not isinstance(data.get('cases'), list) or not 1 <= len(data['cases']) <= 10000:
        raise ValueError('Provide 1–10000 cases')
    if any(not isinstance(c,dict) or not isinstance(c.get('query'),str) or not 1 <= len(c['query']) <= 2000 for c in data['cases']):
        raise ValueError('Each case needs a query of 1–2000 characters')
    if corpus is not None and (not isinstance(corpus, dict) or not 1 <= len(corpus) <= 2000):
        raise ValueError('Corpus must map 1–2000 slugs to Markdown text')
    for slug, body in (corpus or {}).items():
        if (not isinstance(slug, str) or slug.startswith('.') or len(slug) > 200
                or any(c in slug for c in '/\\:\x00') or not isinstance(body, str)
                or len(body.encode()) > 1024 * 1024):
            raise ValueError('Invalid corpus slug or Markdown')
    digest = hashlib.sha256(text.encode()).hexdigest()
    item_id = 'dataset-' + digest[:16]
    relative = 'datasets/' + item_id + '.yaml'
    target = path(root, relative)
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    store._atomic_write(target, content)
    try:
        evaluation.load_dataset(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    with store._file_lock(path(root, '.catalog.lock')):
        registry = _registry(root)
        if any(d['id']==item_id for d in registry['datasets']):
            return {'id': item_id, 'status': 'existing'}
        corpus_path = 'current'
        if corpus is not None:
            corpus_path = 'corpora/' + item_id
            for slug, body in corpus.items():
                store._atomic_write(path(root, corpus_path + '/wiki/' + slug + '.md'), body)
        item = {'id': item_id, 'title': str(data.get('dataset_id', filename)), 'path': relative,
                'corpus': corpus_path, 'source': filename, 'sha256': digest,
                'imported_at': datetime.now(UTC).isoformat(), 'adapter': 'recall'}
        registry['datasets'].append(item)
        write(root, 'datasets/catalog.json', registry)
    return {'id': item_id, 'status': 'imported'}


def start(root, payload):
    item = dataset(root, payload.get('dataset'))
    method, split = payload.get('method'), payload.get('split')
    if method not in METHODS:
        raise ValueError('Choose a supported recall method')
    missing = coverage(root, item)
    if missing['missing_count']:
        raise ValueError(f"Missing {missing['missing_count']} gold documents; restore the corpus before running")
    data = evaluation.load_dataset(path(root, item['path']))
    splits = {case['split'] for case in data['cases'] if 'split' in case}
    if splits and split not in splits:
        raise ValueError('Choose an explicit split')
    if not splits and split is not None:
        raise ValueError('This dataset has no split')
    with store._file_lock(path(root, '.run.lock')):
        for old in path(root, 'jobs').glob('*.json'):
            if read(root, 'jobs/' + old.name).get('status') in {'queued','running'}:
                raise ValueError('An evaluation is already running')
        run_id = 'run-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
        job = {'id': run_id, 'dataset': item['id'], 'method': method, 'split': split,
               'status': 'queued', 'completed': 0,
               'total': sum(1 for c in data['cases'] if not split or c.get('split')==split),
               'created_at': datetime.now(UTC).isoformat()}
        write(root, 'jobs/' + run_id + '.json', job)
        env = {key:value for key,value in os.environ.items() if key.upper() not in {'PYTHONHOME','PYTHONPATH'}}
        parent = Path(__file__).resolve().parent.parent
        env.update(PYTHONPATH=str(parent), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        try:
            with path(root, 'jobs/' + run_id + '.log').open('wb') as log:
                subprocess.Popen([sys.executable, '-P', '-m', 'knowledge_studio.studio_eval_worker',
                                  str(root.resolve()), run_id], cwd=parent, env=env,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name!='nt')
        except OSError as exc:
            write(root, 'jobs/' + run_id + '.json', {**job,'status':'failed','error':str(exc)})
            raise
    return job


def compare(root, payload):
    left, right = identifier(payload.get('baseline')), identifier(payload.get('candidate'))
    vary = ['code','backend'] + (['settings','parameters'] if payload.get('configuration_experiment') is True else [])
    return evaluation.compare_runs(path(root, 'runs/' + left + '.json'), path(root, 'runs/' + right + '.json'), vary=vary)
