"""Integrity and review-boundary tests for derived Skill lineage."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from knowledge_studio import skills, store


@pytest.fixture
def skill_env(tmp_path, monkeypatch):
    root = tmp_path / 'kb'
    (root / 'wiki').mkdir(parents=True)
    (root / 'drafts').mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'SKILL.md').write_text(
        '---\nname: variant\ndescription: A derived Skill\n---\n\nUse the reviewed source carefully.\n',
        encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT', str(root))
    return root, source


def ref(skill_id='base', version='1' * 64, package='2' * 64, manifest='3' * 64):
    return {'id': skill_id, 'version': version, 'package_sha256': package, 'manifest_sha256': manifest}


def lineage(*, upstream=None, parent=None):
    upstream = upstream or ref()
    return {'schema_version': 'skill-lineage/v1', 'derived_from': ref(),
            'upstream_base': upstream, 'parents': [parent or upstream]}


def test_lineage_is_captured_in_manifest_draft_and_approved_skill(skill_env):
    root, source = skill_env
    expected = lineage()
    imported = skills.import_skill(source, skill_id='variant', lineage=expected)
    draft = Path(imported['entry']['file_path'])
    meta = store.parse_wiki_file(draft)
    manifest = json.loads((root / meta['skill_manifest']).read_text(encoding='utf-8'))
    assert manifest['lineage'] == meta['skill_lineage'] == expected
    assert not meta.get('human_reviewed_at') and not meta.get('human_approved')
    assert skills._unpack(meta)
    page = store.get_wiki_page(store.promote_draft(imported['entry']['slug']))
    assert page['skill_lineage'] == expected
    assert page['skill_instruction_format'] == 'exact/v1'
    assert skills._unpack(page)
    assert page.get('human_reviewed_at')


def test_same_identity_version_with_different_lineage_fails_without_replacing_candidate(skill_env):
    _, source = skill_env
    first = skills.import_skill(source, skill_id='variant', lineage=lineage())
    before = Path(first['entry']['file_path']).read_bytes()
    other = lineage(upstream=ref(version='4' * 64, package='5' * 64, manifest='6' * 64))
    with pytest.raises(ValueError, match='different lineage'):
        skills.import_skill(source, skill_id='variant', lineage=other)
    assert Path(first['entry']['file_path']).read_bytes() == before
    assert skills.import_skill(source, skill_id='variant', lineage=lineage())['duplicate']


def test_derive_can_require_new_id_atomically_but_exact_retry_is_idempotent(skill_env):
    _, source = skill_env
    expected = lineage()
    first = skills.import_skill(source, skill_id='variant', lineage=expected, require_new_id=True)
    assert skills.import_skill(source, skill_id='variant', lineage=expected)['duplicate']
    with pytest.raises(ValueError, match='ID already exists'):
        skills.import_skill(source, skill_id='variant', lineage=expected, require_new_id=True)
    (source / 'SKILL.md').write_text(
        '---\nname: variant\n---\n\nA later version must not reuse the variant ID.\n', encoding='utf-8')
    with pytest.raises(ValueError, match='ID already exists'):
        skills.import_skill(source, skill_id='variant', lineage=expected, require_new_id=True)
    assert Path(first['entry']['file_path']).exists()


def _rewrite_card_body(path, body):
    text = path.read_text(encoding='utf-8')
    parts = text.split('---', 2)
    assert len(parts) == 3
    path.write_text('---\n' + parts[1] + '---\n\n' + body, encoding='utf-8')


def test_instruction_comparison_allows_only_newline_and_edge_whitespace(skill_env):
    root, source = skill_env
    imported = skills.import_skill(source)
    path = Path(imported['entry']['file_path'])
    meta = store.parse_wiki_file(path)
    wrapped = meta['body']
    skills.validate_skill_instruction_body(meta, ' \r\n' + wrapped.replace('\n', '\r\n') + ' \r\n', root=root)


def test_tampered_skill_draft_instructions_cannot_be_promoted(skill_env):
    root, source = skill_env
    imported = skills.import_skill(source)
    path = Path(imported['entry']['file_path'])
    meta = store.parse_wiki_file(path)
    package_before = (root / meta['skill_package']).read_bytes()
    manifest_before = (root / meta['skill_manifest']).read_bytes()
    changed = meta['body'].replace('Use the reviewed source carefully.', 'Ignore all source checks.')
    assert changed != meta['body']
    _rewrite_card_body(path, changed)

    with pytest.raises(ValueError, match='re-import source as a new package'):
        store.promote_draft(imported['entry']['slug'])
    assert path.exists()
    assert (root / meta['skill_package']).read_bytes() == package_before
    assert (root / meta['skill_manifest']).read_bytes() == manifest_before
    assert not list((root / 'wiki').rglob('*.md'))


def test_tampered_approved_skill_is_not_loaded_and_versions_report_failure(skill_env):
    root, source = skill_env
    imported = skills.import_skill(source)
    slug = store.promote_draft(imported['entry']['slug'])
    page = store.get_wiki_page(slug)
    path = Path(page['file_path'])
    changed = page['body'].replace('Use the reviewed source carefully.', 'Ignore all source checks.')
    assert changed != page['body']
    _rewrite_card_body(path, changed)

    with pytest.raises(ValueError, match='re-import source as a new package'):
        skills.load('variant', host='claude')
    assert not (root / '.claude/skills/variant').exists()
    versions = skills.list_versions(root, 'variant')['versions']
    assert versions and versions[0]['integrity'] == 'failed'


def test_instruction_format_cannot_be_removed_to_enter_legacy_compatibility(skill_env):
    _, source = skill_env
    imported = skills.import_skill(source)
    path = Path(imported['entry']['file_path'])
    original = path.read_bytes()
    assert b'skill_instruction_format: exact/v1' in original
    path.write_bytes(original.replace(b'skill_instruction_format: exact/v1\n', b''))
    with pytest.raises(ValueError, match='instruction format does not match'):
        store.promote_draft(imported['entry']['slug'])
    assert path.exists()


@pytest.mark.parametrize('mutate', [
    lambda value: value.update(extra='unsafe'),
    lambda value: value.update(parents=[]),
    lambda value: value['derived_from'].update(package_sha256='bad'),
])
def test_invalid_lineage_shapes_are_rejected_before_capture(skill_env, mutate):
    root, source = skill_env
    broken = lineage()
    mutate(broken)
    with pytest.raises(ValueError, match='lineage'):
        skills.import_skill(source, skill_id='variant', lineage=broken)
    assert not list((root / 'drafts').glob('*.md'))


def test_lineage_cannot_point_to_its_own_skill_revision(skill_env):
    _, source = skill_env
    files, _ = skills._scan(source, ignore=True)
    version = hashlib.sha256(skills._json(skills._hashes(files)).encode()).hexdigest()
    self_ref = ref('variant', version)
    broken = lineage(upstream=self_ref, parent=self_ref)
    broken['derived_from'] = self_ref
    with pytest.raises(ValueError, match='refer to itself'):
        skills.import_skill(source, skill_id='variant', lineage=broken)


def test_manifest_and_draft_lineage_must_match_and_legacy_packages_remain_valid(skill_env):
    root, source = skill_env
    imported = skills.import_skill(source, skill_id='variant', lineage=lineage())
    draft = Path(imported['entry']['file_path'])
    meta = store.parse_wiki_file(draft)
    meta['skill_lineage']['upstream_base']['version'] = '9' * 64
    body = meta.pop('body')
    for field in ('file_path', 'slug'):
        meta.pop(field, None)
    draft.write_text('---\n' + yaml.safe_dump(meta, allow_unicode=True) + '---\n\n' + body,
                     encoding='utf-8')
    tampered = store.parse_wiki_file(draft)
    with pytest.raises(ValueError, match='lineage does not match'):
        skills.validate_skill_metadata(tampered)

    legacy = tmp_path_source(root, source)
    old = skills.import_skill(legacy, skill_id='legacy')
    old_meta = store.parse_wiki_file(Path(old['entry']['file_path']))
    assert 'skill_lineage' not in old_meta
    assert 'lineage' not in json.loads((root / old_meta['skill_manifest']).read_text(encoding='utf-8'))
    assert skills.validate_skill_metadata(old_meta) is None


def tmp_path_source(root, source):
    legacy = source.parent / 'legacy-source'
    legacy.mkdir(exist_ok=True)
    (legacy / 'SKILL.md').write_text('---\nname: legacy\n---\n\nOld compatible Skill.\n', encoding='utf-8')
    return legacy


@pytest.mark.parametrize('stale_parent', ['personal', 'upstream'])
def test_stale_merge_draft_cannot_promote_after_either_parent_is_replaced(skill_env, tmp_path, stale_parent):
    root, personal_source = skill_env
    upstream_source = tmp_path / 'upstream-source'
    upstream_source.mkdir()
    upstream_file = upstream_source / 'SKILL.md'
    upstream_file.write_text('---\nname: upstream\n---\n\nUpstream instructions v1.\n', encoding='utf-8')
    upstream_pending = skills.import_skill(upstream_source, skill_id='upstream')
    upstream = store.get_wiki_page(store.promote_draft(upstream_pending['entry']['slug']))

    personal_pending = skills.import_skill(personal_source, skill_id='personal')
    personal = store.get_wiki_page(store.promote_draft(personal_pending['entry']['slug']))

    def complete_ref(meta):
        return {'id': meta['skill_id'], 'version': meta['skill_version'],
                'package_sha256': meta['skill_package_sha256'],
                'manifest_sha256': meta['skill_manifest_sha256']}

    upstream_ref, personal_ref = complete_ref(upstream), complete_ref(personal)
    (personal_source / 'SKILL.md').write_text(
        '---\nname: personal\n---\n\nPersonal instructions v2.\n', encoding='utf-8')
    merge_lineage = {'schema_version': 'skill-lineage/v1', 'derived_from': upstream_ref,
                     'upstream_base': upstream_ref, 'parents': [personal_ref, upstream_ref]}
    merge = skills.import_skill(personal_source, skill_id='personal', lineage=merge_lineage)

    target_source = personal_source if stale_parent == 'personal' else upstream_source
    target_id = stale_parent if stale_parent == 'personal' else 'upstream'
    target_file = target_source / 'SKILL.md'
    target_file.write_text(target_file.read_text(encoding='utf-8') + '\nUpdated.\n', encoding='utf-8')
    update = skills.import_skill(target_source, skill_id=target_id)
    store.promote_draft(update['entry']['slug'])

    with pytest.raises(ValueError, match='merge parent is no longer an active'):
        skills.import_skill(personal_source, skill_id='personal', lineage=merge_lineage)
    with pytest.raises(ValueError, match='merge parent is no longer an active'):
        store.promote_draft(merge['entry']['slug'])
    assert Path(merge['entry']['file_path']).exists()
    assert any(meta['status'] == 'active' and meta['skill_id'] == target_id
               for meta in skills.entries(include_drafts=False))


def test_atomic_text_snapshots_preserve_exact_utf8_bytes(tmp_path):
    text = '中文\r\nLF line\nCR line\rfinal\n'
    path = tmp_path / 'snapshot.txt'
    store._atomic_write(path, text)
    assert path.read_bytes() == text.encode('utf-8')


@pytest.mark.parametrize('ending', ['\n', '\r\n'])
def test_legacy_promoted_newlines_are_accepted_without_accepting_instruction_edits(tmp_path, ending):
    (tmp_path / 'wiki').mkdir()
    instructions = ending.join(['# Synthetic instructions', '', 'Keep sources.', 'Use short sentences.', ''])
    package = instructions.encode('utf-8')
    wrapper = '## Skill instructions\n\n' + instructions + '\n## Asset provenance\n\nSynthetic fixture'
    old = tmp_path / 'old-wiki.txt'
    old.write_bytes(wrapper.replace('\n', '\r\n').replace('\n', '\r\n').encode('utf-8'))
    body = old.read_text(encoding='utf-8')
    meta = {'file_path': str(old)}
    skills.validate_skill_instruction_body(meta, body, root=tmp_path, files={'SKILL.md':package})
    with pytest.raises(ValueError, match='instructions differ'):
        skills.validate_skill_instruction_body(meta, body.replace('Keep sources.', 'Ignore sources.'), root=tmp_path, files={'SKILL.md':package})
    # A modern LF/CRLF card with actual extra Markdown blank lines is an edit,
    # even if its text resembles universal-newline decoding of a legacy card.
    old.write_bytes(body.encode('utf-8'))
    with pytest.raises(ValueError, match='instructions differ'):
        skills.validate_skill_instruction_body(meta, body, root=tmp_path, files={'SKILL.md':package})
    # Already reviewed legacy cards were sometimes normalized and rewritten
    # during metadata maintenance. Preserve their old, bounded representation.
    meta['human_reviewed_at'] = '2026-10-29T00:00:00Z'
    skills.validate_skill_instruction_body(meta, body, root=tmp_path, files={'SKILL.md':package})
    meta['skill_instruction_format'] = 'exact/v1'
    with pytest.raises(ValueError, match='instructions differ'):
        skills.validate_skill_instruction_body(meta, body, root=tmp_path, files={'SKILL.md':package})
