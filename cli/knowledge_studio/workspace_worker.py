"""Fixed-operation child for APIs that resolve their KB through process configuration."""
import json
from pathlib import Path
import sys

from . import store, workspace


def dispatch(operation, request):
    root = store.repo_root()
    if operation == 'skill-catalog':
        from . import skills
        grouped = {}
        for card in skills.entries(root=root):
            identity = card.get('skill_id')
            if not identity:
                continue
            lineage = card.get('skill_lineage')
            original = lineage.get('derived_from') if isinstance(lineage, dict) else None
            title = original['id'] + ' · 我的版本' if isinstance(original, dict) and isinstance(original.get('id'), str) else card.get('title') or identity
            item = grouped.setdefault(identity, {'id': identity, 'title': title, 'reviewed': False})
            if card.get('status') == 'active' and card.get('human_reviewed_at'):
                item['version'] = card.get('skill_version')
                item['reviewed'] = True
        return {'knowledge_base': str(root), 'items': sorted(grouped.values(), key=lambda item:item['id'])}
    if operation in ('skill-detail', 'skill-derive', 'skill-merge-preview', 'skill-merge-prepare'):
        from . import skill_derivation
        if operation == 'skill-detail':
            return skill_derivation.detail(root, request.get('ref'))
        if operation == 'skill-derive':
            return skill_derivation.derive(root, request)
        if operation == 'skill-merge-preview':
            return skill_derivation.preview_merge(root, request)
        return skill_derivation.prepare_merge(root, request)
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
    if operation == 'reject':
        if request.get('confirm_reject') is not True:
            raise ValueError('Choose not to retain the exact Draft before rejection')
        inspected = workspace.draft(root, request.get('path'))
        if inspected.get('review_status') != 'draft':
            raise ValueError('This Draft revision already has a decision')
        expected = request.get('expected_sha256')
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('Read the exact Draft revision before rejection')
        receipt = store.reject_draft(Path(inspected['path']).stem, expected_sha256=expected)
        return {'status': 'rejected', 'path': inspected['path'],
                'receipt': receipt.relative_to(root).as_posix()}
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
