"""Public contracts, transactional setup, bounded series and lossless transfer."""
import copy,json,time
import pytest
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select,func,event
from parity.db import DB,schema,meta,SCHEMA_VERSION,sources
from parity import automation_schema as a,monitor_schema as m,config
from parity.automation import Automations
from parity.v2_api import create_router
from parity.series import dashboard_series
from parity.transfer import backup_database,restore_database
from tests.test_monitoring import monitor,setup_monitor,URL
from tests.test_automation_runtime import activate,cost_plan,drain,capture


def client_for(service):
    app=FastAPI();app.include_router(create_router(service,None))
    @app.exception_handler(ValueError)
    async def bad(request:Request,error):return JSONResponse({'detail':str(error)},400)
    return TestClient(app)


def test_automatic_source_and_calculation_activate_together_idempotently(monitor):
    service,fetcher=monitor
    with client_for(service.service) as client:
        response=client.post('/api/monitors/auto-preview',json={'root_url':URL,'instructions':'Calculate the sum of Current Price','use_ai':False})
        assert response.status_code==200,response.text
        draft=response.json();assert draft['automation']['status']=='ready'
        body={'draft_id':draft['draft_id'],'fields':draft['fields'],'automation_draft_id':draft['automation']['draft_id']}
        saved=client.post('/api/monitors',json=body);assert saved.status_code==200,saved.text
        assert client.post('/api/monitors',json=body).json()['monitor']['id']==saved.json()['monitor']['id']
        worker=Automations(service.service);drain(worker)
        automations=client.get('/api/automations').json()
        assert automations['total']==1
        auto=automations['items'][0]
        assert auto['current']['outputs'][0]['value']=='1200.5'
        assert not auto['plan']['inputs'][0]['monitor_id'].startswith('draft:')
        evidence=client.get('/api/calculations/'+auto['current']['id']).json()
        assert evidence['inputs'][0]['capture_id']==draft['capture_id']


def test_unresolved_calculation_never_starts_only_source(monitor):
    service,fetcher=monitor
    with client_for(service.service) as client:
        draft=client.post('/api/monitors/auto-preview',json={'root_url':URL,'instructions':'Calculate the cost of Current Price for my quantity and compare with my budget','use_ai':False}).json()
        assert draft['automation']['status']=='needs_input'
        response=client.post('/api/monitors',json={'draft_id':draft['draft_id'],'fields':draft['fields']})
        assert response.status_code==400
        assert service.dashboard()['totals']['monitors']==0
        assert Automations(service.service).listing()['total']==0


def test_api_parameters_alert_ack_archive_and_legacy_series(monitor):
    service,activated,_=setup_monitor(monitor)
    worker,auto,draft=activate(service,cost_plan(activated));drain(worker)
    with client_for(service.service) as client:
        assert client.get('/api/automations/'+auto['id']).status_code==200
        alert=client.get('/api/automation-alerts').json()['items'][0]
        assert client.patch('/api/automation-alerts/'+alert['id'],json={'acknowledged':True}).json()['acknowledged_at']
        assert client.patch('/api/automation-alerts/'+alert['id'],json={'acknowledged':False}).status_code==400
        revised=client.patch('/api/automations/'+auto['id'],json={'parameters':{'quantity':'3'}})
        assert revised.status_code==200,revised.text
        drain(worker)
        identities=[{'kind':'calculated','automation_id':auto['id'],'field_id':'cost'}, {'monitor_id':activated['monitor']['id'],'field_id':activated['monitor']['fields'][0]['id']}]
        series=client.post('/api/dashboard/series',json={'fields':identities}).json()
        assert len(series['items'])==2
        assert series['items'][0]['points'][-1]['value']=='3601.5'
        assert series['items'][0]['points'][0]['evaluation_id']
        assert client.delete('/api/automations/'+auto['id']).json()['archived_at']
        assert client.get('/api/automations').json()['total']==0
        assert client.get('/api/automations?archived=true').json()['total']==1


def test_calculated_series_batch_preserves_real_extrema_boundaries_and_two_queries(monitor):
    service,activated,_=setup_monitor(monitor)
    worker,auto,_=activate(service,cost_plan(activated));drain(worker)
    original=worker.db.one(select(a.automation_evaluations))
    start=time.time()-10000
    with worker.db.tx() as c:
        for n in range(1000):
            value='-999' if n==333 else '999' if n==777 else str(n%21-10)
            record={**original,'id':f'e{n:04}','job_id':f'j{n:04}','at':start+n*7.1,'outputs':[{'id':'cost','name':'Cost','value':value,'unit':'INR','type':'number'}]}
            if n==500:record.update(status='blocked',outputs=[],error='Missing price')
            c.execute(a.automation_evaluations.insert().values(**record))
            c.execute(a.automation_values.insert().values(evaluation_id=record['id'],automation_id=auto['id'],field_id='cost',revision_id=auto['revision_id'],at=record['at'],status=record['status'],value=value if n!=500 else None,number=float(value) if n!=500 else None,unit='INR' if n<800 else 'USD'))
    calls=[]
    def count(*args):calls.append(1)
    event.listen(worker.db.engine,'before_cursor_execute',count)
    try:result=dashboard_series(service.service,{'fields':[{'kind':'calculated','automation_id':auto['id'],'field_id':'cost'}],'start':start,'end':start+8000})['items'][0]
    finally:event.remove(worker.db.engine,'before_cursor_execute',count)
    assert len(calls)==2 and result['total']==1000 and len(result['points'])<=200 and result['sampled']
    assert {'e0000','e0999','e0333','e0777'}<={p['evaluation_id'] for p in result['points']}
    assert any(p['number']==0 for p in result['points'])
    assert any(p['break_before'] and p['at']>=start+500*7.1 for p in result['points'])
    assert all(p['evaluation_id'] for p in result['points'])


def test_schema4_upgrade_and_populated_automation_backup_restore(monitor,tmp_path):
    service,activated,_=setup_monitor(monitor)
    worker,auto,_=activate(service,cost_plan(activated));drain(worker)
    before=worker.get(auto['id'])['current']
    with worker.db.tx() as c:
        alert=c.execute(select(a.automation_alerts)).mappings().first()
        c.execute(a.automation_deliveries.insert().values(id='pending',alert_id=alert['id'],automation_id=auto['id'],revision_id=auto['revision_id'],connection_id='missing-secret',payload={'alert':alert['id']},status='queued',created_at=time.time()))
    archive=tmp_path/'with-calculations.zip'
    backup_database(str(worker.db.engine.url.render_as_string(hide_password=False)),config.DATA,archive)
    target_url='sqlite:///'+str(tmp_path/'restored.sqlite')
    result=restore_database(archive,target_url,tmp_path/'restored-data');assert result['verified']
    restored=DB(target_url)
    assert restored.one(select(a.automation_evaluations).where(a.automation_evaluations.c.id==before['id']))['outputs']==before['outputs']
    assert restored.one(select(a.automation_deliveries))['status']=='disabled'
    assert not (tmp_path/'restored-data/private/automation-connections.json').exists()
    restored.engine.dispose()
    # Rehearse an actual v4 installation: remove only the new empty tables from a
    # separate fresh DB, keep a populated source/capture history, then upgrade.
    old_url='sqlite:///'+str(tmp_path/'schema4.sqlite');old=DB(old_url)
    with old.tx() as c:
        for table in reversed(meta.sorted_tables):
            if table.name.startswith('automation'):table.drop(c)
        c.execute(schema.delete());c.execute(schema.insert().values(number=4))
    old.engine.dispose()
    with pytest.raises(RuntimeError,match='upgrade required'):DB(old_url)
    old_backup=tmp_path/'before-upgrade.zip';backup_database(old_url,tmp_path/'empty',old_backup)
    upgraded=DB(old_url,upgrade=True)
    assert upgraded.one(select(schema))['number']==SCHEMA_VERSION==5
    assert upgraded.one(select(func.count().label('n')).select_from(a.automations))['n']==0
    upgraded.engine.dispose()


def test_calculated_layout_and_pending_worker_values_are_not_verified(monitor):
    service,activated,_=setup_monitor(monitor)
    plan=cost_plan(activated);plan['outputs'][0]['id']='a'*36
    plan['rules'][0]['condition']['args'][0]['id']='a'*36
    worker,auto,_=activate(service,plan);drain(worker)
    identity='calculated:'+auto['id']+':'+'a'*36
    assert service.layout({'order':[identity],'hidden':[identity],'pinned':[identity]})['pinned']==[identity]
    old=worker.get(auto['id'])['current']['id']
    capture(service,activated,'pending-recalculation','1400')
    current=worker.get(auto['id'])['current']
    assert current['status']=='pending' and current['outputs'][0]['value']=='2401'
    assert current['last_valid_evaluation_id']==old
    drain(worker)
    assert worker.get(auto['id'])['current']['status']=='ok'


def test_dated_responsive_table_discovery_uses_labels_latest_date_and_session():
    from parity.structured import discover,extract_field
    html='''<div id="tab-am"><table><tr><td data-label="Date">19/10/2026</td><td data-label="Gold 916">100</td><td data-label="Silver 999">20</td></tr>
    <tr><td data-label="Date">16/10/2026</td><td data-label="Gold 916">90</td><td data-label="Silver 999">19</td></tr></table></div>'''
    candidates=discover(html,URL)
    field=next(f for f in candidates if f['name']=='Gold 916 — latest dated row AM')
    assert field['valid'] and field['preview']['value']=='100' and field['preview']['period']=='2026-10-19 AM'
    updated=html.replace('<table>','<table><tr><td data-label="Date">21/10/2026</td><td data-label="Gold 916">110</td><td data-label="Silver 999">21</td></tr>')
    assert extract_field(updated,field,URL)['value']=='110'
    assert extract_field(updated,field,URL)['period']=='2026-10-21 AM'
    # Row reordering cannot select an older observation; changing a label fails.
    with pytest.raises(LookupError,match='column'):
        extract_field(updated.replace('Gold 916','Unrelated gold'),field,URL)


def test_calculation_can_select_a_detected_field_outside_default_extraction_selection(monitor):
    service,fetcher=monitor
    draft=service.auto_preview({'root_url':URL,'instructions':'Calculate sum of Current Price','use_ai':False})
    worker=Automations(service.service)
    holding=next(i for i in draft['automation']['catalog'] if i['name']=='Promoter holding')
    assert holding['field_id'] not in {f['id'] for f in draft['fields']}
    plan={'version':1,'name':'Holding copy','inputs':[holding],'outputs':[{'id':'holding','name':'Holding','expression':{'op':'input','id':holding['id']}}]}
    calculation=worker.preview({'instructions':'Show a calculated holding','monitor_draft_id':draft['draft_id'],'plan':plan})
    saved=service.activate({'draft_id':draft['draft_id'],'fields':draft['fields'],'automation_draft_id':calculation['draft_id']})
    assert any(f['name']=='Promoter holding' for f in saved['monitor']['fields'])
    record=worker.once();assert record['outputs'][0]['value']=='0'
    assert record['inputs'][0]['capture_id']==draft['capture_id']


def test_preview_inherits_source_units_before_dimension_validation(monitor):
    service,activated,_=setup_monitor(monitor)
    plan=cost_plan(activated);del plan['inputs'][0]['unit']
    preview=Automations(service.service).preview({'plan':plan,'use_ai':False})
    assert preview['status']=='ready' and preview['plan']['inputs'][0]['unit']=='INR'
    assert preview['preview']['outputs'][0]['value']=='2401'


def test_dashboard_search_keeps_source_and_calculation_context(monitor):
    service,activated,_=setup_monitor(monitor)
    worker,auto,_=activate(service,cost_plan(activated));drain(worker)
    source=service.db.one(select(sources).where(sources.c.id==activated['source']['id']))
    with client_for(service.service) as client:
        for term in ['current PRICE',source['name'],source['root_url'],auto['name'],auto['plan']['outputs'][0]['name']]:
            dashboard=client.get('/api/dashboard',params={'q':term,'limit':1}).json()
            assert dashboard['total']==1,(term,dashboard)
            assert dashboard['monitors'][0]['source_id']==activated['source']['id']
            assert dashboard['totals']['fields']==len(activated['monitor']['fields'])
            calculations=client.get('/api/automations',params={'q':term,'limit':1}).json()
            assert calculations['total']==1,(term,calculations)
            assert calculations['items'][0]['id']==auto['id']
        with service.db.tx() as connection:
            connection.execute(sources.update().where(sources.c.id==source['id']).values(name='NeedleXLiteral'))
        for term in ['no-matching-source-4829','needle%literal','needle_literal']:
            assert client.get('/api/dashboard',params={'q':term}).json()['total']==0
            assert client.get('/api/automations',params={'q':term}).json()['total']==0
        assert client.get('/api/dashboard',params={'q':' '*5}).json()['total']==1
        assert client.get('/api/dashboard',params={'q':'x'*201}).status_code==422
        assert client.get('/api/automations',params={'q':'x'*201}).status_code==422
        service.service.remove_source(activated['source']['id'])
        assert client.get('/api/dashboard',params={'q':source['name']}).json()['total']==0
