#!/usr/bin/env python3
"""Native lifecycle adapter; installed only with explicit --collaboration."""
from pathlib import Path
import sys

if __name__ == '__main__':
    owner = Path(__file__).resolve().parent.parent.name.lower()
    if owner not in {'.claude', '.codex'}:
        raise SystemExit('Install this hook with oks hook install --collaboration')
    try:
        from knowledge_studio.host_collaboration import main
        code = main(owner[1:])
    except Exception as exc:
        print(f'OKS collaboration capture failed: {type(exc).__name__}', file=sys.stderr)
        code = 0
    raise SystemExit(code)
