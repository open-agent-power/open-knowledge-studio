"""A dataset is inert data; benchmark jobs cannot write personal Wiki."""
import json
from pathlib import Path
import time
import pytest
import yaml
from knowledge_studio import studio_evaluation as ev, store, handoff


@pytest.fixture
def root(tmp_path):
    root=tmp_path/'kb'
    (root/'wiki').mkdir(parents=True)
    (root/'mail').mkdir()
    (root/'wiki/personal.md').write_text('# Personal knowledge\nMust stay unchanged')
    return root


def bundle():
    return {'dataset':{'schema_version':'recall-case/v1','dataset_id':'custom','version':'1',
        'cases':[{'case_id':'one','query':'quartz zebra evidence','relevant':['evidence']}]},
        'corpus':{'evidence':'---\ntitle: Quartz evidence\ntype: concept\narea: test\nstatus: active\n---\n# Quartz zebra evidence\nquartz zebra evidence'}}


def test_import_validates_data_and_never_executes_or_writes_wiki(root):
    before=(root/'wiki/personal.md').read_bytes()
    imported=ev.import_dataset(root,{'filename':'custom.yaml','text':yaml.safe_dump(bundle())})
    item=ev.dataset(root,imported['id'])
    assert ev.coverage(root,item)['missing_count']==0
    assert (root/'wiki/personal.md').read_bytes()==before
    assert not (root/'wiki/evidence.md').exists()
    bad=bundle();bad['corpus']={'../../escape':'bad'}
    with pytest.raises(ValueError,match='slug'):
        ev.import_dataset(root,{'filename':'bad.yaml','text':yaml.safe_dump(bad)})
    with pytest.raises(ValueError,match='aliases'):
        ev.import_dataset(root,{'filename':'bad.yaml','text':'a: &a [1]\nb: *a'})
    with pytest.raises(ValueError):ev.start(root,{'dataset':item['id'],'method':'python evil.py'})


def test_background_run_persists_real_cases_and_preserves_personal_wiki(root):
    imported=ev.import_dataset(root,{'filename':'custom.json','text':json.dumps(bundle())})
    before=(root/'wiki/personal.md').read_bytes()
    job=ev.start(root,{'dataset':imported['id'],'method':'fts5'})
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        state=ev.read(root,'jobs/'+job['id']+'.json')
        if state['status'] in {'completed','failed'}:break
        time.sleep(.1)
    assert state['status']=='completed',state
    result=ev.run(root,job['id'])
    assert result['metrics']['case_count']==1
    assert result['metrics']['recall_at_1']==1
    assert result['cases'][0]['retrieved']==['evidence']
    assert result['manifest']['kb_snapshot_before']==result['manifest']['kb_snapshot_after']
    assert (root/'wiki/personal.md').read_bytes()==before
    assert ev.catalog(root)['runs'][0]['id']==job['id']


def test_missing_gold_and_symlinks_cannot_launch_a_meaningless_or_outside_run(root,tmp_path):
    data=bundle()['dataset']
    imported=ev.import_dataset(root,{'filename':'missing.yaml','text':yaml.safe_dump(data)})
    with pytest.raises(ValueError,match='Missing 1'):
        ev.start(root,{'dataset':imported['id'],'method':'fts5'})
    with pytest.raises(ValueError):ev.run(root,'../secret')
    outside=tmp_path/'outside';outside.mkdir()
    (root/'records/evaluation/runs').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):ev.run(root,'outside')


def test_date_archived_goals_remain_available_to_recall_and_handoffs(root,monkeypatch):
    target=root/'goal/2026/11/04/work.md';target.parent.mkdir(parents=True)
    target.write_text('---\ntitle: Work\ntype: goal\nstatus: active\nkeywords: [quartz]\n---\n# Work')
    monkeypatch.setattr(store,'repo_root',lambda:root)
    assert store.load_active_goals()[0]['slug']=='work'
    assert handoff._read(root,'goal/2026/11/04/work.md','profiles/goals')==target.read_bytes()
    with pytest.raises(ValueError):handoff._relative('goal/../../outside.md','profiles/goals')


def test_http_upload_accepts_large_datasets_but_requires_instance_and_origin(root):
    from knowledge_studio.mail_web import create_server
    from threading import Thread
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    server=create_server(root,0,local_edit=True)
    worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    data=bundle()['dataset'];data['cases']=[{'case_id':f'case-{i}','query':'query '*40,'relevant':['evidence']} for i in range(400)]
    payload=json.dumps({'filename':'large.yaml','text':yaml.safe_dump(data),'expected_knowledge_base':str(root)})
    assert len(payload)>65536
    def post(headers):
        return urlopen(Request(origin+'/api/evaluation/import',data=payload.encode(),headers={'Content-Type':'application/json',**headers}),timeout=10)
    try:
        with pytest.raises(HTTPError) as exc:post({})
        assert exc.value.code==403
        with post({'Origin':origin}) as response:
            assert json.load(response)['status']=='imported'
        with urlopen(origin+'/api/evaluation/catalog') as response:
            assert json.load(response)['datasets'][0]['case_count']==400
    finally:
        server.shutdown();server.server_close();worker.join(timeout=5)


def test_reject_incomplete_upload_does_not_block_server(root):
    import socket
    from threading import Thread
    from urllib.request import urlopen
    from knowledge_studio.mail_web import create_server

    server = create_server(root, 0, local_edit=True)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                (f"POST /api/evaluation/import HTTP/1.1\r\n"
                 f"Host: 127.0.0.1:{server.server_port}\r\n"
                 "Content-Type: application/json\r\n"
                 "Content-Length: 100000\r\n\r\n").encode() + b"{}"
            )
            assert b" 403 " in client.recv(4096)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/evaluation/catalog", timeout=3) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
