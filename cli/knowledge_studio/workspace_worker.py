"""Fixed-operation child for APIs that resolve their KB through process configuration."""
import json
from pathlib import Path
import sys

from . import store, workspace


def dispatch(operation, request):
    root = store.repo_root()
    if operation == 'query':
        from .recall import recall
        query = request.get('query')
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError('Enter a question of 1-500 characters')
        return recall(query.strip(), limit=5, knowledge_only=True, use_task=False, goal='none')
    if operation == 'promote':
        if request.get('confirm_review') is not True:
            raise ValueError('Read and confirm the exact Draft before promotion')
        inspected = workspace.draft(root, request.get('path'))
        expected = request.get('expected_sha256')
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('Read the exact Draft revision before promotion')
        slug = store.promote_draft(Path(inspected['path']).stem, expected_sha256=expected)
        page = store.get_wiki_page(slug)
        return {'status': 'promoted', 'slug': slug, 'path': Path(page['file_path']).relative_to(root).as_posix()}
    if operation in {'versions', 'diff', 'bundled-diff', 'import-bundled'}:
        from . import skills
        if operation == 'versions':
            return skills.list_versions(root, request.get('id'))
        if operation == 'bundled-diff':
            return skills.bundled_diff(root, request.get('id'), request.get('version'))
        if operation == 'import-bundled':
            return skills.prepare_bundled_update(root, request)
        return skills.compare_versions(root, request.get('id'), request.get('from'), request.get('to'))
    raise ValueError('Unsupported local operation')


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError('Request exceeds size limit')
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError('Request must be an object')
        print(json.dumps(dispatch(sys.argv[1], request), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(2)
