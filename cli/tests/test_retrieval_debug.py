"""Explicit query/read/use/output links, with no inferred execution claim."""
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner
from knowledge_studio import skills, store, tasks, retrieval_debug as debug
from knowledge_studio.cli import app


@pytest.fixture
def linked(tmp_path, monkeypatch):
    root=tmp_path/'kb'; (root/'wiki').mkdir(parents=True); (root/'drafts').mkdir()
    (root/'profiles/goals').mkdir(parents=True)
    (root/'profiles/goals/report.md').write_text('---\ntype: goal\ntitle: report\nstatus: active\n---\nCite sources.',encoding='utf-8')
    monkeypatch.setenv('OKS_ROOT',str(root));monkeypatch.setenv('OKS_TASK_HOME',str(tmp_path/'bindings'))
    source=tmp_path/'source';source.mkdir();(source/'SKILL.md').write_text('---\nname: report\ndescription: report evidence\n---\nRead sources and cite.',encoding='utf-8')
    imported=skills.import_skill(source)
    slug=store.promote_draft(imported['entry']['slug'])  # Synthetic fixture review, not a human acceptance claim.
    page=store.get_wiki_page(slug);hit=debug.asset_context(root,page)|{'slug':slug,'title':'Report'}
    task=tasks.start(root,'report','profiles/goals/report.md',[])
    context=debug.agreement_context(root,task['agreement'],'report')
    identifier=debug.record(root,'report',{'task':context},[hit])
    (root/'report.md').write_text('Actual output bytes',encoding='utf-8')
    return root,hit,identifier


def load(hit,identifier):
    result=CliRunner().invoke(app,['skills','load','report','--version',hit['skill_version'],'--retrieval-id',identifier])
    assert result.exit_code==0,result.output
    return json.loads(result.output)


def test_link_requires_actual_load_then_keeps_caller_reported_and_hashes(linked):
    root,hit,identifier=linked
    before=(root/'.oks/tasks/report.json').read_bytes()
    with pytest.raises(ValueError,match='Load this Skill'):
        tasks.checkpoint(root,'report',1,'Read','Review',['report.md'],retrieval_id=identifier,used_sources=[hit['source_path']])
    assert (root/'.oks/tasks/report.json').read_bytes()==before
    loaded=load(hit,identifier)
    assert loaded['executed'] is False and loaded['load_receipt']['host_consumed']=='unknown'
    result=tasks.checkpoint(root,'report',1,'Read','Review',['report.md'],retrieval_id=identifier,used_sources=[hit['source_path']])
    use=result['uses'][0]
    assert use['verification']=='caller_reported' and use['execution_verified'] is False
    assert use['artifacts'][0]['sha256']==hashlib.sha256(b'Actual output bytes').hexdigest()
    record=debug.overview(root)['records'][0]
    assert record['executed'] is False and record['usage'][0]['artifacts'][0]['status']=='unchanged'
    (root/'report.md').write_text('changed',encoding='utf-8')
    assert debug.overview(root)['records'][0]['usage'][0]['artifacts'][0]['status']=='changed'
    tasks.checkpoint(root,'report',2,'Other','Review',[])
    assert debug.overview(root)['records'][0]['usage'][0]['revision']==2


def test_wrong_query_scope_source_or_missing_artifact_cannot_link(linked):
    root,hit,identifier=linked
    load(hit,identifier)
    with pytest.raises(ValueError,match='not returned'):
        debug.source_hit(root,identifier,'wiki/other.md')
    wrong=debug.record(root,'report',{'task':None},[hit])
    with pytest.raises(ValueError,match='not bound'):
        tasks.checkpoint(root,'report',1,'Read','Review',['report.md'],retrieval_id=wrong,used_sources=[hit['source_path']])
    with pytest.raises(ValueError,match='artifact'):
        tasks.checkpoint(root,'report',1,'Read','Review',[],retrieval_id=identifier,used_sources=[hit['source_path']])
    with pytest.raises(ValueError,match='both'):
        tasks.checkpoint(root,'report',1,'Read','Review',['report.md'],retrieval_id=identifier)
    with pytest.raises(ValueError,match='expired'):
        debug.query_record(root,'unknown')


def test_changed_source_rejects_read_and_report_without_mutation(linked):
    root,hit,identifier=linked
    load(hit,identifier)
    path=root/hit['source_path'];path.write_text(path.read_text(encoding='utf-8')+'\nChanged.',encoding='utf-8')
    before=(root/'.oks/tasks/report.json').read_bytes()
    result=CliRunner().invoke(app,['skills','load','report','--retrieval-id',identifier])
    assert result.exit_code==2 and 'changed' in result.output
    with pytest.raises(ValueError,match='changed'):
        tasks.checkpoint(root,'report',1,'Read','Review',['report.md'],retrieval_id=identifier,used_sources=[hit['source_path']])
    assert (root/'.oks/tasks/report.json').read_bytes()==before


def test_cli_checkpoint_and_skill_search_return_explicit_record_ids(linked):
    root,hit,identifier=linked
    found=skills.search('report evidence',debug_record=True)
    assert found and found[0]['debug_record_id'] in found[0]['load_command']
    load(hit,identifier)
    result=CliRunner().invoke(app,['task','checkpoint','report','--revision','1','--progress','Read','--next','Review',
        '--artifact','report.md','--retrieval-id',identifier,'--used-source',hit['source_path']])
    assert result.exit_code==0,result.output
    assert json.loads(result.output)['uses'][0]['source_path']==hit['source_path']


def test_overview_projects_native_reads_without_changing_legacy_query_records(linked):
    root,hit,identifier=linked
    legacy=debug.record(root,'unlinked',{'task':None},[hit])
    task_record=debug.record(root,'linked',{'task':{'scope':'report'}},[hit])
    run_dir=root/'.oks/workflow-runs';run_dir.mkdir(parents=True)
    read={'event_id':'a'*64,'task_id':'report','run_id':'claude-'+'b'*40,'host':'claude',
          'revision':1,'source_path':'wiki/example.md','source_sha256':'c'*64,
          'title':'Example','observed_at':'2026-10-29T01:02:03+00:00'}
    (run_dir/'public.json').write_text(json.dumps({'schema_version':'task-native-run/v1','run_id':read['run_id'],
        'host':'claude','task_id':'report','native_reads':[read]}),encoding='utf-8')
    (run_dir/'private.json').write_text(json.dumps({'schema_version':'task-native-run/v1','run_id':'claude-'+'d'*40,
        'host':'claude','task_id':'report','private_scope':True,'native_reads':[dict(read,event_id='e'*64)]}),encoding='utf-8')
    result=debug.overview(root,task_id='report')
    assert result['knowledge_base']==str(root.resolve()) and result['task_filter']=='report'
    assert [item['event_id'] for item in result['native_reads']]==['a'*64]
    assert {item['id'] for item in result['records']}=={task_record,identifier}
    assert legacy not in {item['id'] for item in result['records']}
    assert result['records'][0]['hits'][0]['source_path']==hit['source_path']
    # Tool IDs are local to a native session. Another run can reuse the ID.
    another=dict(read,run_id='claude-'+'f'*40)
    (run_dir/'another-public.json').write_text(json.dumps({'run_id':another['run_id'],
        'host':'claude','task_id':'report','native_reads':[another]}),encoding='utf-8')
    reads=debug.overview(root,task_id='report')['native_reads']
    assert len(reads)==2 and {item['run_id'] for item in reads}=={read['run_id'],another['run_id']}


def test_native_use_requires_current_cited_output_and_excludes_private_runs(linked):
    root,hit,identifier=linked
    source=root/'wiki/source.md'
    source.write_text('---\ntype: concept\ntitle: Source\nstatus: active\n---\nReviewed source.\n',encoding='utf-8')
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    run_id='claude-'+'a'*40
    out_rel=f'outputs/{run_id}/result.md'
    output=root/out_rel;output.parent.mkdir(parents=True)
    output.write_text('[Source](/wiki/source.md)\n',encoding='utf-8')
    artifact=tasks._artifact(root,out_rel)
    run_dir=root/'.oks/workflow-runs';run_dir.mkdir(parents=True,exist_ok=True)
    read={'event_id':'b'*64,'task_id':'report','run_id':run_id,'host':'claude','revision':1,
          'source_path':'wiki/source.md','source_sha256':source_sha,'title':'Source','observed_at':'2026-10-29T01:02:03+00:00'}
    run_path=run_dir/f'{run_id}.json'
    run={'schema_version':'task-native-run/v1','run_id':run_id,'host':'claude','task_id':'report',
         'workspace':str(root),'phase':'returned','status':'returned','private_scope':False,
         'artifacts':[artifact],'native_reads':[read]}
    run_path.write_text(json.dumps(run),encoding='utf-8')
    captured=tasks.capture_outputs(root,'report',tasks.show(root,'report')['agreement']['sha256'],
        'native-output',[artifact],host='claude',run_id=run_id)
    run['task_revision']=captured['revision'];run_path.write_text(json.dumps(run),encoding='utf-8')
    private=dict(run,run_id='claude-'+'c'*40,private_scope=True,
        native_reads=[dict(read,event_id='d'*64,run_id='claude-'+'c'*40)])
    private['artifacts']=[]
    (run_dir/f"{private['run_id']}.json").write_text(json.dumps(private),encoding='utf-8')

    uses=debug.overview(root,task_id='report')['native_uses']
    assert len(uses)==1 and len(uses[0]['event_id'])==64
    assert [{**use,'event_id':None} for use in uses]==[{'event_id':None,'task_id':'report','revision':captured['revision'],
        'source_path':'wiki/source.md','source_sha256':source_sha,'title':'Source',
        'artifact':artifact,'verification':'output_citation'}]
    # A later public continuation can cite a source read earlier in this task.
    newer=dict(run,run_id='claude-'+'e'*40,native_reads=[])
    new_rel=f"outputs/{newer['run_id']}/result.md";new_path=root/new_rel;new_path.parent.mkdir(parents=True)
    new_path.write_text('[Source](/wiki/source.md)\nA corrected continuation.\n',encoding='utf-8')
    new_ref=tasks._artifact(root,new_rel);newer['artifacts']=[new_ref]
    new_run_path=run_dir/f"{newer['run_id']}.json";new_run_path.write_text(json.dumps(newer),encoding='utf-8')
    new_capture=tasks.capture_outputs(root,'report',tasks.show(root,'report')['agreement']['sha256'],
        'native-continuation',[new_ref],host='claude',run_id=newer['run_id'])
    newer['task_revision']=new_capture['revision'];new_run_path.write_text(json.dumps(newer),encoding='utf-8')
    uses=debug.overview(root,task_id='report')['native_uses']
    assert len(uses)==1 and uses[0]['artifact']==new_ref
    source.write_text(source.read_text(encoding='utf-8')+'Changed.\n',encoding='utf-8')
    assert debug.overview(root,task_id='report')['native_uses']==[]
    source.write_text('---\ntype: concept\ntitle: Source\nstatus: active\n---\nReviewed source.\n',encoding='utf-8')
    new_path.write_text('No citation now.\n',encoding='utf-8')
    assert debug.overview(root,task_id='report')['native_uses']==[]
