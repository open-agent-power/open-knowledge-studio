"""Exact-version task page operations, with clearly synthetic approvals."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import pytest
from knowledge_studio import feedback,reminders,tasks,workspace
from knowledge_studio.mail_web import create_server

DATA=json.loads((Path(__file__).parent/'fixtures/task-flow.json').read_text(encoding='utf-8'))


@pytest.fixture
def kb(tmp_path,monkeypatch):
    root=tmp_path/'实例 空格';work=tmp_path/'work';work.mkdir()
    for name in ('profiles/goals','wiki','mail','drafts','settings','reports'):(root/name).mkdir(parents=True)
    (root/'profiles/goals/report.md').write_text('---\ntype: goal\ntitle: Report\nstatus: active\n---\nKeep citations.\n',encoding='utf-8')
    for name in ('a','b'):(root/f'wiki/{name}.md').write_text(f'---\ntitle: Source {name}\ntype: strategy\narea: computing\nstatus: active\nhuman_reviewed_at: synthetic\noptions: []\n---\n{name} source body.\n',encoding='utf-8')
    (root/'reports/report.md').write_text('Actual artifact contents, synthetic task.',encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT',str(root));monkeypatch.setenv('OKS_TASK_HOME',str(tmp_path/'bindings'));monkeypatch.setenv('OKS_FEEDBACK_HOME',str(tmp_path/'private'));monkeypatch.chdir(work)
    tasks.start(root,'report','profiles/goals/report.md',['wiki/a.md'])
    return root,work


def snapshot(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def acceptance(view,paths=None):
    paths=paths if paths is not None else [v['path'] for v in view['sources']]
    choices={v['path']:v for v in view['choices']}
    return dict(task_id='report',expected_revision=view['revision'],accept_changes=True,
        expected_goal_sha256=view['goal']['current']['sha256'],wiki=[{key:choices[path][key] for key in ('path','sha256')} for path in paths])


def progress(root):
    task=tasks.show(root,'report')
    return dict(task_id='report',expected_revision=task['revision'],expected_agreement_sha256=task['agreement']['sha256'],
        progress='Draft written',next_action='Review sources',artifacts=['reports/report.md'])


def test_previews_are_read_only_and_do_not_invent_old_wiki_body(kb):
    root,_=kb
    old=workspace.task_review(root,'report');assert old['sources'][0]['historical_bytes_available']
    page=root/'wiki/a.md';page.write_text(page.read_text(encoding='utf-8')+'Updated content\n',encoding='utf-8')
    before=snapshot(root);view=workspace.task_review(root,'report');handoff=workspace.task_handoff(root,'report',1)
    assert snapshot(root)==before and not view['state_mutated'] and not handoff['state_mutated']
    source=view['sources'][0]
    assert not source['historical_bytes_available'] and 'text' not in source['before']
    assert 'Updated content' in source['current']['text']
    assert source['before']['sha256']!=source['current']['sha256']
    assert '# 接手说明：report' in handoff['text']
    assert '来源变化已阻止接续' in handoff['text']
    assert 'resume_command' not in handoff['text']


@pytest.mark.parametrize('changed',['goal','wiki'])
def test_cannot_accept_a_version_changed_after_preview(kb,changed):
    root,_=kb;view=workspace.task_review(root,'report');request=acceptance(view)
    path=root/('profiles/goals/report.md' if changed=='goal' else 'wiki/a.md')
    path.write_text(path.read_text(encoding='utf-8')+'Unseen later change\n',encoding='utf-8')
    before=tasks._path(root,'report').read_bytes()
    with pytest.raises(ValueError,match='changed since inspection'):workspace.accept_task_sources(root,request)
    assert tasks._path(root,'report').read_bytes()==before
    updated=workspace.accept_task_sources(root,acceptance(workspace.task_review(root,'report')))
    assert updated['revision']==2 and updated['status']=='current'
    assert updated['history'][0]['agreement']!=updated['agreement']


def test_explicit_review_choice_replaces_source_and_preserves_outputs_and_scope_gates(kb):
    root,work=kb;task=tasks.show(root,'report');selection=dict(subject='synthetic',project='trial',task='report')
    feedback.record(root,dict(scope=selection,event_id='signal',agreement=task['agreement'],asset_path='wiki/a.md',action='adopted',reason='Synthetic only'))
    candidate=feedback.propose(root,dict(scope=selection,candidate_id='rule',event_ids=['signal'],title='Synthetic',summary='PRIVATE_RULE'))
    feedback.review(root,dict(scope=selection,candidate_id='rule',expected_revision=candidate['revision'],decision='approve',comment='Synthetic approval fixture'))
    reminders.add(root,dict(task_id='report',id='due',note='Review',due_at='2000-01-01T00:00:00Z',expected_agreement_sha256=task['agreement']['sha256']))
    saved=workspace.save_task_progress(root,progress(root))
    goal=root/'profiles/goals/report.md';goal.write_text(goal.read_text(encoding='utf-8')+'New audience.\n',encoding='utf-8')
    request=acceptance(workspace.task_review(root,'report'),['wiki/b.md'])
    with pytest.raises(ValueError):workspace.accept_task_sources(root,{**request,'accept_changes':False})
    updated=workspace.accept_task_sources(root,request)
    assert updated['artifacts']==saved['artifacts'] and updated['history'][-1]['agreement']['knowledge'][0]['path']=='wiki/a.md'
    assert [v['path'] for v in updated['agreement']['knowledge']]==['wiki/b.md']
    assert reminders.listing(root,'report')['items'][0]['status']=='needs_review'
    assert not feedback.select_context(root,selection,updated['agreement'])['candidates']


def test_missing_unreviewed_and_expired_sources_need_explicit_replacement(kb):
    root,_=kb;source=root/'wiki/a.md';source.unlink()
    view=workspace.task_review(root,'report');assert view['sources'][0]['current'] is None
    assert workspace.accept_task_sources(root,acceptance(view,['wiki/b.md']))['status']=='current'
    source=root/'wiki/b.md';text=source.read_text(encoding='utf-8')
    source.write_text(text.replace('status: active','status: draft'),encoding='utf-8')
    view=workspace.task_review(root,'report');assert not next(v for v in view['choices'] if v['path']=='wiki/b.md')['eligible']
    with pytest.raises(ValueError):workspace.accept_task_sources(root,acceptance(view))
    source.write_text(text.replace('options: []','options: []\napplicability:\n  valid_until: "2000-01-01T00:00:00Z"'),encoding='utf-8')
    (root/'settings/recall.yaml').write_text('memory_validity: enforce\n',encoding='utf-8')
    view=workspace.task_review(root,'report');assert view['sources'][0]['current']['reason']=='expired'
    before=tasks._path(root,'report').read_bytes()
    with pytest.raises(ValueError,match='not applicable'):workspace.accept_task_sources(root,acceptance(view))
    assert tasks._path(root,'report').read_bytes()==before
    assert not workspace.accept_task_sources(root,acceptance(view,[]))['agreement']['knowledge']


def test_noop_drift_closed_and_bad_source_requests_preserve_records(kb):
    root,_=kb;view=workspace.task_review(root,'report');request=acceptance(view)
    before=tasks._path(root,'report').read_bytes()
    assert workspace.accept_task_sources(root,request)['revision']==1 and tasks._path(root,'report').read_bytes()==before
    for override in [dict(expected_revision=True),dict(wiki='x'),dict(wiki=[dict(path='../outside.md',sha256='x')]),dict(wiki=request['wiki']*2),dict(expected_goal_sha256='old')]:
        with pytest.raises(ValueError):workspace.accept_task_sources(root,{**request,**override})
        assert tasks._path(root,'report').read_bytes()==before
    workspace.save_task_progress(root,progress(root))
    with pytest.raises(ValueError,match='revision'):workspace.accept_task_sources(root,request)
    tasks.transition(root,'report',2,'complete','Synthetic')
    request=acceptance(workspace.task_review(root,'report'))
    with pytest.raises(ValueError,match='closed'):workspace.accept_task_sources(root,request)
    with pytest.raises(ValueError,match='closed'):workspace.save_task_progress(root,progress(root))


def test_shadow_remains_observational_and_enforce_rejects_expired_sources(kb):
    root,_=kb;source=root/'wiki/a.md'
    source.write_text(source.read_text(encoding='utf-8').replace('options: []','options: []\napplicability:\n  valid_until: "2000-01-01T00:00:00Z"'),encoding='utf-8')
    view=workspace.task_review(root,'report');choice=next(v for v in view['choices'] if v['path']=='wiki/a.md')
    assert choice['time_status']=='expired' and not choice['time_enforced'] and choice['eligible']
    assert workspace.accept_task_sources(root,acceptance(view))['status']=='current'
    (root/'settings/recall.yaml').write_text('memory_validity: enforce\n',encoding='utf-8')
    view=workspace.task_review(root,'report');assert not view['sources'][0]['current']['eligible']
    with pytest.raises(ValueError,match='not applicable'):workspace.accept_task_sources(root,acceptance(view))


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda v:v['name'])
def test_frozen_invalid_progress_requests_never_mutate(kb,case):
    root,_=kb;before=tasks._path(root,'report').read_bytes()
    with pytest.raises((ValueError,OSError)):workspace.save_task_progress(root,{**progress(root),**case['override']})
    assert tasks._path(root,'report').read_bytes()==before


def test_progress_handoff_and_artifact_versions_remain_traceable(kb):
    root,work=kb;before=tasks.binding(root,work)
    saved=workspace.save_task_progress(root,progress(root));assert saved['revision']==2 and not saved.get('uses')
    artifact=workspace.artifact(root,'report','reports/report.md',2);assert artifact['status']=='unchanged'
    text=workspace.task_handoff(root,'report',2)['text']
    assert 'Review sources' in text
    assert all(item['path'] in text and item['sha256'] in text for item in saved['artifacts'])
    assert tasks.show(root,'report')['agreement']['sha256'] in text
    assert '执行验证：未验证' in text
    assert tasks.binding(root,work)==before
    assert not list((root/'mail').rglob('*.md'))
    with pytest.raises(ValueError,match='revision'):workspace.task_handoff(root,'report',1)
    tasks.transition(root,'report',2,'cancel','Synthetic')
    text=workspace.task_handoff(root,'report',3)['text'];assert '# 已结束任务：report' in text and 'oks task show --task-id report' in text and 'resume_command' not in text


def test_truncated_choices_do_not_drop_pinned_source(kb):
    root,_=kb
    for n in range(102):(root/f'wiki/extra{n}.md').write_text('---\ntitle: extra\nstatus: active\nhuman_reviewed_at: synthetic\n---\ntext',encoding='utf-8')
    view=workspace.task_review(root,'report')
    assert view['truncated'] and view['sources'][0]['path']=='wiki/a.md'
    assert any(v['path']=='wiki/a.md' for v in view['choices'])


@contextmanager
def server(root,**flags):
    service=create_server(root,0,**flags);thread=Thread(target=service.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{service.server_port}'
    def call(route,payload=None,origin=None):
        req=Request(base+route,data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json','Origin':origin if origin is not None else base})
        with urlopen(req,timeout=10) as response:return json.load(response)
    try:yield base,call
    finally:service.shutdown();service.server_close();thread.join(timeout=5)


@pytest.mark.parametrize('flags',[{},dict(local_review=True),dict(mode='collaboration'),dict(local_edit=True)])
def test_http_source_progress_permissions_origin_instance_and_read_only_handoff(kb,flags):
    root,_=kb
    with server(root,**flags) as (base,call):
        view=call('/api/tasks/review?id=report');assert view['knowledge_base']==str(root)
        handoff=call('/api/tasks/handoff?id=report&revision=1');assert handoff['knowledge_base']==str(root)
        shown=call('/api/tasks/show?id=report');assert shown['knowledge_base']==str(root)
        for route,request in [('/api/tasks/accept-sources',acceptance(view)),('/api/tasks/progress',progress(root))]:
            request['expected_knowledge_base']=str(root)
            if not flags.get('local_edit'):
                with pytest.raises(HTTPError) as error:call(route,request)
                assert error.value.code==403
            else:
                for value,origin,code in [(request,'http://evil.invalid',403),({**request,'expected_knowledge_base':'other'},base,409)]:
                    with pytest.raises(HTTPError) as error:call(route,value,origin)
                    assert error.value.code==code
                result=call(route,request);assert result['knowledge_base']==str(root)
