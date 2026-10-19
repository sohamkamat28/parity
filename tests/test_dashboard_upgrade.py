import copy,json,socket,time
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func,event,text
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from parity import monitor_schema as ms,config
from parity.db import sources,runs,DB
from parity.jobs import Jobs
from parity.job_schema import url_jobs
from parity.series import dashboard_series
from parity.structured import discover,extract_field,suggest
from parity.fetch import Fetcher,FetchError,Response
from parity.monitor_evidence import retrieve
from parity.v2_api import create_router
from tests.test_monitoring import monitor,setup_monitor,URL,HTML


def test_batched_series_preserves_endpoints_extrema_gaps_and_evidence(monitor):
    m,activated,fields=setup_monitor(monitor)
    field=activated['monitor']['fields'][0]
    original=m.db.one(select(ms.monitor_observations).where(ms.monitor_observations.c.field_id==field['id']))
    start=time.time()-10000
    rows=[]
    for index in range(1000):
        row={**original,'id':f'point-{index:04}','at':start+index*7.3,'value':str(index%11-5)}
        if index==345:row['value']='-999'
        if index==700:row['value']='999'
        if index==500:row.update(status='missing',value=None,error='Layout changed')
        if index>600:row['period']='Q2'
        if index>800:row.update(unit='USD',revision_id=original['revision_id'])
        rows.append(row)
    with m.db.tx() as c:c.execute(ms.monitor_observations.insert(),rows)
    calls=[]
    def count(*args):calls.append(1)
    event.listen(m.db.engine,'before_cursor_execute',count)
    try:
        result=dashboard_series(m.service,{'start':start,'end':start+8000,'fields':[{'monitor_id':original['monitor_id'],'field_id':field['id']}]})['items'][0]
    finally:event.remove(m.db.engine,'before_cursor_execute',count)
    points=result['points'];ids={p['id'] for p in points}
    assert len(calls)==2 and 1<len(points)<=200 and result['total']==1000 and result['sampled']
    assert {'point-0000','point-0999','point-0345','point-0700'}<=ids
    assert any(p['number']==0 for p in points)
    assert any(p['break_before'] and start+500*7.3-200<=p['at']<=start+500*7.3+200 for p in points)
    assert all(p['capture_id']==original['capture_id'] for p in points)
    assert [p['at'] for p in points]==sorted(p['at'] for p in points)
    assert dashboard_series(m.service,{'start':start,'end':start+8000,'fields':[{'monitor_id':original['monitor_id'],'field_id':field['id']}]})['items'][0]==result


def test_series_baseline_validation_and_revision_boundary(monitor):
    m,a,fields=setup_monitor(monitor)
    f=a['monitor']['fields'][0];identity={'monitor_id':a['monitor']['id'],'field_id':f['id']}
    result=dashboard_series(m.service,{'fields':[identity]})['items'][0]
    assert result['total']==1 and len(result['points'])==1 and not result['sampled']
    assert result['points'][0]['number']==1200.5
    for payload in ({'fields':[]},{'fields':[identity],'end':'bad'},{'fields':[identity]*51},{'fields':[identity],'start':1,'end':3000000},{'fields':[{'monitor_id':'other','field_id':f['id']}]}):
        with pytest.raises(ValueError):dashboard_series(m.service,payload)
    draft=m.preview({'source_id':a['source']['id'],'fields':a['monitor']['fields']})
    revised=m.revise(a['monitor']['id'],{'draft_id':draft['draft_id'],'fields':draft['fields']})
    result=dashboard_series(m.service,{'fields':[identity]})['items'][0]
    assert len({p['revision_id'] for p in result['points']})==2
    assert all(p['break_before'] for p in result['points'])


def test_removal_fences_workers_retains_history_and_restore_is_paused(monitor):
    m,a,fields=setup_monitor(monitor)
    service=m.service;source=a['source'];jobs=Jobs(service)
    jobs.initialize(a['run']['id']);claim=jobs.claim_capture(a['run']['id']);assert claim
    before=m.db.one(select(func.count().label('n')).select_from(ms.monitor_observations))['n']
    removed=service.remove_source(source['id'])
    assert removed['removed_at'] and not removed['enabled'] and removed['paused']
    assert service.remove_source(source['id'])['removed_at']==removed['removed_at']
    assert m.dashboard()['totals']['monitors']==0
    assert not service.overview()['sources']
    assert m.db.one(select(url_jobs).where(url_jobs.c.id==claim['id']))['status']=='cancelled'
    with pytest.raises(ValueError,match='STALE_WORKER'):jobs.renew(claim)
    with pytest.raises(ValueError):
        with m.db.tx() as c:service._guard(c,source['id'],claim['run_id'],claim['source_generation'])
    assert not retrieve(service,'current price',mode='current')
    historical=retrieve(service,'current price',mode='as_of',as_of=time.time())
    assert historical
    assert m.evidence(historical[0]['capture_id'])['id']==historical[0]['capture_id']
    assert m.db.one(select(func.count().label('n')).select_from(ms.monitor_observations))['n']==before
    with pytest.raises(ValueError):service.set_source(source['id'],enabled=True)
    restored=service.remove_source(source['id'],restore=True)
    assert restored['removed_at'] is None and restored['enabled'] and restored['paused']
    assert service.remove_source(source['id'],restore=True)['paused']
    assert m.dashboard()['totals']['monitors']==1
    assert len(m.db.all(select(ms.monitor_events).where(ms.monitor_events.c.kind.in_(['source_removed','source_restored']))))==2


def test_series_and_removed_list_api(monitor):
    m,a,fields=setup_monitor(monitor)
    app=FastAPI();app.include_router(create_router(m.service,None))
    @app.exception_handler(ValueError)
    async def bad(request:Request,error):return JSONResponse({'detail':str(error)},400)
    with TestClient(app) as client:
        assert client.post('/api/dashboard/series',json={'fields':[{'monitor_id':a['monitor']['id'],'field_id':a['monitor']['fields'][0]['id']}]}).status_code==200
        assert client.post('/api/dashboard/series',json={'fields':[]}).status_code==400
        m.service.remove_source(a['source']['id'])
        assert client.get('/api/list/sources').json()['total']==0
        assert client.get('/api/list/sources?removed=true').json()['items'][0]['id']==a['source']['id']
        assert client.get('/api/monitors').json()['total']==0
        assert client.get('/api/monitors?source_id='+a['source']['id']).json()['total']==1


def test_json_ld_is_bound_to_entity_and_property_not_position():
    objects=[{'@type':'Product','@id':'book-a','name':'Atlas','offers':{'price':0,'priceCurrency':'USD'}},
             {'@type':'Product','@id':'book-b','name':'Other','offers':{'price':12,'priceCurrency':'USD'}}]
    def page(data):return '<script type="application/ld+json">'+json.dumps(data)+'</script><h1>Book shop</h1>'
    candidates=discover(page(objects),URL)
    field=next(f for f in candidates if 'Atlas' in f['name'])
    assert field['valid'] and field['preview']['value']=='0' and field['preview']['unit']=='USD'
    assert extract_field(page(objects[::-1]),field,URL)['value']=='0'
    for bad in ([objects[1]],[objects[0],objects[0]]):
        with pytest.raises(LookupError):extract_field(page(bad),field,URL)
    altered=copy.deepcopy(objects);altered[0]['offers']={'priceCurrency':'USD'}
    with pytest.raises(LookupError):extract_field(page(altered),field,URL)


def test_accessible_semantics_and_ambiguous_auto_price(monitor):
    body='<span id="temp-label">Temperature</span><output aria-labelledby="temp-label" data-value="-4">-4</output>'
    field=suggest(discover(body,URL),'Track temperature')[0]
    assert field['preview']['value']=='-4'
    m,fetcher=monitor;fetcher.body='<p>Current price: $10</p><p>Current price: $20</p>'
    with pytest.raises(FetchError,match='Multiple prices or products') as error:m.auto_preview({'root_url':URL,'instructions':'Track current price','use_ai':False})
    assert error.value.code=='ambiguous_fields' and not m.dashboard()['monitors']


def test_alternative_validated_addresses_retain_tls_hostname(monkeypatch):
    fetcher=Fetcher();attempts=[];hostnames=[]
    monkeypatch.setattr(fetcher,'addresses',lambda *args:['93.184.216.34','93.184.216.35'])
    sock=SimpleNamespace(settimeout=lambda value:None,close=lambda:None)
    def connect(address,timeout):
        attempts.append(address[0]);assert 0<timeout<=3
        if len(attempts)==1:raise TimeoutError('Unreachable first address')
        return sock
    monkeypatch.setattr(socket,'create_connection',connect)
    import ssl,http.client
    monkeypatch.setattr(ssl,'create_default_context',lambda:SimpleNamespace(wrap_socket=lambda socket,server_hostname:(hostnames.append(server_hostname) or socket)))
    response=SimpleNamespace(status=200,getheaders=lambda:[('Content-Type','text/html')],read=lambda size:b'<p>Works</p>')
    monkeypatch.setattr(http.client,'HTTPConnection',lambda *a,**kw:SimpleNamespace(request=lambda *a,**kw:None,getresponse=lambda:response,close=lambda:None))
    result=fetcher._request(URL,{'root_url':URL,'config':{}},{})
    assert result.status==200 and len(attempts)==2 and hostnames==['fixture.example']


def test_schedule_is_saved_and_remains_after_restart(monitor):
    m,fetcher=monitor
    draft=m.auto_preview({'root_url':URL,'instructions':'Track current price','settings':{'interval':7200},'use_ai':False})
    activated=m.activate({'draft_id':draft['draft_id'],'fields':draft['fields']})
    assert activated['source']['config']['interval']==7200
    reopened=DB(m.db.engine.url.render_as_string(hide_password=False))
    try:assert reopened.one(select(sources).where(sources.c.id==activated['source']['id']))['config']['interval']==7200
    finally:reopened.engine.dispose()


def test_list_first_observed_survives_disappearance_and_reappearance(monitor):
    m,a,fields=setup_monitor(monitor,names=('Announcements',))
    baseline=next(f['value'] for f in m.dashboard()['widgets'] if f['type']=='list')
    source=a['source'];first={item['key']:item['first_observed_at'] for item in baseline}
    assert all(first.values())
    m.process_capture(source,'gone',Response(URL,200,{},HTML.replace('<li><a href="/notice/a">First notice</a></li>','').encode()))
    m.process_capture(source,'back',Response(URL,200,{},HTML.encode()))
    assert {i['key']:i['first_observed_at'] for i in next(f['value'] for f in m.dashboard()['widgets'] if f['type']=='list')}==first


def test_v3_backup_restore_and_additive_migration_keep_histories(monitor,tmp_path):
    from parity.transfer import backup_database,restore_database,verify_backup
    from parity.db import schema,SCHEMA_VERSION
    m,a,fields=setup_monitor(monitor,names=('Announcements',))
    original_count=m.db.one(select(func.count().label('n')).select_from(ms.monitor_observations))['n']
    with m.db.tx() as c:
        c.execute(ms.monitor_list_items.delete())
        ms.monitor_list_items.drop(c)
        c.exec_driver_sql('ALTER TABLE sources DROP COLUMN removed_at')
        c.execute(schema.delete());c.execute(schema.insert().values(number=3))
    url=m.db.engine.url.render_as_string(hide_password=False)
    archive=tmp_path/'v3-backup.zip'
    backup_database(url,config.DATA,archive)
    manifest=verify_backup(archive)
    assert manifest['schema_version']==3 and 'removed_at' not in manifest['tables']['sources']['columns']
    restored=restore_database(archive,'sqlite:///'+str(tmp_path/'restored.sqlite'),tmp_path/'restored-data')
    assert restored['verified'] and restored['schema_version']==SCHEMA_VERSION
    # Source remains on v3 until explicitly initialized; backing it up didn't mutate it.
    assert m.db.one(select(schema))['number']==3
    with pytest.raises(RuntimeError,match="upgrade required"):DB(url)
    upgraded=DB(url,upgrade=True)
    try:
        assert upgraded.one(select(schema))['number']==SCHEMA_VERSION
        assert upgraded.one(select(func.count().label('n')).select_from(ms.monitor_observations))['n']==original_count
        assert upgraded.one(select(func.count().label('n')).select_from(ms.monitor_list_items))['n']==2
        assert upgraded.one(select(sources))['removed_at'] is None
    finally:upgraded.engine.dispose()


def test_access_blocks_are_permanent_and_retry_after_is_retained(monkeypatch,monitor):
    fetcher=Fetcher()
    source={'root_url':URL,'config':{'delay':0}}
    monkeypatch.setattr(fetcher,'_request',lambda *args:Response(URL,403,{},b''))
    with pytest.raises(FetchError) as blocked:fetcher.get(URL,source)
    assert blocked.value.code=='access_blocked' and not blocked.value.transient
    monkeypatch.setattr(fetcher,'_request',lambda *args:Response(URL,429,{'retry-after':'120'},b''))
    with pytest.raises(FetchError) as limited:fetcher.get(URL,source)
    assert limited.value.transient
    m,fetcher=monitor
    assert Jobs(m.service)._retry_at(limited.value.response,1)>=time.time()+119


def test_removed_document_retrieval_and_citation_compatibility(monitor,monkeypatch):
    from parity.embedding import Embedder
    from parity.db import versions
    m,a,fields=setup_monitor(monitor)
    monkeypatch.setenv('PARITY_EMBEDDER_LOCAL','1')
    model=Embedder('lexical');monkeypatch.setattr(m.service,'model',lambda:model)
    m.service.run(a['run']['id']);assert Jobs(m.service).index_once()['chunks']>0
    before=m.service.search('company',source_ids=[a['source']['id']])
    assert before['results']
    version_id=before['results'][0]['version_id'];page_id=before['results'][0]['page_id']
    m.service.remove_source(a['source']['id'])
    assert not m.service.search('company',source_ids=[a['source']['id']])['results']
    historical=m.service.search('company',source_ids=[a['source']['id']],mode='as_of',as_of=time.time())
    assert historical['results'][0]['version_id']==version_id
    assert m.service.get_page(page_id,1)['version']['id']==version_id


def test_schedule_updates_next_due_and_rejects_invalid_ranges(monitor):
    m,a,fields=setup_monitor(monitor)
    m.service.run(a['run']['id'])
    changed=m.service.update_source(a['source']['id'],settings={'interval':3600})
    assert changed['config']['interval']==3600 and time.time()+3590<changed['next_due']<time.time()+3601
    for invalid in (9,604801,True,float('inf'),float('nan')):
        with pytest.raises(ValueError,match='interval'):m.service.update_source(a['source']['id'],settings={'interval':invalid})


def test_series_keeps_every_observation_until_limit_and_marks_missed_checks(monitor):
    m,a,fields=setup_monitor(monitor)
    f=a['monitor']['fields'][0]
    original=m.db.one(select(ms.monitor_observations).where(ms.monitor_observations.c.field_id==f['id']))
    now=original['at']
    rows=[{**original,'id':f'small-{i}','at':now+i*20,'value':str(i-2)} for i in range(1,7)]
    rows[-1]['at']=now+4000
    with m.db.tx() as c:c.execute(ms.monitor_observations.insert(),rows)
    result=dashboard_series(m.service,dict(fields=[dict(monitor_id=a['monitor']['id'],field_id=f['id'])],start=now-1,end=now+5000))['items'][0]
    assert result['total']==7 and len(result['points'])==7 and not result['sampled']
    assert result['points'][-1]['break_before'] and not result['points'][1]['break_before']


def test_removal_racing_a_capture_claim_uses_consistent_lock_order(monitor,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    m,a,fields=setup_monitor(monitor)
    if m.db.engine.dialect.name!='postgresql':pytest.skip('Row-lock concurrency is exercised on PostgreSQL')
    jobs=Jobs(m.service);jobs.initialize(a['run']['id'])
    entered=threading.Event();release=threading.Event();removing=threading.Event()
    reserve=jobs._reserve
    def blocked_reserve(*args):
        entered.set();assert release.wait(10)
        return reserve(*args)
    monkeypatch.setattr(jobs,'_reserve',blocked_reserve)
    def remove():
        removing.set();return m.service.remove_source(a['source']['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        capture=pool.submit(jobs.claim_capture,a['run']['id'])
        assert entered.wait(10)
        removal=pool.submit(remove);assert removing.wait(10)
        try:
            until=time.monotonic()+5
            with m.db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as observer:
                while time.monotonic()<until:
                    waiting=observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock'")).scalar_one()
                    if waiting:break
                    time.sleep(.02)
                assert waiting,'The removal must actually overlap a held capture transaction'
        finally:release.set()
        claim=capture.result(timeout=15);assert claim
        assert removal.result(timeout=15)['removed_at']
    with pytest.raises(ValueError,match='STALE_WORKER'):jobs.renew(claim)


def test_semantic_price_tracks_currency_changes_and_zero():
    body='<div itemscope><meta itemprop="priceCurrency" content="USD"><meta itemprop="price" content="0"></div>'
    field=next(f for f in discover(body,URL) if f['rule'].get('unit_selector'))
    assert field['type']=='currency' and field['preview']['value']=='0' and field['preview']['unit']=='USD'
    assert len(suggest(discover(body,URL),'Track current price'))==1
    assert extract_field(body.replace('USD','EUR'),field,URL)['unit']=='EUR'
    with pytest.raises(LookupError):extract_field(body.replace('itemprop="priceCurrency"','itemprop="other"'),field,URL)


def test_equal_prices_on_different_entities_need_product_specific_instructions(monitor):
    m,fetcher=monitor
    values=[dict(**{'@type':'Product','@id':name},name=name,offers={'price':0,'priceCurrency':'USD'}) for name in ('Atlas','Other')]
    fetcher.body='<script type="application/ld+json">'+json.dumps(values)+'</script>'
    with pytest.raises(FetchError,match='Multiple prices or products'):m.auto_preview(dict(root_url=URL,instructions='Track current price',use_ai=False))
    draft=m.auto_preview(dict(root_url=URL,instructions='Track Atlas current price',use_ai=False))
    assert len(draft['fields'])==1 and draft['fields'][0]['preview']['value']=='0' and draft['fields'][0]['rule']['entity']=='@id:Atlas'


def test_dns_failure_has_actionable_classification(monkeypatch):
    def unavailable(*args,**kwargs):raise socket.gaierror(8,'nodename nor servname provided, or not known')
    monkeypatch.setattr(socket,'getaddrinfo',unavailable)
    with pytest.raises(FetchError,match='hostname could not be resolved') as error:Fetcher().addresses(URL,{'root_url':URL,'config':{}})
    assert error.value.code=='dns_error' and error.value.transient
