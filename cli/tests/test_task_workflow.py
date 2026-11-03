"""A few chain-level guards for task→native output→learning→review."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knowledge_studio import store, tasks, task_workflow as flow
from knowledge_studio.cli import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    kb = tmp_path/'kb'; kb.mkdir()
    workspace = tmp_path/'project'; workspace.mkdir()
    monkeypatch.setenv('OKS_ROOT', str(kb))
    monkeypatch.setenv('OKS_TASK_HOME', str(tmp_path/'bindings'))
    monkeypatch.setenv('OKS_MACHINE_ID', 'workflow-test')
    monkeypatch.chdir(workspace)
    (kb/'profiles/goals').mkdir(parents=True)
    (kb/'profiles/goals/report.md').write_text('---\ntype: goal\ntitle: Brief\nstatus: active\n---\nWrite a source-backed brief.\n', encoding='utf-8')
    (kb/'settings').mkdir()
    (kb/'settings/task-workflow.json').write_text(json.dumps({'schema_version':'task-workflow/v1','enabled':True,'hosts':['claude']}), encoding='utf-8')
    tasks.start(kb, 'report', 'profiles/goals/report.md', [])
    tasks.select(kb, workspace, 'report')
    return kb, workspace


def native(workspace, event, **kw):
    return {'hook_event_name':event,'session_id':'real-host-id','cwd':str(workspace), **kw}


def write_and_return(kb, workspace, text='## 学习建议\n保留逐段引用，适用于需核对来源的简报。依据：result.md。'):
    before=set((kb/'.oks/workflow-runs').glob('*.json'))
    assert flow.observe(kb, native(workspace, 'SessionStart'), 'claude')['context']
    assert set((kb/'.oks/workflow-runs').glob('*.json'))==before
    result = workspace/'result.md'; result.write_text('Actual brief with citations.\n', encoding='utf-8')
    event = native(workspace, 'PostToolUse', tool_name='Write', tool_input={'file_path':str(result)}, tool_response={'filePath':str(result)}, tool_use_id='actual-write-id')
    observed = flow.observe(kb,event,'claude')
    assert observed['artifacts']
    final = native(workspace,'Stop', last_assistant_message=text)
    return final, flow.observe(kb,final,'claude')


def test_one_action_begin_and_native_output_learning_chain(setup):
    kb, workspace = setup
    invocation = CliRunner().invoke(app,['task','begin','next','--title','下一项','--goal','Write the next brief.','--path',str(kb)])
    assert invocation.exit_code == 0, invocation.output
    assert tasks.binding(kb,workspace)['task_id']=='next'
    start=native(workspace,'UserPromptSubmit',prompt='开始任务：入门说明\n目标已经确认，写出有来源的说明。')
    flow.observe(kb,start,'claude')
    selected=tasks.binding(kb,workspace)['task_id']
    assert selected!='next'
    flow.observe(kb,start,'claude')
    assert tasks.binding(kb,workspace)['task_id']==selected
    tasks.select(kb,workspace,'report')
    final, run = write_and_return(kb,workspace)
    assert run['phase']=='returned' and run['learning_status']=='pending_review'
    current = tasks.show(kb,'report')
    assert current['revision']==2 and current['lifecycle']=='active'
    assert len(current['artifacts'])==1 and current['artifacts'][0]['path'].startswith('outputs/')
    draft=kb/run['draft_path']; assert draft.is_file()
    content=draft.read_text(encoding='utf-8')
    assert 'human_approved: false' in content
    assert flow.draft_context(kb,content)['source_status']=='current'
    assert flow.observe(kb,final,'claude')['draft_path']==run['draft_path']
    assert tasks.show(kb,'report')['revision']==2
    assert not (kb/'wiki').exists()


def test_manual_progress_preserved_and_changed_evidence_blocks_review(setup):
    kb,workspace=setup
    tasks.checkpoint(kb,'report',1,'人工已核对范围','下一步由我指定',[])
    _,run=write_and_return(kb,workspace)
    task=tasks.show(kb,'report')
    assert task['progress']=='人工已核对范围' and task['next_action']=='下一步由我指定'
    ref=task['artifacts'][0]
    (kb/ref['path']).write_text('changed later',encoding='utf-8')
    with pytest.raises(ValueError,match='sources changed'):
        store.promote_draft(Path(run['draft_path']).stem)
    assert (kb/run['draft_path']).exists()


def test_private_scope_never_generates_shared_learning(setup):
    kb,workspace=setup
    tasks.select(kb,workspace,'report','private-subject','private-project')
    target=kb/'reports/private-output.md';target.parent.mkdir()
    target.write_text('Explicitly saved task output',encoding='utf-8')
    flow.observe(kb,native(workspace,'PostToolUse',tool_name='Write',tool_input={'file_path':str(target)}),'claude')
    run=flow.observe(kb,native(workspace,'Stop',last_assistant_message='## 学习建议\n仅此私人范围使用的建议。'),'claude')
    assert run['learning_status']=='private_scope'
    assert not list((kb/'drafts').glob('*.md'))
    assert 'private-subject' not in json.dumps(flow.overview(kb,'report'))


def test_goal_change_pauses_capture_without_accepting_new_sources(setup):
    kb,workspace=setup
    flow.observe(kb,native(workspace,'SessionStart'),'claude')
    (kb/'profiles/goals/report.md').write_text('---\ntype: goal\nstatus: active\n---\nNew requirement.\n',encoding='utf-8')
    run=flow.observe(kb,native(workspace,'Stop',last_assistant_message='## 学习建议\n不沿用过期目标。'),'claude')
    assert run['status']=='source_changed'
    assert tasks.show(kb,'report')['revision']==1
    assert not list((kb/'drafts').glob('*.md'))


def test_outside_workspace_and_credentials_not_archived(setup,tmp_path):
    kb,workspace=setup
    outside=tmp_path/'outside.md';outside.write_text('not part of this project',encoding='utf-8')
    secret=workspace/'result.txt';secret.write_text('Authorization: Bearer secret_token_123456789abcdef',encoding='utf-8')
    structured=workspace/'result.json';structured.write_text('{"PASSWORD":"hunter2","access_token":"abc"}',encoding='utf-8')
    (kb/'reports').mkdir()
    internal=kb/'reports/private.json';internal.write_text('{"PASSWORD":"hunter2"}',encoding='utf-8')
    internal_text=kb/'reports/private.md';internal_text.write_text(secret.read_text(encoding='utf-8'),encoding='utf-8')
    for target in (outside,secret,structured,internal,internal_text):
        run=flow.observe(kb,native(workspace,'PostToolUse',tool_name='Write',tool_input={'file_path':str(target)}),'claude')
        assert not run['artifacts']
        assert run['warning']
    assert not list((kb/'outputs').rglob('*'))


def test_fixture_promotion_not_resurrected_and_is_recallable(setup):
    # Mechanical approval fixture only; the real acceptance still needs a human.
    kb,workspace=setup
    final,run=write_and_return(kb,workspace)
    slug=store.promote_draft(Path(run['draft_path']).stem)
    page=store.get_wiki_page(slug)
    assert page['human_reviewed_at']
    assert flow.overview(kb,'report')['drafts'][0]['status']=='promoted'
    flow.observe(kb,final,'claude')
    assert (kb/run['draft_path']).exists()  # Retained evidence, excluded from pending.
    assert not store.list_drafts()


def test_archived_project_links_keep_the_original_source_without_changing_bytes(setup):
    from knowledge_studio import workspace as reader
    kb,project=setup
    (kb/'raw').mkdir();(kb/'raw/source.md').write_text('Original material',encoding='utf-8')
    output=project/'linked.md'
    output.write_text('[source](../kb/raw/source.md)\n[config](../kb/settings/task-workflow.json)\n[hidden](../kb/raw/.private/secret.md)',encoding='utf-8')
    flow.observe(kb,native(project,'PostToolUse',tool_name='Write',tool_input={'file_path':str(output)}),'claude')
    run=flow.observe(kb,native(project,'Stop',last_assistant_message='Done.'),'claude')
    relative=run['artifacts'][0]['path']
    assert (kb/relative).read_bytes()==output.read_bytes()
    links=reader.artifact_source_links(kb,relative,output.read_text(encoding='utf-8'))
    assert links=={'../kb/raw/source.md':'raw/source.md'}
    assert reader.artifact_source(kb,'report',relative,2,'raw/source.md')['text']=='Original material'
    with pytest.raises(ValueError):reader.artifact_source(kb,'report',relative,2,'settings/task-workflow.json')
    with pytest.raises(ValueError):reader.artifact_source(kb,'report',relative,2,'raw/.private/secret.md')


def test_rejected_learning_is_not_resurrected_by_a_different_return_event(setup):
    kb,project=setup
    final,run=write_and_return(kb,project)
    candidate=run['draft_path']
    store.reject_draft(Path(candidate).stem)
    assert flow.overview(kb,'report')['drafts'][0]['status']=='rejected'
    flow.observe(kb,{**final,'last_assistant_message':final['last_assistant_message']+'\n'},'claude')
    assert (kb/candidate).exists()
    assert not store.list_drafts()
    assert flow.overview(kb,'report')['drafts'][0]['status']=='rejected'


def test_review_preserves_exact_bytes_and_reopens_without_reapproving(setup):
    import hashlib
    from knowledge_studio import workspace as reader
    kb,project=setup
    _,run=write_and_return(kb,project)
    candidate=run['draft_path'];target=kb/candidate
    original=b'\xef\xbb\xbf'+target.read_bytes().replace(b'\n',b'\r\n')
    target.write_bytes(original)
    inspected=reader.draft(kb,candidate)
    slug=store.promote_draft(target.stem,expected_sha256=inspected['sha256'])
    page=store.get_wiki_page(slug)
    proof=page['reviewed_source']
    assert proof['sha256']==hashlib.sha256(original).hexdigest()
    assert (kb/proof['path']).read_bytes()==original
    assert page['workflow_source']['task_id']=='report'
    reopened=reader.draft(kb,candidate)
    assert reopened['review_status']=='promoted' and reopened['original_available']
    assert reopened['sha256']==inspected['sha256']
    with pytest.raises(ValueError,match='already reviewed'):
        store.promote_draft(target.stem,expected_sha256=reopened['sha256'])
    (kb/proof['path']).write_text('changed evidence',encoding='utf-8')
    assert reader.draft(kb,candidate)['original_available']
    assert reader.draft(kb,candidate)['snapshot_status']=='retained_original'


def test_related_proposals_group_but_approval_does_not_spread(setup):
    kb,project=setup
    final,run=write_and_return(kb,project)
    first=run['draft_path']
    second=flow.observe(kb,{**final,'last_assistant_message':'## 学习建议\n另一条需要单独审核的建议。'},'claude')['draft_path']
    store.promote_draft(Path(first).stem)
    overview=flow.overview(kb,'report')
    assert len(overview['learning_groups'])==1
    assert {item['status'] for item in overview['learning_groups'][0]['variants']}=={'draft','promoted'}
    assert (kb/second).exists()
    # A new edited file at an old candidate path does not inherit its approval.
    (kb/first).write_text((kb/second).read_text(encoding='utf-8')+'\nEdited revision',encoding='utf-8')
    from knowledge_studio import workspace as reader
    assert reader.draft(kb,first)['review_status']=='draft'
    assert next(item for item in flow.overview(kb,'report')['drafts'] if item['path']==first)['status']=='draft'


def test_new_session_same_lesson_and_output_never_inherits_old_approval(setup):
    kb,project=setup
    (kb/'reports').mkdir();output=kb/'reports/shared.md';output.write_text('Shared exact output',encoding='utf-8')
    lesson='## 学习建议\n相同内容仍须对每次新提案独立审核。'
    def propose(session):
        flow.observe(kb,{**native(project,'PostToolUse',tool_name='Write',tool_input={'file_path':str(output)}),'session_id':session},'claude')
        return flow.observe(kb,{**native(project,'Stop',last_assistant_message=lesson),'session_id':session},'claude')['draft_path']
    first=propose('session-one');store.promote_draft(Path(first).stem)
    second=propose('session-two')
    assert first!=second and (kb/second).exists()
    grouped=flow.overview(kb,'report')['learning_groups']
    assert len(grouped)==1 and sorted(item['status'] for item in grouped[0]['variants'])==['draft','promoted']
    first_review=flow.reviewed_candidate(kb,first)
    store.promote_draft(Path(second).stem)
    assert len(list((kb/'wiki').rglob('*.md')))==1
    assert flow.reviewed_candidate(kb,first)['sha256']==first_review['sha256']
    assert flow.reviewed_candidate(kb,second)['sha256']!=first_review['sha256']
    assert all(item['status']=='promoted' for item in flow.overview(kb,'report')['drafts'])


def test_workflow_review_keeps_concurrent_edits_and_uses_one_pending_projection(setup,monkeypatch):
    from knowledge_studio import mail_knowledge, workspace as reader
    kb,project=setup
    _,run=write_and_return(kb,project);candidate=run['draft_path'];path=kb/candidate
    original=path.read_bytes();inspected=reader.draft(kb,candidate)
    write=store.write_wiki_page
    def edit_after_wiki_write(**kwargs):
        result=write(**kwargs)
        path.write_bytes(original+b'\nConcurrent unreviewed change.\n')
        return result
    monkeypatch.setattr(store,'write_wiki_page',edit_after_wiki_write)
    slug=store.promote_draft(path.stem,expected_sha256=inspected['sha256'])
    assert b'Concurrent unreviewed' in path.read_bytes()
    assert 'Concurrent unreviewed' not in store.get_wiki_page(slug)['body']
    assert reader.draft(kb,candidate)['review_status']=='draft'
    assert len(store.list_drafts())==1
    assert mail_knowledge.knowledge_map(kb)['counts']['points']==2


def test_managed_task_learning_cannot_drop_its_source_marker_to_bypass_review(setup):
    import frontmatter
    kb,project=setup
    _,run=write_and_return(kb,project);path=kb/run['draft_path']
    doc=frontmatter.loads(path.read_text(encoding='utf-8'));del doc['workflow_source']
    path.write_text(frontmatter.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError,match='source markers missing'):store.promote_draft(path.stem)
    assert path.exists() and not list((kb/'wiki').rglob('*.md'))


def test_review_links_pin_exact_bytes_when_one_path_has_new_approved_content(setup):
    from knowledge_studio import workspace as reader,mail_web
    kb,project=setup
    _,run=write_and_return(kb,project);candidate=run['draft_path'];path=kb/candidate
    old=reader.draft(kb,candidate);old_slug=store.promote_draft(path.stem)
    path.write_bytes(path.read_bytes()+b'\nA newly reviewed addition.\n')
    new=reader.draft(kb,candidate);assert new['review_status']=='draft'
    new_slug=store.promote_draft(path.stem,expected_sha256=new['sha256'])
    assert new_slug!=old_slug
    assert reader.draft(kb,candidate)['review_status']=='promoted'
    assert 'newly reviewed addition' not in reader.draft(kb,candidate,old['sha256'])['text']
    assert 'newly reviewed addition' in reader.draft(kb,candidate,new['sha256'])['text']
    assert mail_web._memory_item(kb,candidate)['path'].endswith(new_slug+'.md')
    with pytest.raises(ValueError,match='revision unavailable'):reader.draft(kb,candidate,'0'*64)
