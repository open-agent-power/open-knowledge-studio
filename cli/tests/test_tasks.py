"""Task continuity contracts; real model acceptance is recorded separately."""
import json
import shlex
from pathlib import Path
import os
import subprocess
import sys
from threading import Thread
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner
from knowledge_studio import tasks, store
from knowledge_studio.cli import app
from knowledge_studio.recall import recall


@pytest.fixture
def task_kb(tmp_path, monkeypatch):
    root=tmp_path/'kb'; workspace=tmp_path/'work'; workspace.mkdir()
    (root/'profiles/goals').mkdir(parents=True); (root/'wiki').mkdir(); (root/'mail').mkdir(); (root/'settings').mkdir()
    (root/'profiles/goals/report.md').write_text('---\ntype: goal\ntitle: Report\nstatus: active\n---\nKeep source citations.\n',encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT',str(root));monkeypatch.setenv('OKS_TASK_HOME',str(tmp_path/'bindings'))
    monkeypatch.chdir(workspace)
    tasks.start(root,'report','profiles/goals/report.md',[])
    return root, workspace


def test_selected_task_survives_process_and_never_infers_private_labels(task_kb):
    root,workspace=task_kb
    tasks.select(root,workspace,'report')
    result=recall('continue')
    assert result['continuation']['task_id']=='report'
    assert result['task_context']['status']=='not_requested'
    done=subprocess.run([sys.executable,'-c','from knowledge_studio.cli import app; app()','task','show'],env=os.environ,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert done.returncode==0,done.stderr
    assert json.loads(done.stdout)['task_id']=='report'
    assert 'continuation' not in recall('unrelated',use_task=False)
    assert 'continuation' not in recall('unrelated',workspace=workspace.parent)
    tasks.clear(root,workspace)
    assert tasks.binding(root,workspace) is None and tasks.show(root,'report')['revision']==1


def test_changed_goal_requires_explicit_refresh_and_preserves_history(task_kb):
    root,workspace=task_kb
    tasks.select(root,workspace,'report')
    (root/'report.md').write_text('Actual draft',encoding='utf-8')
    tasks.checkpoint(root,'report',1,'Initial outline written','Write evidence section',['report.md'])
    (root/'profiles/goals/report.md').write_text('---\ntype: goal\n---\nNew audience: managers.\n',encoding='utf-8')
    changed=tasks.show(root,'report')
    assert changed['status']=='needs_review'
    assert 'managers' in changed['current_goal_text']
    assert 'managers' not in changed['agreement']['goal']['text']
    with pytest.raises(ValueError,match='needs review'):recall('continue')
    with pytest.raises(ValueError,match='stale'):tasks.checkpoint(root,'report',2,'x','y',[])
    result=CliRunner().invoke(app,['task','refresh','report','--revision','2'])
    assert result.exit_code==2
    tasks.refresh(root,'report',2)
    result=recall('continue')
    assert 'managers' in result['continuation']['goal_text']
    assert result['continuation']['progress']=='Initial outline written'
    assert tasks.show(root,'report')['history'][0]['agreement']['goal']['text'].rstrip().endswith('Keep source citations.')
    (root/'report.md').write_text('External edit',encoding='utf-8')
    assert tasks.show(root,'report')['artifact_issues'][0]['code']=='artifact_changed'
    (root/'profiles/goals/report.md').unlink()
    missing=tasks.show(root,'report')
    assert missing['status']=='needs_review' and missing['current_goal_text'] is None


def test_task_binding_does_not_cross_kb_and_explicit_agreement_wins(task_kb):
    root,workspace=task_kb
    tasks.select(root,workspace,'report','alice','project')
    assert tasks.binding(root.parent/'other',workspace) is None
    explicit=tasks.show(root,'report')['agreement']
    assert 'continuation' not in recall('report',agreement=explicit,task_scope='report')
    assert recall('report',agreement=explicit,task_scope='report')['task_context']['status']=='not_requested'
    with pytest.raises(ValueError,match='differs'):recall('report',task_scope='other')
    assert 'alice' not in (root/'.oks/tasks/report.json').read_text(encoding='utf-8')


def test_checkpoint_stale_write_path_and_atomic_failure(task_kb,monkeypatch):
    root,workspace=task_kb
    with pytest.raises(ValueError,match='revision'):tasks.checkpoint(root,'report',0,'x','y',[])
    with pytest.raises(ValueError,match='canonical'):tasks.checkpoint(root,'report',1,'x','y',['../outside'])
    before=(root/'.oks/tasks/report.json').read_bytes()
    def fail(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(store,'_atomic_write',fail)
    with pytest.raises(OSError):tasks.checkpoint(root,'report',1,'x','y',[])
    assert (root/'.oks/tasks/report.json').read_bytes()==before


def test_private_binding_inside_kb_and_partial_labels_rejected(task_kb,monkeypatch):
    root,workspace=task_kb
    with pytest.raises(ValueError,match='both'):tasks.select(root,workspace,'report','alice')
    monkeypatch.setenv('OKS_TASK_HOME',str(root/'.oks/bindings'))
    with pytest.raises(ValueError,match='outside'):tasks.select(root,workspace,'report')


def test_short_continue_hook_and_read_only_task_page(task_kb):
    from knowledge_studio.mail_web import create_server
    root,workspace=task_kb; tasks.select(root,workspace,'report')
    tasks.checkpoint(root,'report',1,'Outline ready','Check current claims',[])
    hook=Path(__file__).resolve().parents[2]/'assets/hooks/user-prompt-recall.py'
    done=subprocess.run([sys.executable,str(hook)],input=json.dumps({'prompt':'继续','cwd':str(workspace),'session_id':'task-short'}),env={**os.environ,'OKS_HOOK_OUTPUT':'json'},capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert done.returncode==0,done.stderr
    assert 'Check current claims' in done.stdout
    server=create_server(root,port=0);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        with urlopen(base+'/api/tasks/show?id=report') as response:value=json.load(response)
        assert value['progress']=='Outline ready' and value['execution_verified'] is False
        with urlopen(base+'/tasks') as response:assert '当前进度' in response.read().decode()
    finally:server.shutdown();server.server_close();worker.join(timeout=5)


def test_handoff_is_local_read_only(task_kb):
    root,workspace=task_kb
    before=(root/'.oks/tasks/report.json').read_bytes()
    text=tasks.export_handoff(root,'report')
    assert 'oks task select report' in text and 'Keep source citations.' in text
    assert (root/'.oks/tasks/report.json').read_bytes()==before
    command=json.loads(text.split('\n\n',1)[1])['check_command']
    assert CliRunner().invoke(app,shlex.split(command)[1:]).exit_code==0
    assert tasks.binding(root,workspace) is None


def test_compact_context_preserves_requirements_and_source_identity(task_kb):
    from copy import deepcopy
    from knowledge_studio.recall import compact_context
    root,workspace=task_kb
    tasks.select(root,workspace,'report')
    original=recall('report',debug_record=True)
    original['knowledge']=[{'slug':'rule','source_path':'wiki/rule.md','source_sha256':'a'*64,
        'body_preview':'Read the full rule before acting','options':[{'decision':'do not publish'}],
        'human_reviewed_at':'2026-10-27','status':'active','skill_version':'v1','load_command':'oks skills load report --version v1',
        'score_components':{'retrieval_score':3},'rank':1,'schema_version':'recall-hit/v1'}]
    original['task_context']={'status':'selected','candidates':[{'summary':'Never omit the source restriction'}],'excluded_counts':{'invalidated':2}}
    original['diagnostics']['fallback_reason']='fts5_unavailable'
    before=deepcopy(original)
    compact=compact_context(original)
    assert original==before
    assert compact['continuation']==original['continuation']
    assert compact['task_context']==original['task_context']
    assert compact['knowledge'][0]['options']==original['knowledge'][0]['options']
    for field in ('source_sha256','human_reviewed_at','status','skill_version','load_command','body_preview'):
        assert compact['knowledge'][0][field]==original['knowledge'][0][field]
    assert not any(h.get('source_path')=='profiles/goals/report.md' for h in compact['episodic'])
    assert compact['warnings']['fallback_reason']=='fts5_unavailable'
    assert compact_context(original,explain=True)['diagnostics']==original['diagnostics']
    assert compact['debug_record_id']==original['debug_record_id']
    assert CliRunner().invoke(app,shlex.split(compact['task_detail_command'])[1:]).exit_code==0


def test_compact_cli_opt_in_and_stale_goal(task_kb):
    root,workspace=task_kb
    runner=CliRunner()
    regular=runner.invoke(app,['recall','report','--format','json'])
    assert regular.exit_code==0,regular.output
    assert json.loads(regular.output)['schema_version']=='recall-response/v1'
    compact=runner.invoke(app,['recall','report','--format','json','--compact'])
    assert compact.exit_code==0,compact.output
    assert json.loads(compact.output)['schema_version']=='recall-context/v1'
    assert runner.invoke(app,['recall','report','--compact']).exit_code==2
    tasks.select(root,workspace,'report')
    path=root/'profiles/goals/report.md'
    path.write_text(path.read_text(encoding='utf-8')+'Changed requirement.',encoding='utf-8')
    assert runner.invoke(app,['recall','report','--format','json','--compact']).exit_code==2
