"""One background benchmark per process; no server-global KB environment switch."""
from pathlib import Path
from datetime import datetime, UTC
import os
import sys
import shutil
from . import studio_evaluation as ev
from . import evaluation, store


def main(root, run_id):
    job = ev.read(root, 'jobs/' + ev.identifier(run_id) + '.json')
    item = ev.dataset(root, job['dataset'])
    def update(**changes):
        job.update(changes)
        ev.write(root, 'jobs/' + run_id + '.json', job)
    try:
        update(status='running', pid=os.getpid())
        corpus = ev.corpus_root(root, item)
        if corpus != root:
            # Each benchmark uses the active recall parameters, without importing
            # synthetic conversations into the person's reviewed Wiki.
            source = root / 'settings/recall.yaml'
            target = ev.path(root, item['corpus'] + '/settings/recall.yaml')
            if source.is_file():
                store._atomic_write(target, source.read_text())
            elif target.exists():
                target.unlink()
        os.environ['OKS_ROOT'] = str(corpus)
        def progress(done, total):
            if done==total or done%10==0:
                update(completed=done,total=total)
        result = evaluation.run_evaluation(ev.path(root,item['path']),ev.path(root,'runs/'+run_id+'.json'),
                    search_backend=job['method'],split=job.get('split'),progress=progress)
        result['studio'] = {'dataset':item['id'],'corpus':item.get('corpus','current'),
                            'method':job['method'],'source':item.get('source')}
        ev.write(root,'runs/'+run_id+'.json',result)
        update(status='completed',completed=job['total'],finished_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        update(status='failed',error=str(exc),finished_at=datetime.now(UTC).isoformat())
        raise


if __name__=='__main__':
    main(Path(sys.argv[1]).resolve(), sys.argv[2])
