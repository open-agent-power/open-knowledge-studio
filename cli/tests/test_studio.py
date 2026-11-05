"""File projections never constitute task execution or human knowledge approval."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from knowledge_studio import studio
from knowledge_studio.mail_web import create_server


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / '知识库'
    docs = {
        'goal/interface/index.md': '# 简化界面\n\n[[goal/interface/page.md]]\n[[wiki/rule]]\n',
        'goal/interface/page.md': '# 页面\n\n## 实现\n- [ ] 编辑\n  - [ ] 验证\n\n## 备注\n不代表验收。\n',
        'profiles/goals/legacy.md': '---\ntype: goal\ntitle: 旧目标\n---\n# Legacy\n',
        'discuss/2026/11/04/interface.md': '# 讨论\n\n[[goal/interface/index.md]]\n\n## 人的判断\n只有三个菜单。\n\n## AI 理解\n另加一个工作台。\n\n## 待确认\n是否一致？\n\n[[raw/source.md]]\n',
        'discuss/unrelated.md': '# 无关讨论\n\n不应出现在所选图谱。\n',
        'wiki/rule.md': '---\ntitle: 三阶段\n---\n# Loop\n',
        'raw/source.md': '# 来源\n\n原始判断。\n',
        'skill/my-method/SKILL.md': '---\nname: my-method\n---\n# 方法\n',
        '.agents/skills/host-only/SKILL.md': '# 不属于知识库技能目录\n',
    }
    for relative, text in docs.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    (root / 'mail').mkdir()
    return root


def test_scope_projection_uses_written_links_and_remains_read_only(kb):
    assert {s['path'] for s in studio.scopes(kb)['scopes']} == {'goal/interface', 'profiles/goals/legacy.md'}
    result = studio.view(kb, 'goal/interface')
    assert set(result['files']) == {'goal/interface/index.md', 'goal/interface/page.md', 'wiki/rule.md',
                                    'discuss/2026/11/04/interface.md', 'raw/source.md'}
    assert {n['type'] for n in result['nodes']} >= {'goal', 'human_judgment', 'agent_understanding', 'open_question', 'raw', 'wiki'}
    assert all(n.get('alignment', 'unspecified') == 'unspecified' for n in result['nodes'])
    assert all(e['evidence'] in result['files'] for e in result['edges'])
    assert studio.view(kb, 'goal/interface')['version'] == result['version']
    assert not (kb / '.oks').exists()
    assert studio.local_skills(kb)['skills'][0]['path'] == 'skill/my-method/SKILL.md'
    assert len(studio.local_skills(kb)['skills']) == 1


def test_outline_preserves_source_lines_nesting_and_non_tasks():
    text = '---\r\ntitle: 示例\r\n---\r\n\r\n# 目标\r\n描述\r\n## 子目标\r\n### 实现\r\n- [ ] A\r\n  - [x] B\r\n## 备注\r\n- [ ] 引用中的清单不是执行项\r\n```md\r\n# 不是目标\r\n```\r\n'
    rows = studio.outline(text)
    assert next(r for r in rows if r['text'] == '目标')['line'] == 4
    a, b = [r for r in rows if r['kind'] == 'task']
    assert b['parent'] == a['line'] and b['checked']
    assert next(r for r in rows if r['text'] == '实现')['kind'] == 'heading'
    assert all(r['text'] != '不是目标' for r in rows)
    assert next(r for r in rows if '执行项' in r['text'])['kind'] == 'note'


def test_projection_reuses_documents_only_within_the_current_request(kb, monkeypatch):
    reads = []
    original = studio.workspace._text_file

    def record_read(root, relative, suffixes):
        reads.append(relative)
        return original(root, relative, suffixes)

    monkeypatch.setattr(studio.workspace, '_text_file', record_read)
    relative = 'discuss/2026/11/04/interface.md'
    first = studio.view(kb, 'goal/interface')
    assert reads.count(relative) == 1
    assert all('outline' in item for item in first['files'].values())

    document = kb / relative
    document.write_text(document.read_text(encoding='utf-8') + '\n外部修改\n', encoding='utf-8')
    reads.clear()
    second = studio.view(kb, 'goal/interface')
    assert reads.count(relative) == 1
    assert second['version'] != first['version']
    assert second['files'][relative]['text'].splitlines()[-1] == '外部修改'


def test_goal_edit_is_revision_checked_and_does_not_modify_task_agreements(kb):
    before = studio.read_file(kb, 'goal/interface/page.md')
    request = {'path': before['path'], 'expected_sha256': before['sha256'], 'text': before['text'] + '\n新说明\n'}
    updated = studio.save_file(kb, request)
    assert updated['sha256'] != before['sha256']
    assert studio.view(kb, 'goal/interface')['files'][before['path']]['sha256'] == updated['sha256']
    with pytest.raises(ValueError, match='changed'):
        studio.save_file(kb, request)
    assert not (kb / '.oks/tasks').exists()
    assert not (kb / 'wiki/新说明.md').exists()


def test_two_goal_writers_cannot_overwrite_one_another(kb):
    before = studio.read_file(kb, 'goal/interface/page.md')
    def write(suffix):
        try:
            studio.save_file(kb, {'path': before['path'], 'text': before['text'] + suffix,
                                  'expected_sha256': before['sha256']})
            return 'saved'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ['A', 'B'])) == ['conflict', 'saved']


@pytest.mark.parametrize('path', ['../outside.md', 'wiki/rule.md', 'raw/source.md', '.oks/a.md', 'goal/../wiki/rule.md', 'goal//a.md', 'goal/a.txt', '/goal/a.md'])
def test_goal_editor_refuses_other_buckets_and_noncanonical_paths(kb, path):
    with pytest.raises((ValueError, OSError)):
        studio.save_file(kb, {'path': path, 'create': True, 'text': '# no'})
    assert (kb / 'wiki/rule.md').read_text().startswith('---')


def test_symlink_escape_and_malformed_frontmatter_preserve_files(kb, tmp_path):
    outside = tmp_path / 'outside.md'
    outside.write_text('# private')
    (kb / 'goal/link.md').symlink_to(outside)
    with pytest.raises(ValueError):
        studio.read_file(kb, 'goal/link.md')
    assert all(s['path'] != 'goal/link.md' for s in studio.scopes(kb)['scopes'])
    before = (kb / 'goal/interface/page.md').read_bytes()
    with pytest.raises(Exception):
        studio.save_file(kb, {'path': 'goal/interface/page.md', 'expected_sha256': hashlib.sha256(before).hexdigest(), 'text': '---\n[bad\n---\n# bad'})
    assert (kb / 'goal/interface/page.md').read_bytes() == before


def test_relative_references_and_unreadable_scope_have_explicit_boundaries(kb):
    path = kb / 'goal/interface/page.md'
    path.write_text('# 页面\n\n[知识](../../wiki/rule.md)\n')
    result = studio.view(kb, 'goal/interface/page.md')
    assert 'wiki/rule.md' in result['files']
    (kb / 'goal/bad.md').write_text('---\n[invalid\n---\n# bad')
    with pytest.raises(ValueError, match='No readable'):
        studio.view(kb, 'goal/bad.md')


def test_a_goal_reference_is_not_automatically_a_parent_child_relation(kb):
    result = studio.view(kb, 'goal/interface')
    edge = next(e for e in result['edges'] if e['from'] == 'goal/interface/index.md' and e['to'] == 'goal/interface/page.md')
    assert edge['type'] == 'cites'
    index = kb / 'goal/interface/index.md'
    index.write_text('# 根目标\n\n## 子目标\n[[goal/interface/page.md]]\n')
    result = studio.view(kb, 'goal/interface')
    edge = next(e for e in result['edges'] if e['from'] == 'goal/interface/index.md' and e['to'] == 'goal/interface/page.md')
    assert edge['type'] == 'contains'


def test_code_examples_do_not_create_relations_or_agent_judgments(kb):
    path = kb / 'goal/code.md'
    path.write_text('```md\n# Fake\n[[wiki/rule]]\n```\n# Actual\n`[[wiki/rule]]`\n<!-- [[wiki/rule]] -->\n')
    result = studio.view(kb, 'goal/code.md')
    assert result['nodes'][0]['title'] == 'Actual'
    assert set(result['files']) == {'goal/code.md'}
    (kb / 'discuss/code.md').write_text('[[goal/code.md]]\n\n```md\n## AI 理解\n不是实际判断。\n```\n')
    result = studio.view(kb, 'goal/code.md')
    assert all(n['type'] != 'agent_understanding' for n in result['nodes'])


def test_local_state_symlink_cannot_redirect_editor_locks(kb, tmp_path):
    external = tmp_path / 'private-state'
    external.mkdir()
    (kb / '.oks').symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        studio.save_file(kb, {'path': 'goal/new.md', 'create': True, 'text': '# New'})
    assert list(external.iterdir()) == []


def test_use_counts_keep_their_original_meaning_and_do_not_mutate(kb):
    state = kb / '.oks'
    state.mkdir()
    path = state / 'access.json'
    path.write_text('{"rule": 3, "other": 1}')
    before = path.read_bytes()
    result = studio.usage(kb)
    assert result['entries'][0] == {'slug': 'rule', 'count': 3}
    assert result['timing_recorded'] is False and path.read_bytes() == before
    path.write_text('{"rule": true}')
    invalid = studio.usage(kb)
    assert invalid['warnings'] and invalid['entries'] == []


def test_new_goal_and_settings_are_instance_local_and_preserve_unknown_keys(kb, monkeypatch):
    monkeypatch.delenv('OKS_RECALL_TOPN', raising=False)
    created = studio.save_file(kb, {'path': 'goal/new/a.md', 'text': '# 新目标', 'create': True})
    assert created['title'] == '新目标'
    with pytest.raises(ValueError, match='exists'):
        studio.save_file(kb, {'path': 'goal/new/a.md', 'text': '# overwrite', 'create': True})
    (kb / 'settings').mkdir()
    (kb / 'settings/recall.yaml').write_text('custom: keep\nrecall:\n  topn: 3\n')
    before = studio.settings(kb)
    after = studio.save_settings(kb, {'expected_sha256': before['sha256'], 'values': {'recall_topn': 5, 'embedding_fallback': True}})
    assert after['values']['recall_topn'] == 5 and after['values']['embedding_fallback'] is True
    assert 'custom: keep' in (kb / 'settings/recall.yaml').read_text()
    for values in ({'recall_topn': True}, {'recall_floor': float('nan')}, {'memory_validity': 'off'}, {'unknown': 'secret'}):
        with pytest.raises(ValueError):
            studio.save_settings(kb, {'expected_sha256': after['sha256'], 'values': values})
    with pytest.raises(ValueError, match='changed'):
        studio.save_settings(kb, {'expected_sha256': before['sha256'], 'values': {'recall_topn': 8}})


@pytest.mark.parametrize('editing', [False, True])
def test_http_edit_permissions_instance_binding_and_reused_views(kb, editing):
    server = create_server(kb, 0, local_edit=editing)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def call(route, data=None, origin=base):
        req = Request(base + route, data=json.dumps(data).encode() if data is not None else None,
                      headers={'Content-Type': 'application/json', 'Origin': origin})
        return urlopen(req, timeout=5)
    try:
        with call('/') as response:
            assert b'/studio.js' in response.read()
        with call('/?panel=1#wiki-overview') as response:
            assert b'app.js' in response.read()
        for asset in ('studio.js', 'studio-model.js', 'studio.css', 'studio-theme.css', 'graph-labels.js',
                      'studio/api.js', 'studio/dom.js', 'studio/state.js', 'studio/graph.js',
                      'studio/discussion.js', 'studio/goals.js', 'studio/learning.js', 'studio/settings.js',
                      'studio/graph.css', 'studio/goals.css', 'studio/learning.css', 'studio/formulas.js', 'studio/knowledge.js', 'studio/knowledge-model.js', 'studio/evaluation.js', 'studio/evaluation-charts.js', 'studio/evaluation.css',
                      'vendor/katex/katex.min.js', 'vendor/katex/katex.min.css',
                      'vendor/katex/fonts/KaTeX_Main-Regular.woff2', 'studio-redirect.js'):
            with call('/' + asset) as response:
                assert response.status == 200
        with call('/api/studio/view?scope=goal%2Finterface') as response:
            assert json.load(response)['scope'] == 'goal/interface'
        payload = {'path': 'goal/new.md', 'text': '# New', 'create': True, 'expected_knowledge_base': str(kb)}
        with pytest.raises(HTTPError) as error:
            call('/api/studio/file', payload, 'http://evil.invalid')
        assert error.value.code == 403
        if editing:
            with pytest.raises(HTTPError) as error:
                call('/api/studio/file', {**payload, 'expected_knowledge_base': str(kb.parent)})
            assert error.value.code == 409
            with call('/api/studio/file', payload) as response:
                assert json.load(response)['path'] == 'goal/new.md'
        else:
            with pytest.raises(HTTPError) as error:
                call('/api/studio/file', payload)
            assert error.value.code == 403
            assert not (kb / 'goal/new.md').exists()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


def test_discussion_dates_are_paths_and_contexts_keep_their_own_roles(kb):
    assert studio.document_date('goal/2026/11/04/a.md') == '2026-11-04'
    assert studio.document_date('goal/2026/02/31/a.md') is None
    assert studio.document_date('profiles/goals/legacy.md') is None
    result = studio.scopes(kb, 'discuss')
    assert any(f['date'] == '2026-11-04' for s in result['scopes'] for f in s['files'])
    discussion = studio.view(kb, 'discuss/2026/11/04/interface.md')
    assert discussion['entry'] == 'discuss/2026/11/04/interface.md'
    assert 'goal/interface/index.md' in discussion['files']
    created = studio.save_file(kb, {'path':'discuss/2026/11/05/new.md','text':'# New discussion','create':True})
    assert created['kind'] == 'discuss'
    project = kb / 'profiles/projects/test.md'
    project.parent.mkdir(parents=True)
    project.write_text('# Project\n[[wiki/rule]]')
    result = studio.context_catalog(kb)
    assert next(item for item in result['entries'] if item['path']=='profiles/projects/test.md')['type']=='project'
    assert {'a':'profiles/projects/test.md','b':'wiki/rule.md','type':'cites'} in result['edges']
