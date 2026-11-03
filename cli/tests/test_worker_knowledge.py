import json
import hashlib
from pathlib import Path

import pytest
import yaml

from knowledge_studio import mail_knowledge, store, worker_knowledge as fields


def write(root, relative, **meta):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\n'+yaml.safe_dump(meta, allow_unicode=True)+'---\n\n原始正文保持不变。\n', encoding='utf-8')
    return path


def point(data, path):
    return next(p for d in data['domains'] for c in d['clusters'] for p in c['points'] if p['path']==path)


def record(record_id='rec1', **values):
    return {'record_id': record_id, 'fields': values}


def snapshot(records, **overrides):
    return {'state':'live','source':{'base_token_hash':'0123456789ab','table_id':'tbl1'},'observed_at':'2026-10-19T00:00:00Z','records':records,**overrides}


def test_worker_domains_are_multi_valued_and_do_not_reclassify_files(tmp_path):
    file=write(tmp_path,'wiki/a.md',title='A',area='engineering',type='concept')
    before=file.read_bytes()
    snap=snapshot([record(**{'知识域':['computing','finance','unknown-domain'],'Wiki路径':'wiki/a.md','评级':'A','质量状态':'partial'})])
    data=mail_knowledge.knowledge_map(tmp_path,worker_snapshot=snap)
    item=point(data,'wiki/a.md')
    assert [d['id'] for d in item['knowledge_domains']]==['computing','finance']
    assert item['classification']['unmapped']==['unknown-domain']
    assert item['classification']['source']=='worker 知识域'
    assert item['worker_records'][0]['fields']['质量状态']=='partial'
    assert item['is_skill'] is False
    assert data['worker_source']['linked_records']==1
    assert file.read_bytes()==before


@pytest.mark.parametrize('kind', ['concept','strategy','anti-pattern'])
def test_governance_type_does_not_create_a_skill(tmp_path,kind):
    write(tmp_path,'drafts/a.md',title='A',draft_area='computing',draft_type=kind)
    data=mail_knowledge.knowledge_map(tmp_path)
    item=point(data,'drafts/a.md')
    assert not item['is_skill']
    assert item['skill']['state']=='none'
    assert data['governance']['pluggable']==[]
    assert sum(g['count'] for g in data['governance']['types'])==0
    write(tmp_path,'drafts/a.md',title='A',artifact_kind='skill',draft_area='skills',draft_type=kind)
    data=mail_knowledge.knowledge_map(tmp_path)
    assert point(data,'drafts/a.md')['is_skill']
    assert point(data,'drafts/a.md')['skill']['state']=='candidate'
    assert sum(g['count'] for g in data['governance']['types'])==1


def test_unknown_domains_missing_fields_and_unmatched_capture_remain_explicit(tmp_path):
    write(tmp_path,'wiki/a.md',title='Same title',area='ai')
    write(tmp_path,'wiki/b.md',title='B',area='computing')
    snap=snapshot([record(**{'总结':'Same title','Wiki路径':'../private.md','Wiki状态':'promoted','质量状态':'failed'})],partial=True)
    data=mail_knowledge.knowledge_map(tmp_path,worker_snapshot=snap)
    a=point(data,'wiki/a.md')
    assert a['knowledge_domains']==[{'id':'_unmapped','label':'待对齐知识域'}]
    assert a['worker_records']==[]
    assert a['classification']['raw_values']==['ai']
    assert point(data,'wiki/b.md')['classification']['source']=='本地 area（非飞书字段）'
    assert data['worker_source']['linked_records']==0
    assert data['worker_source']['partial']
    assert data['worker_source']['records'][0]['fields']['质量状态']=='failed'


def test_source_record_identity_is_scoped_and_not_title_matched(tmp_path):
    old={'source':{'base_token_hash':'aaaaaaaaaaaa','table_id':'tbl1','record_id':'rec1'},'fields':{'知识域':'science'},'observed_at':'2026-10-01'}
    write(tmp_path,'wiki/a.md',title='A',area='computing',worker_records=[old])
    data=mail_knowledge.knowledge_map(tmp_path,worker_snapshot=snapshot([record(**{'知识域':'finance','总结':'A'})]))
    item=point(data,'wiki/a.md')
    assert item['worker_records'][0]['fields']['知识域']=='science'
    assert data['worker_source']['linked_records']==0


def test_matching_identity_updates_snapshot_and_keeps_stale_state(tmp_path):
    source={'base_token_hash':'0123456789ab','table_id':'tbl1','record_id':'rec1'}
    write(tmp_path,'wiki/a.md',title='A',area='computing',worker_records=[{'source':source,'fields':{'评级':'B'},'observed_at':'2026-10-01'}])
    data=mail_knowledge.knowledge_map(tmp_path,worker_snapshot=snapshot([record(**{'评级':'A','知识域':'finance','Wiki状态':'review_pending'})],state='stale'))
    row=point(data,'wiki/a.md')['worker_records'][0]
    assert row['fields']['评级']=='A'
    assert row['state']=='stale'
    assert row['observed_at']=='2026-10-19T00:00:00Z'


def test_classification_version_without_review_timestamp_is_not_human_review(tmp_path):
    write(tmp_path, 'wiki/a.md', title='A', area='computing', classification_version=1,
          worker_records=[{'source': {'base_token_hash': '0123456789ab', 'table_id': 'tbl1', 'record_id': 'rec1'},
                           'fields': {'知识域': 'finance'}, 'observed_at': '2026-10-19'}])
    item = point(mail_knowledge.knowledge_map(tmp_path, worker_snapshot=snapshot([])), 'wiki/a.md')
    assert item['classification']['source'] == 'worker 知识域'
    assert item['knowledge_domains'] == [{'id': 'finance', 'label': mail_knowledge.DOMAIN_LABELS['finance']}]


def test_exact_run_sidecar_restores_intake_fields_without_changing_capture_contract(tmp_path):
    write(tmp_path,'wiki/a.md',title='A',area='engineering',traces=[{'kind':'execution','id':'run-one'}])
    run=tmp_path/'.oks/runs/run-one'
    run.mkdir(parents=True)
    source={'base_token_hash':'0123456789ab','table_id':'tbl1','record_id':'rec1'}
    (run/'capture-envelope.json').write_text(json.dumps({'source_record':source}),encoding='utf-8')
    (run/'intake-fields.json').write_text(json.dumps({'source':source,'fields':{'知识域':'science','思考':'独立思考'},'observed_at':'2026-10-01'}),encoding='utf-8')
    data=mail_knowledge.knowledge_map(tmp_path)
    assert point(data,'wiki/a.md')['knowledge_domains'][0]['id']=='science'
    assert point(data,'wiki/a.md')['worker_records'][0]['fields']['思考']=='独立思考'
    assert 'intake_fields' not in json.loads((run/'capture-envelope.json').read_text())


def test_projection_never_exposes_credentials_or_worker_leases():
    value=fields.clean_fields({'评级':'A','base_token':'SECRET','租约所有者':'PRIVATE','附件':[{'file_token':'TOKEN'}],'内容':[{'text':'原'},{'text':'文'}]})
    assert value=={'评级':'A','内容':'原文'}
    assert 'SECRET' not in json.dumps(value)
    source={'base_token_hash':'0123456789ab','table_id':'tbl1','record_id':'rec1','base_token':'SECRET'}
    result=fields.clean_records([{'source':source,'fields':{'评级':'A'},'observed_at':'now'}])
    assert 'SECRET' not in json.dumps(result)


def test_snapshot_merge_compares_instants_across_timezone_offsets():
    source={'base_token_hash':'abc','table_id':'tbl1','record_id':'rec1'}
    newer={'source':source,'observed_at':'2026-10-19T01:00:00Z','fields':{'评级':'A'}}
    older={'source':source,'observed_at':'2026-10-19T08:30:00+08:00','fields':{'评级':'B'}}
    assert fields.merge_records([newer],[older])[0]['fields']['评级']=='A'


def test_run_sidecar_cannot_substitute_another_source_record(tmp_path):
    write(tmp_path,'wiki/a.md',title='A',area='engineering',traces=[{'id':'run-one'}])
    run=tmp_path/'.oks/runs/run-one'
    run.mkdir(parents=True)
    source={'base_token_hash':'abc','table_id':'tbl1','record_id':'rec1'}
    (run/'capture-envelope.json').write_text(json.dumps({'source_record':source}),encoding='utf-8')
    (run/'intake-fields.json').write_text(json.dumps({'source':{**source,'record_id':'other'},'fields':{'知识域':'finance'}}),encoding='utf-8')
    data=mail_knowledge.knowledge_map(tmp_path)
    assert point(data,'wiki/a.md')['knowledge_domains'][0]['id']=='engineering'
    assert all(r['source']['record_id']=='rec1' for r in point(data,'wiki/a.md')['worker_records'])
    (run/'capture-envelope.json').write_text('[]',encoding='utf-8')
    assert point(mail_knowledge.knowledge_map(tmp_path),'wiki/a.md')['worker_records']==[]


def test_worker_records_survive_promotion_and_content_dedup(monkeypatch,tmp_path):
    monkeypatch.setenv('OKS_ROOT',str(tmp_path))
    source={'base_token_hash':'0123456789ab','table_id':'tbl1','record_id':'rec1'}
    first={'source':source,'observed_at':'2026-10-01','fields':{'知识域':'computing','评级':'A','质量状态':'partial'}}
    write(tmp_path,'drafts/a.md',title='A',draft_area='computing',draft_type='concept',worker_records=[first])
    slug=store.promote_draft('a')
    page=store.get_wiki_page(slug)
    assert page['worker_records'][0]['fields']['质量状态']=='partial'
    second={'source':source,'observed_at':'2026-10-02','fields':{'审核动作':'accept','质量状态':'failed'}}
    candidate=write(tmp_path,'drafts/b.md',title='B',draft_area='computing',draft_type='concept',worker_records=[second])
    original=candidate.read_bytes()
    repeated=store.promote_draft('b')
    assert repeated==slug
    row=store.get_wiki_page(slug)['worker_records'][0]
    assert row['fields']=={'知识域':'computing','评级':'A','质量状态':'failed','审核动作':'accept'}
    assert candidate.read_bytes()==original
    from knowledge_studio import draft_review
    proof=draft_review.read_receipt(tmp_path,'b',hashlib.sha256(original).hexdigest())
    assert proof['decision']=='promoted' and draft_review.read_original(tmp_path,proof)==original
