"""Task closure is a caller declaration; synthetic controls are not user approval."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner
from knowledge_studio import feedback, handoff, reminders, store, tasks
from knowledge_studio.cli import app
from knowledge_studio.recall import recall
from knowledge_studio.retrieval_debug import agreement_context

DATA=json.loads((Path(__file__).parent/'fixtures/task-lifecycle.json').read_text(encoding='utf-8'))
NOW=datetime(2026,10,28,12,tzinfo=UTC)


@pytest.fixture
def kb(tmp_path,monkeypatch):
    root,work=tmp_path/'知识库 空格',tmp_path/'work';work.mkdir()
    for folder in ('profiles/goals','wiki','mail','drafts','settings'):(root/folder).mkdir(parents=True)
    (root/'profiles/goals/report.md').write_text('---\ntype: goal\ntitle: Report\nstatus: active\n---\nSECRET_OLD_TASK_GOAL\n',encoding='utf-8')
    (root/'wiki/source.md').write_text('---\ntitle: source\ntype: strategy\narea: computing\nstatus: active\nhuman_reviewed_at: synthetic\n---\nSource citations.\n',encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT',str(root));monkeypatch.setenv('OKS_TASK_HOME',str(tmp_path/'bindings'))
    monkeypatch.setenv('OKS_FEEDBACK_HOME',str(tmp_path/'private'));monkeypatch.chdir(work)
    tasks.start(root,'report','profiles/goals/report.md',['wiki/source.md'])
    return root,work


def close(root,action='complete'):
    return tasks.transition(root,'report',tasks.show(root,'report')['revision'],action,'Synthetic declaration only')


@pytest.mark.parametrize('case',DATA['cases'])
def test_frozen_transition_matrix(kb,case):
    root,_=kb
    if case['from']!='active':close(root,'complete' if case['from']=='completed' else 'cancel')
    before=tasks._path(root,'report').read_bytes()
    if case['to'] is None:
        with pytest.raises(ValueError):close(root,case['action'])
        assert tasks._path(root,'report').read_bytes()==before
    else:
        value=close(root,case['action']);assert value['lifecycle']==case['to']
        assert value['history'][-1]['lifecycle']==case['from'] and value['execution_verified'] is False


def test_legacy_reads_do_not_migrate_and_closure_preserves_outputs_goal_and_history(kb):
    root,_=kb;path=tasks._path(root,'report');before=path.read_bytes();goal=(root/'profiles/goals/report.md').read_bytes()
    assert 'lifecycle' not in json.loads(before)
    assert tasks.show(root,'report')['lifecycle']=='active'
    assert tasks.overview(root,now=NOW)['counts']['active']==1 and path.read_bytes()==before
    (root/'report.md').write_text('Actual output reference',encoding='utf-8')
    saved=tasks.checkpoint(root,'report',1,'Draft saved','Review',['report.md'])
    value=close(root)
    assert value['revision']==3 and value['artifacts']==saved['artifacts']
    assert value['status']=='current' and value['history'][-1]['progress']=='Draft saved'
    assert (root/'profiles/goals/report.md').read_bytes()==goal
    assert 'resume_command' not in tasks.export_handoff(root,'report')
    assert tasks.show(root,'report')['lifecycle']=='completed'


def test_closed_task_blocks_binding_explicit_agreement_feedback_mail_and_progress(kb):
    from knowledge_studio.mail import write_message
    from knowledge_studio.skills import search
    root,work=kb;agreement=tasks.show(root,'report')['agreement'];tasks.select(root,work,'report','fixture','project')
    scope=dict(subject='fixture',project='project',task='report')
    event=dict(scope=scope,agreement=agreement,event_id='signal',action='adopted',reason='Synthetic',asset_path='wiki/source.md')
    feedback.record(root,event)
    candidate=feedback.propose(root,dict(scope=scope,candidate_id='rule',event_ids=['signal'],title='Rule',summary='PRIVATE_CLOSED_RULE'))
    feedback.review(root,dict(scope=scope,candidate_id='rule',expected_revision=candidate['revision'],decision='approve',comment='Synthetic fixture'))
    close(root)
    for operation in [lambda:tasks.select(root,work,'report'),lambda:recall('continue'),
        lambda:recall('source',agreement=agreement,task_scope='report',use_task=False),
        lambda:agreement_context(root,agreement,'report'),lambda:search('source',agreement=agreement,task_scope='report'),
        lambda:feedback.select_context(root,scope,agreement),lambda:feedback.record(root,{**event,'event_id':'new'}),
        lambda:write_message(root,body='x',sender='human',recipients=['other'],kind='handoff',agreement=agreement),
        lambda:tasks.checkpoint(root,'report',2,'x','y',[]),lambda:tasks.refresh(root,'report',2),
        lambda:tasks.update_sources(root,'report',2,[])]:
        with pytest.raises(ValueError,match='closed'):operation()
    assert 'continuation' not in recall('source',use_task=False)
    standalone=handoff.prepare(root,'profiles/goals/report.md',[],'unrelated standalone scope')
    assert agreement_context(root,standalone,'unrelated standalone scope')['status']=='current'
    assert feedback.inspect(root,scope)['candidates'][0]['effective_status']=='invalidated'


def test_reopen_preserves_source_gate_and_requires_reminder_confirmation(kb):
    root,work=kb;task=tasks.show(root,'report')
    reminder=reminders.add(root,dict(task_id='report',id='due',note='REMINDER_OLD',due_at=NOW.isoformat(),expected_agreement_sha256=task['agreement']['sha256']),now=NOW)
    close(root)
    assert reminders.listing(root,'report',now=NOW)['items'][0]['status']=='task_closed'
    assert reminders.due_for_session(root,'report','s',now=NOW)==[]
    with pytest.raises(ValueError,match='closed'):
        reminders.add(root,dict(task_id='report',id='new',note='x',due_at=NOW.isoformat()))
    goal=root/'profiles/goals/report.md';goal.write_text(goal.read_text(encoding='utf-8')+'Changed audience\n',encoding='utf-8')
    reopened=close(root,'reopen');assert reopened['activation']==2 and reopened['status']=='needs_review'
    with pytest.raises(ValueError):tasks.select(root,work,'report')
    current=tasks.refresh(root,'report',reopened['revision'])
    assert reminders.listing(root,'report',now=NOW)['items'][0]['status']=='needs_review'
    request=dict(task_id='report',id='due',action='confirm',expected_revision=reminder['revision'],expected_agreement_sha256=current['agreement']['sha256'])
    assert reminders.update(root,request,now=NOW)['status']=='due'
    assert reminders.due_for_session(root,'report','s',now=NOW)


def test_reopen_unchanged_sources_still_pauses_old_reminders(kb):
    root,_=kb;task=tasks.show(root,'report')
    reminders.add(root,dict(task_id='report',id='due',note='x',due_at=NOW.isoformat(),expected_agreement_sha256=task['agreement']['sha256']),now=NOW)
    close(root);close(root,'reopen')
    assert tasks.show(root,'report')['status']=='current'
    assert reminders.listing(root,'report',now=NOW)['items'][0]['status']=='needs_review'


def test_stale_revision_failed_save_and_concurrent_close_preserve_state(kb,monkeypatch):
    root,_=kb;path=tasks._path(root,'report');before=path.read_bytes()
    with pytest.raises(ValueError):tasks.transition(root,'report',True,'complete','x')
    with pytest.raises(ValueError):tasks.transition(root,'report',1,'complete',' ')
    with monkeypatch.context() as patch:
        def fail(*args):raise OSError('disk full')
        patch.setattr(store,'_atomic_write',fail)
        with pytest.raises(OSError):close(root)
    assert path.read_bytes()==before
    def attempt(_):
        try:tasks.transition(root,'report',1,'complete','Synthetic');return 'saved'
        except ValueError:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,range(2)))==['saved','stale']
    assert tasks.show(root,'report')['revision']==2


def test_overview_exposes_changes_corruption_and_truncation_without_writes(kb):
    root,_=kb
    (root/'.oks/tasks/broken.json').write_text('{bad',encoding='utf-8')
    (root/'wiki/source.md').write_text('changed',encoding='utf-8')
    view=tasks.overview(root,now=NOW)
    assert view['counts']==dict(active=1,needs_review=1,closed=0,unavailable=1,due=0)
    before=tasks._path(root,'report').read_bytes()
    for n in range(102):(root/'.oks/tasks'/f'bad{n}.json').write_text('{}',encoding='utf-8')
    view=tasks.overview(root,now=NOW)
    assert view['truncated'] and len(view['tasks'])==100 and tasks._path(root,'report').read_bytes()==before


def test_actual_hook_does_not_emit_closed_goal_private_rule_or_reminder(kb):
    root,work=kb;task=tasks.show(root,'report');tasks.select(root,work,'report')
    reminders.add(root,dict(task_id='report',id='due',note='SECRET_OLD_REMINDER',due_at='2000-01-01T00:00:00Z',expected_agreement_sha256=task['agreement']['sha256']))
    close(root)
    hook=Path(__file__).resolve().parents[2]/'assets/hooks/user-prompt-recall.py'
    if not hook.exists():
        from knowledge_studio.mail_setup import asset_root
        hook=asset_root()/'hooks/user-prompt-recall.py'
    p=subprocess.run([sys.executable,str(hook)],input=json.dumps(dict(prompt='继续',session_id='closed',cwd=str(work))),cwd=work,
        env={**os.environ,'OKS_HOOK_OUTPUT':'json'},capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert p.returncode==0,p.stderr
    context=json.loads(p.stdout)['context']
    assert '任务已结束' in context and 'SECRET_OLD_TASK_GOAL' not in context and 'SECRET_OLD_REMINDER' not in context


@pytest.mark.parametrize('flags',[{},dict(local_review=True),dict(mode='collaboration'),dict(local_edit=True)])
def test_http_lifecycle_permissions_revision_and_instance(kb,flags):
    from knowledge_studio.mail_web import create_server
    root,_=kb;server=create_server(root,0,**flags);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    payload=dict(task_id='report',expected_revision=1,action='complete',reason='Synthetic UI declaration',expected_knowledge_base=str(root))
    def post(data,origin=base):
        with urlopen(Request(base+'/api/tasks/lifecycle',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin}),timeout=10) as response:return json.load(response)
    try:
        with urlopen(base+'/api/tasks/overview',timeout=10) as response:assert json.load(response)['counts']['active']==1
        if not flags.get('local_edit'):
            with pytest.raises(HTTPError) as error:post(payload)
            assert error.value.code==403
        else:
            for data,origin,code in [(payload,'http://evil.invalid',403),({**payload,'expected_knowledge_base':'other'},base,409),({**payload,'expected_revision':0},base,409)]:
                with pytest.raises(HTTPError) as error:post(data,origin)
                assert error.value.code==code
            assert post(payload)['lifecycle']=='completed'
            with pytest.raises(HTTPError) as error:post(payload)
            assert error.value.code==409
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_cli_completion_and_explicit_reopen(kb):
    root,_=kb;runner=CliRunner()
    assert runner.invoke(app,['task','complete','report','--revision','1']).exit_code!=0
    value=runner.invoke(app,['task','cancel','report','--revision','1','--reason','Synthetic'])
    assert value.exit_code==0 and json.loads(value.output)['lifecycle']=='cancelled'
    value=runner.invoke(app,['task','reopen','report','--revision','2','--reason','New work'])
    assert value.exit_code==0 and json.loads(value.output)['activation']==2
