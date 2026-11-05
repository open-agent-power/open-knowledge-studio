"""Goal reminder tests use synthetic tasks, not user completion evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
from knowledge_studio import reminders, tasks
from knowledge_studio.cli import app
from knowledge_studio.mail_web import create_server

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root, work = tmp_path / '实例 空格', tmp_path / 'work'
    work.mkdir()
    for folder in ('profiles/goals', 'wiki', 'mail', 'drafts', 'settings'):
        (root / folder).mkdir(parents=True)
    (root / 'profiles/goals/report.md').write_text('---\ntype: goal\n---\nCite report sources.\n', encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT', str(root)); monkeypatch.setenv('OKS_TASK_HOME', str(tmp_path / 'bindings'))
    monkeypatch.setenv('OKS_FEEDBACK_HOME', str(tmp_path / 'private'))
    tasks.start(root, 'report', 'profiles/goals/report.md', [])
    return root, work


def request(root, identifier='check'):
    return dict(task_id='report', id=identifier, note='CHECK_LIFECYCLE_REMINDER', due_at=NOW.isoformat(),
        expected_agreement_sha256=tasks.show(root, 'report')['agreement']['sha256'])


def change(root, item, action, **extra):
    return reminders.update(root, dict(task_id='report', id=item['id'], expected_revision=item['revision'],
        action=action, expected_agreement_sha256=tasks.show(root,'report')['agreement']['sha256'], **extra), now=NOW)


def test_due_snooze_complete_cancel_and_revision_conflicts(kb):
    root, _ = kb
    item = reminders.add(root, request(root), now=NOW)
    assert item['status'] == 'due'
    item = change(root, item, 'snooze', due_at=(NOW + timedelta(hours=1)).isoformat())
    assert item['status'] == 'scheduled' and item['revision'] == 2
    with pytest.raises(ValueError, match='current revision'):
        reminders.update(root, dict(task_id='report',id='check',expected_revision=1,action='complete'))
    item = change(root,item,'complete')
    assert item['status'] == 'completed' and reminders.due_for_session(root,'report','s',now=NOW+timedelta(days=1)) == []
    with pytest.raises(ValueError, match='already completed'):
        change(root,item,'cancel')
    other=reminders.add(root,request(root,'other'),now=NOW)
    assert change(root,other,'cancel')['status'] == 'cancelled'
    assert not reminders.listing(root,'report')['background_wake']


def test_goal_edit_pauses_reminder_until_task_and_reminder_are_explicitly_confirmed(kb):
    root,_=kb
    item=reminders.add(root,request(root),now=NOW)
    path=root/'profiles/goals/report.md';path.write_text(path.read_text(encoding='utf-8')+'New constraints\n',encoding='utf-8')
    assert reminders.listing(root,'report',now=NOW)['items'][0]['status'] == 'needs_review'
    assert reminders.due_for_session(root,'report','s',now=NOW) == []
    with pytest.raises(ValueError): change(root,item,'confirm')
    tasks.refresh(root,'report',1)
    assert reminders.listing(root,'report',now=NOW)['items'][0]['status'] == 'needs_review'
    assert change(root,item,'confirm')['status'] == 'due'


def test_session_dedup_is_atomic_and_failed_output_is_not_marked(kb):
    root,_=kb;reminders.add(root,{**request(root),'due_at':'2020-01-01T00:00:00Z'},now=NOW)
    with pytest.raises(RuntimeError):
        with reminders.output_guard(root,'report','same') as due:
            assert len(due)==1
            raise RuntimeError('output pipe failed')
    def emit(_):
        with reminders.output_guard(root,'report','same') as due:return len(due)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(emit,range(2))) == [0,1]
    assert reminders.due_for_session(root,'report','same') == []
    assert len(reminders.due_for_session(root,'report','another')) == 1
    assert reminders.due_for_session(root,'report','') == []


@pytest.mark.parametrize('date', ['2026-10-28T12:00:00', 'invalid', None])
def test_ambiguous_times_do_not_create_records(kb,date):
    root,_=kb
    with pytest.raises(ValueError): reminders.add(root,{**request(root),'due_at':date})
    assert reminders.listing(root,'report')['items'] == []


def test_duplicate_add_and_snooze_past_never_overwrite(kb):
    root,_=kb
    item=reminders.add(root,request(root),now=NOW)
    with pytest.raises(ValueError,match='already exists'):reminders.add(root,request(root),now=NOW)
    with pytest.raises(ValueError,match='future time'):change(root,item,'snooze',due_at=NOW.isoformat())
    assert reminders.listing(root,'report',now=NOW)['items'][0]['revision'] == 1


def test_actual_hook_dedups_and_requires_selected_task(kb):
    root,work=kb
    reminders.add(root,{**request(root),'due_at':'2020-01-01T00:00:00Z'})
    from knowledge_studio.resources import asset_root
    hook=asset_root()/'hooks/user-prompt-recall.py'
    env={**os.environ,'OKS_HOOK_OUTPUT':'json'}
    def run():
        p=subprocess.run([sys.executable,str(hook)],input=json.dumps(dict(prompt='继续',session_id='test-session',cwd=str(work))),
            cwd=work,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert p.returncode==0,p.stderr
        return json.loads(p.stdout).get('context','')
    assert 'CHECK_LIFECYCLE_REMINDER' not in run()
    tasks.select(root,work,'report')
    assert 'CHECK_LIFECYCLE_REMINDER' in run()
    assert 'CHECK_LIFECYCLE_REMINDER' not in run()
    assert reminders.listing(root,'report')['items'][0]['state'] == 'pending'


@contextmanager
def http(root,**flags):
    server=create_server(root,0,**flags);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def post(payload,origin=None):
        headers={'Content-Type':'application/json','Origin':origin if origin is not None else base}
        req=Request(base+'/api/tasks/reminders',data=json.dumps(payload).encode(),headers=headers)
        with urlopen(req,timeout=10) as response:return json.load(response)
    try:yield post
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_http_edit_permission_origin_instance_and_scope_boundaries(kb):
    root,_=kb;payload={**request(root),'action':'add','expected_knowledge_base':str(root)}
    for flags in ({},{'local_review':True},{'mode':'collaboration'}):
        with http(root,**flags) as post:
            with pytest.raises(HTTPError) as error:post(payload)
            assert error.value.code==403
    with http(root,local_edit=True) as post:
        for origin in ('','http://evil.invalid'):
            with pytest.raises(HTTPError) as error:post(payload,origin)
            assert error.value.code==403
        with pytest.raises(HTTPError) as error:post({**payload,'expected_knowledge_base':'other'})
        assert error.value.code==409
        assert post(payload)['id']=='check'
    assert len(reminders.listing(root,'report')['items'])==1


def test_cli_controls_use_the_current_agreement(kb):
    root,_=kb;runner=CliRunner()
    result=runner.invoke(app,['task','remind','add','report','cli','--text','Review','--at',NOW.isoformat(),
        '--agreement-sha256',tasks.show(root,'report')['agreement']['sha256']])
    assert result.exit_code==0,result.output
    result=runner.invoke(app,['task','remind','update','report','cli','complete','--revision','1'])
    assert result.exit_code==0 and json.loads(result.output)['status']=='completed'
