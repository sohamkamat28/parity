"""v2 integration contracts on fresh databases, independent of network and models."""
import asyncio
import copy
import hashlib
import json
import os
import sys
import time
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from parity import config
from parity.db import DB, meta, versions, pages, chat_conversations, chat_messages
from parity.embedding import Embedder
from parity.fetch import Response
from parity.jobs import Jobs
from parity.job_schema import index_state
from parity.monitoring import MonitorService
from parity.monitor_schema import monitor_observations, monitor_events, monitor_field_states
from parity.service import Service
from parity.structured import extract_field
from parity.transfer import backup_database, restore_database, verify_backup, migrate_sqlite
from parity.v2_api import create_router, event_batch
from test_monitoring import HTML, URL, FixtureFetcher


@pytest.fixture
def system(database_url, tmp_path, monkeypatch):
    data=tmp_path/'captures';data.mkdir()
    monkeypatch.setattr(config,'DATA',data)
    service=Service(DB(database_url),fetcher=FixtureFetcher(),inline_index=False)
    yield service,MonitorService(service)
    service.db.engine.dispose()


def activate(m, names=('Current Price','Quarterly results','Announcements')):
    draft=m.preview({'root_url':URL,'instructions':'Track price revenue announcements','use_ai':False})
    preferred={'Quarterly results':'table','Announcements':'list'}
    fields=[next(f for f in draft['candidates'] if f['name']==name and (name not in preferred or f['type']==preferred[name])) for name in names]
    assert len(fields)==len(names)
    return m.activate({'draft_id':draft['draft_id'],'fields':fields})


def test_api_history_comparisons_totals_and_scope(system):
    service,m=system
    activated=activate(m)
    app=FastAPI();app.include_router(create_router(service,None))
    @app.exception_handler(ValueError)
    async def bad_request(request:Request,error):return JSONResponse({'detail':str(error)},400)
    with TestClient(app) as client:
        source=activated['source']
        assert source['config']['scope_mode']=='page'
        assert (source['config']['interval'],source['config']['max_pages'],source['config']['max_depth'])==(900,1,0)
        service.run(activated['run']['id'])
        changed=HTML.replace('Rs. 1,200.50','Rs. 1,250').replace('<td>1,200</td>','<td>1,400</td>')
        m.process_capture(source,'changed',Response(URL,200,{},changed.encode()))
        dashboard=client.get('/api/dashboard').json()
        table=next(f for f in dashboard['widgets'] if f['type']=='table')
        assert table['change']['cells'][0]['period']=='Jun 2026'
        price=next(f for f in dashboard['widgets'] if f['name']=='Current Price')
        assert price['value']=='1250' and price['previous_value']=='1200.5'
        assert dashboard['sources'][0]['root_url']==URL
        assert dashboard['totals']=={'monitors':1,'fields':3,'attention':0}
        response=client.get('/api/monitor-changes?limit=1').json()
        assert response['total']>=5 and response['next_cursor'] and response['items'][0]['capture_id']
        next_page=client.get('/api/monitor-changes',params={'limit':1,'cursor':response['next_cursor']}).json()
        assert next_page['items'][0]['id']!=response['items'][0]['id']
        assert client.get('/api/monitors?limit=1').json()['total']==1
        # More than one dashboard page must not change the database aggregates.
        activate(m,('Promoter holding',))
        small=client.get('/api/dashboard?limit=1').json()
        assert len(small['monitors'])==1 and small['next_cursor']
        assert small['totals']['monitors']==2 and small['totals']['fields']==4
        with service.db.tx() as c:c.execute(monitor_field_states.update().values(last_verified_at=time.time()-10000))
        stale=client.get('/api/dashboard?limit=1').json()
        assert stale['totals']['attention']==4 and stale['attention']
        assert client.get('/api/dashboard?cursor='+small['next_cursor']).json()['totals']['fields']==4


def test_frozen_rules_interruption_and_no_duplicate_observations(system,monkeypatch):
    service,m=system;activated=activate(m,('Current Price',))
    original=service._publish
    def crash(*args,**kwargs):raise KeyboardInterrupt('capture process stopped after structured commit')
    monkeypatch.setattr(service,'_publish',crash)
    with pytest.raises(KeyboardInterrupt):Jobs(service).capture_once(activated['run']['id'])
    count=service.db.one(select(func.count().label('n')).select_from(monitor_observations))['n']
    from test_jobs import expire_claim
    expire_claim(service);monkeypatch.setattr(service,'_publish',original)
    assert Jobs(service).capture_once(activated['run']['id'])['status']=='succeeded'
    assert service.db.one(select(func.count().label('n')).select_from(monitor_observations))['n']==count
    assert len(service.db.all(select(versions)))==1


def test_table_fingerprints_latest_first_units_and_ambiguity():
    field={'name':'Results','type':'table','rule':{'kind':'table','selector':'#quarterly'}}
    initial=extract_field(HTML,field,URL)
    formatted=HTML.replace('<td>1,200</td>','<td>1200.0</td>').replace('Company','Company updated')
    assert extract_field(formatted,field,URL)['fingerprint']==initial['fingerprint']
    cell={'name':'Revenue','type':'number','rule':{'kind':'table_cell','selector':'#quarterly','row':'Revenue','period_mode':'latest','latest_position':'first'}}
    assert extract_field(HTML,cell,URL)['period']=='Mar 2026'
    with pytest.raises(ValueError,match='row labels'):
        extract_field(HTML.replace('Net Profit','Revenue'),field,URL)
    custom={'name':'Output','type':'number','rule':{'kind':'scalar','selector':'span','unit':'widgets'}}
    assert extract_field('<span>0 widgets</span>',custom,URL)['value']=='0'


def test_server_comparisons_use_immutable_comparable_operands(system):
    service,m=system;activated=activate(m,('Current Price',))
    m.process_capture(activated['source'],'changed',Response(URL,200,{},HTML.replace('Rs. 1,200.50','Rs. 1,250').encode()))
    from parity.monitor_evidence import retrieve
    result=retrieve(service,'Compare Current Price change')[0]
    assert 'difference: 49.5 INR' in result['text']
    assert 'Percentage change: 4.1233%' in result['text']
    previous=result['supporting_captures'][0]
    assert previous['value']=='1200.5' and previous['capture_id']!=result['capture_id']
    assert '1,200.50' in m.evidence(previous['capture_id'])['text']
    # Zero is a valid operand; percentage division by zero has no invented result.
    m.process_capture(activated['source'],'zero',Response(URL,200,{},HTML.replace('Rs. 1,200.50','Rs. 0').encode()))
    m.process_capture(activated['source'],'from-zero',Response(URL,200,{},HTML.replace('Rs. 1,200.50','Rs. 10').encode()))
    assert 'undefined because the previous value is zero' in retrieve(service,'Current Price change')[0]['text']


def test_sse_committed_watermark_and_reconnect_gaps(system):
    service,m=system;activate(m,('Current Price',))
    watermark,rows=event_batch(service.db,0)
    assert rows and all(r['id'] for r in rows)
    latest=rows[-1]['id']
    assert event_batch(service.db,latest)==(latest,[])
    assert event_batch(service.db,latest+100)==(latest,None)
    with service.db.tx() as c:
        c.execute(monitor_events.insert(),[{'kind':'monitor_updated','at':time.time(),'detail':{}} for _ in range(205)])
    assert event_batch(service.db,latest)[1] is None


def test_index_projection_rebuild_and_pending_versions(system):
    service,m=system;activated=activate(m,('Current Price',));service.embedder=Embedder('lexical')
    service.run(activated['run']['id']);Jobs(service).index_once()
    assert service.search('Company')['results']
    v=service.db.one(select(versions))
    # Reindex the same version with another signature; projection FKs must survive.
    service.embedder.signature+=':rebuild'
    assert service.index_version(v['id'])['chunks']>0
    assert service.search('Company')['results']
    before=time.time()
    service.fetcher.body=HTML.replace('Rs. 1,200.50','Rs. 1,250')
    service.run(service.enqueue(activated['source']['id'])['id'])
    current=service.search('Company')
    assert not current['results'] and current['index_pending']==1
    assert current['message']=='Search index updating'
    past=service.search('Company',mode='as_of',as_of=before)
    assert past['results'] and all(r['version_id']==v['id'] for r in past['results'])
    assert Jobs(service).index_once()['chunks']>0
    assert all(r['version_id']!=v['id'] for r in service.search('Company')['results'])


def populate(service,m):
    activated=activate(m,('Current Price',));service.embedder=Embedder('lexical')
    service.run(activated['run']['id']);Jobs(service).index_once()
    m.process_capture(activated['source'],'revision',Response(URL,200,{},HTML.replace('Rs. 1,200.50','Rs. 1,250').encode()))
    from parity.monitor_evidence import retrieve
    citation=retrieve(service,'Current Price')[0]
    with service.db.tx() as c:
        c.execute(chat_conversations.insert().values(id='conversation',title='Saved investigation',created_at=1,updated_at=2))
        c.execute(chat_messages.insert().values(id='answer',conversation_id='conversation',ordinal=1,role='assistant',content=citation['text'],citations=[citation],warnings=[],evidence=[citation],context={'mode':'current'},status='answered',created_at=2))
    return activated


def test_populated_backup_restore_hashes_and_evidence(system,tmp_path):
    service,m=system;populate(service,m)
    archive=tmp_path/'saved.zip';backup_database(service.db.engine.url,config.DATA,archive)
    manifest=verify_backup(archive)
    target='sqlite:///'+str(tmp_path/'restored.sqlite')
    result=restore_database(archive,target,tmp_path/'restored-data')
    assert result['verified']
    copied=tmp_path/'copied.zip';backup_database(target,tmp_path/'restored-data',copied)
    after=verify_backup(copied)
    for name in ('versions','chunks','monitor_observations','monitor_changes','chat_messages','search_projection'):
        assert manifest['tables'][name]==after['tables'][name]
    assert manifest['files']==after['files'] and len(manifest['files'])>=2
    with pytest.raises(ValueError,match='empty'):
        restore_database(archive,target,tmp_path/'restored-data')


def test_sqlite_to_postgres_migration_populated(system,tmp_path,monkeypatch):
    target,_=system
    if target.db.engine.dialect.name!='postgresql':pytest.skip('PostgreSQL migration requires PARITY_TEST_DATABASE_URL')
    original_data=tmp_path/'original';original_data.mkdir();monkeypatch.setattr(config,'DATA',original_data)
    original_file=original_data/'parity.db'
    original=Service(DB('sqlite:///'+str(original_file)),fetcher=FixtureFetcher(),inline_index=False)
    populate(original,MonitorService(original));original.db.engine.dispose()
    before=hashlib.sha256(original_file.read_bytes()).hexdigest()
    result=migrate_sqlite(original_data,target.db.engine.url.render_as_string(hide_password=False),tmp_path/'migrated',tmp_path/'before.zip')
    assert result['original_preserved'] and result['restore']['verified']
    assert hashlib.sha256(original_file.read_bytes()).hexdigest()==before
    after=tmp_path/'pg.zip';backup_database(target.db.engine.url,tmp_path/'migrated',after)
    source=verify_backup(tmp_path/'before.zip');copied=verify_backup(after)
    for name in ('sources','versions','chunks','monitor_observations','monitor_changes','chat_messages','search_projection'):
        assert source['tables'][name]==copied['tables'][name]
    assert source['files']==copied['files']


def test_all_five_actual_mcp_contracts(system,monkeypatch):
    service,m=system;activated=populate(service,m)
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    page=service.db.one(select(pages))
    env={**os.environ,'DATABASE_URL':service.db.engine.url.render_as_string(hide_password=False),'PARITY_DATA_DIR':str(config.DATA),'PARITY_EMBEDDER':'lexical','PARITY_OFFLINE':'1'}
    env.pop('PARITY_MCP_API_URL',None);env.pop('PARITY_EMBEDDING_URL',None)
    async def verify():
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','parity.mcp_server'],env=env)) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                calls=[('search_docs',{'query':'Company','source_ids':[activated['source']['id']]}),('get_page',{'page_id':page['id'],'version':1}),('get_page_history',{'page_id':page['id']}),('diff_versions',{'page_id':page['id'],'v1':1,'v2':1}),('list_recent_changes',{'limit':10})]
                assert {t.name for t in (await client.list_tools()).tools}=={name for name,_ in calls}
                for name,params in calls:
                    response=await client.call_tool(name,params)
                    assert not response.isError,(name,response)
                    assert response.content
    asyncio.run(verify())


def test_real_capture_process_termination_and_recovery(system,tmp_path):
    import subprocess
    service,m=system;activated=activate(m,('Current Price',))
    html_path=tmp_path/'fixture.html';html_path.write_text(HTML)
    code='''
import os
from pathlib import Path
from parity.db import DB
from parity.service import Service
from parity.jobs import Jobs
from parity.fetch import Response
class Fetcher:
    demo_origin='http://127.0.0.1:8080'
    def get(self,url,source,headers=None):return Response(url,200,{'content-type':'text/html'},Path(os.environ['FIXTURE_PATH']).read_bytes())
service=Service(DB(),fetcher=Fetcher(),inline_index=False)
jobs=Jobs(service)
original=jobs._store_response
def terminate(claim,response):
    original(claim,response)
    os._exit(99)
jobs._store_response=terminate
jobs.capture_once(os.environ['RUN_ID'])
'''
    env={**os.environ,'DATABASE_URL':service.db.engine.url.render_as_string(hide_password=False),'PARITY_DATA_DIR':str(config.DATA),'RUN_ID':activated['run']['id'],'FIXTURE_PATH':str(html_path)}
    stopped=subprocess.run([sys.executable,'-c',code],env=env,timeout=20,capture_output=True)
    assert stopped.returncode==99,stopped.stderr.decode()[-500:]
    from test_jobs import expire_claim
    expire_claim(service);service.fetcher.body=HTML.replace('Rs. 1,200.50','Rs. 999')
    assert Jobs(service).capture_once(activated['run']['id'])['status']=='succeeded'
    assert Jobs(service).capture_once(activated['run']['id']) is None
    assert len(service.db.all(select(versions)))==1
    assert len(service.db.all(select(monitor_observations)))==2
    assert m.dashboard()['widgets'][0]['value']=='1200.5'
    from parity.db import observations
    assert len(service.db.all(select(observations)))==1


def test_v1_vector_history_migrates_without_changing_original(system,tmp_path):
    target,_=system
    if target.db.engine.dialect.name!='postgresql':pytest.skip('Legacy PostgreSQL migration requires PARITY_TEST_DATABASE_URL')
    from sqlalchemy import create_engine
    from parity.db import _V2_TABLES,_V3_TABLES,schema,sources,cache,chunks,intervals
    data=tmp_path/'legacy';(data/'artifacts').mkdir(parents=True)
    body=b'<html><h1>Legacy capacity</h1><p>Capacity is 10 MW.</p></html>'
    raw=hashlib.sha256(body).hexdigest();(data/'artifacts'/raw).write_bytes(body)
    path=data/'parity.db';engine=create_engine('sqlite:///'+str(path));model=Embedder('lexical')
    excluded={t.name for t in (*_V2_TABLES,*_V3_TABLES)}
    meta.create_all(engine,tables=[t for t in meta.sorted_tables if t.name not in excluded])
    with engine.begin() as c:
        c.execute(schema.insert().values(number=1))
        c.execute(sources.insert().values(id='legacy-source',name='Legacy',root_url='https://legacy.example/',config={'interval':900},enabled=True))
        c.execute(pages.insert().values(id='legacy-page',source_id='legacy-source',url='https://legacy.example/',title='Legacy capacity',current_id='legacy-v1',last_version_id='legacy-v1',availability='active',health='healthy',verified_at=10))
        c.execute(versions.insert().values(id='legacy-v1',page_id='legacy-page',number=1,title='Legacy capacity',content='Capacity is 10 MW.',hash=raw,raw_hash=raw,raw_key=raw,observed_at=5,indexed_at=10))
        c.execute(cache.insert().values(id='legacy-vector',key='legacy-key',signature=model.signature,input='Capacity is 10 MW.',vector=model.encode('Capacity is 10 MW.')))
        c.execute(chunks.insert().values(id='legacy-chunk',version_id='legacy-v1',ordinal=0,heading='Capacity',locator='Capacity',text='Capacity is 10 MW.',cache_id='legacy-vector'))
        c.execute(intervals.insert().values(id='legacy-interval',page_id='legacy-page',version_id='legacy-v1',start=10))
    engine.dispose();before=hashlib.sha256(path.read_bytes()).hexdigest()
    migrated=tmp_path/'legacy-migrated'
    result=migrate_sqlite(data,target.db.engine.url.render_as_string(hide_password=False),migrated,tmp_path/'legacy-backup.zip')
    assert result['restore']['verified'] and hashlib.sha256(path.read_bytes()).hexdigest()==before
    from parity.search_schema import projection
    assert target.db.one(select(projection))['chunk_id']=='legacy-chunk'
    target.embedder=model
    found=target.search('capacity')['results']
    assert found and found[0]['version_id']=='legacy-v1' and found[0]['chunk_id']=='legacy-chunk'
    assert (migrated/'artifacts'/raw).read_bytes()==body


def test_postgres_lexical_rank_does_not_reward_generic_dense_candidates(system):
    service,_=system
    if service.db.engine.dialect.name!='postgresql':pytest.skip('PostgreSQL-specific hybrid rank fusion')
    from parity.db import sources,cache,chunks
    from parity.search_schema import projection
    class Model:
        mode='minilm';signature='deterministic-ranking-fixture'
        def encode(self,query):return [1.0]+[0.0]*383
    service.embedder=Model();now=time.time()
    with service.db.tx() as c:
        c.execute(sources.insert().values(id='rank-source',name='Ranking fixture',root_url='https://rank.example/',config={'interval':900},enabled=True))
        for i in range(201):
            target=i==200;pid=f'rank-page-{i}';vid=f'rank-version-{i}';cid=f'rank-chunk-{i}'
            content='Project '+('Aster88888' if target else f'Other{i}')+' verified capacity 10 MW.'
            vector=([0.0,1.0]+[0.0]*382) if target else service.embedder.encode('')
            c.execute(pages.insert().values(id=pid,source_id='rank-source',url='https://rank.example/'+str(i),title='Project',availability='active',health='healthy',current_id=vid,last_version_id=vid,verified_at=now))
            c.execute(versions.insert().values(id=vid,page_id=pid,number=1,title='Project',content=content,observed_at=now,indexed_at=now))
            c.execute(cache.insert().values(id=cid,key=cid,signature=service.embedder.signature,input=content,vector=vector))
            c.execute(chunks.insert().values(id=cid,version_id=vid,ordinal=0,heading='Capacity',locator='Capacity',text=content,cache_id=cid))
            c.execute(projection.insert().values(chunk_id=cid,source_id='rank-source',page_id=pid,version_id=vid,text=content,heading='Capacity',locator='Capacity',model_signature=service.embedder.signature,vector=vector))
    found=service.search('Project Aster88888 verified capacity MW',limit=10)
    assert any(r['page_id']=='rank-page-200' for r in found['results'])


def test_preview_shares_worker_chromium_slot(system,monkeypatch):
    service,m=system
    from parity.job_schema import resource_locks
    from parity.browser import preview_capture
    from parity import browser
    source=service.add_source('Browser fixture',URL,{'render_mode':'browser'})
    with service.db.tx() as c:c.execute(resource_locks.insert().values(name='chromium',owner='capture-worker',lease_until=time.time()+120))
    with pytest.raises(ValueError,match='Chromium is capturing another page'):
        preview_capture(service,URL,source)
    with service.db.tx() as c:c.execute(resource_locks.update().values(lease_until=0))
    monkeypatch.setattr(browser,'capture',lambda *args:Response(URL,200,{},HTML.encode()))
    assert preview_capture(service,URL,source).status==200
    assert service.db.one(select(resource_locks))['owner'] is None


def test_redirected_preview_failure_warns_the_original_requested_page(system,monkeypatch):
    service,m=system
    monkeypatch.setattr(service.fetcher,'get',lambda *args,**kwargs:Response(URL,200,{},HTML.encode()))
    preview=m.preview({'root_url':URL.rstrip('/'),'instructions':'Current Price','use_ai':False})
    field=next(f for f in preview['candidates'] if f['name']=='Current Price')
    activated=m.activate({'draft_id':preview['draft_id'],'fields':[field]})
    assert activated['monitor']['root_url']==URL
    m.process_error(activated['source'],'redirect-failure',URL.rstrip('/'),'The website returned 403',403)
    field=m.dashboard()['widgets'][0]
    assert field['status']=='stale' and field['value']=='1200.5' and '403' in field['error']
    with pytest.raises(ValueError,match='different website URL'):
        m.preview({'source_id':activated['source']['id'],'root_url':'https://other.example/'})


def test_all_five_mcp_tools_through_authenticated_api_bridge(system,monkeypatch):
    import socket,subprocess
    service,m=system;populate(service,m)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    monkeypatch.setattr(config,'API_PORT',port);monkeypatch.setenv('PARITY_ADMIN_TOKEN','protocol-test-only')
    env={**os.environ,'DATABASE_URL':service.db.engine.url.render_as_string(hide_password=False),'PARITY_DATA_DIR':str(config.DATA),'PARITY_PORT':str(port),'PARITY_EMBEDDER':'lexical','PARITY_EXTERNAL_WORKERS':'1'}
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','parity.api:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        import httpx
        with httpx.Client(trust_env=False,timeout=1) as client:
            for _ in range(100):
                try:
                    if client.get(f'http://127.0.0.1:{port}/health/ready').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise AssertionError('API bridge did not start')
        from parity.integrations import test_mcp
        result=asyncio.run(test_mcp(service))
        assert result['status']=='passed',result
        assert len(result['tools'])==5 and all(t['success'] for t in result['tools'])
    finally:proc.terminate();proc.wait(timeout=10)
