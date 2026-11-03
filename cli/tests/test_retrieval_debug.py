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
