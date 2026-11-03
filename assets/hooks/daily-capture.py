#!/usr/bin/env python3
"""Capture public sources from one explicitly connected Claude workspace."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kb', required=True)
    parser.add_argument('--package', required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.package)
    from knowledge_studio import daily_sources, store, tasks
    root = Path(args.kb).resolve()
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('hook_payload_too_large')
        payload = json.loads(raw)
        result = daily_sources.observe_claude(root, payload)
        state = {k: result[k] for k in ('status', 'error', 'count') if k in result}
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        store._atomic_write(tasks._inside(root, '.oks/daily-capture/hook-error.json'), json.dumps(state))
    except Exception as exc:
        error = {'status': 'failed', 'error': type(exc).__name__, 'updated_at': datetime.now(timezone.utc).isoformat()}
        store._atomic_write(tasks._inside(root, '.oks/daily-capture/hook-error.json'), json.dumps(error))
        print('OKS daily capture failed; original source retained (' + type(exc).__name__ + ')', file=sys.stderr)
    return 0  # Recording failure must not block the user's work.


if __name__ == '__main__':
    raise SystemExit(main())
