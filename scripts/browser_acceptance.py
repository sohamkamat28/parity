"""Actual browser → API → PostgreSQL → workers → SSE acceptance on synthetic data.

Owns a fresh parity_bench_* database and launcher; never touches installation data.
Use --with-models to additionally verify shared MiniLM and native local chat.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import time
import uuid
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from parity import config
from benchmark_v2 import fresh_database
from run import OwnedProcesses


def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def eventually(check,seconds=40):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=check()
        if value:return value
        time.sleep(.5)
    raise AssertionError('Timed out waiting for committed application state')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--with-models',action='store_true');args=p.parse_args()
    target=ROOT/'docs/verification'/('browser-models.json' if args.with_models else 'browser-no-models.json');target.unlink(missing_ok=True)
    app_port,portal_port,chat_port,embed_port=port(),port(),port(),port()
    base=f'http://127.0.0.1:{app_port}';portal=f'http://127.0.0.1:{portal_port}'
    output=ROOT/'outputs/runtime'/('browser-'+uuid.uuid4().hex);output.mkdir(parents=True)
    report={'models':'enabled' if args.with_models else 'stopped','checks':[],'screenshots':[],'console_errors':[],'series_requests':0}
    checks=report['checks']
    def passed(name):checks.append(name);print('PASS: '+name,flush=True)
    with fresh_database(os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL) as url:
        env={**os.environ,'DATABASE_URL':url,'PARITY_DATA_DIR':str(output/'data'),'PARITY_PORT':str(app_port),'PARITY_FIXTURE_ORIGIN':portal,'PARITY_LOCAL_CHAT_PORT':str(chat_port),'PARITY_EMBEDDING_PORT':str(embed_port),'PARITY_ADMIN_TOKEN':secrets.token_urlsafe(32),'PARITY_FIXTURE_TOKEN':secrets.token_urlsafe(32),'PARITY_CHAT_PROVIDER':'local','PARITY_OFFLINE':'1','OMP_NUM_THREADS':'4'}
        owned=OwnedProcesses(output)
        try:
            env.update(PARITY_EXTERNAL_WORKERS='1',PARITY_EMBEDDING_URL=f'http://127.0.0.1:{embed_port}',PARITY_EMBEDDING_TOKEN=secrets.token_urlsafe(32),PARITY_LOCAL_CHAT_TOKEN=secrets.token_urlsafe(32))
            owned.start('fixture',[sys.executable,'-m','uvicorn','tests.support.fixture_site:app','--host','127.0.0.1','--port',str(portal_port),'--no-access-log'],ROOT,env)
            if args.with_models:
                executable=next((config.CACHE/'local-chat/runtime').rglob('llama-server.exe' if os.name=='nt' else 'llama-server'))
                model=config.CACHE/'local-chat'/(config.LOCAL_CHAT_MODEL+'.gguf')
                owned.start('local-chat',[str(executable),'--model',str(model),'--host','127.0.0.1','--port',str(chat_port),'--ctx-size','4096','--threads','4','--parallel','1','--n-gpu-layers','0','--alias',config.LOCAL_CHAT_MODEL,'--api-key',env['PARITY_LOCAL_CHAT_TOKEN']],ROOT,env)
                owned.start('embedding',[sys.executable,'-m','uvicorn','parity.embedding_server:app','--host','127.0.0.1','--port',str(embed_port),'--no-access-log'],ROOT,env)
            for role,name in [('scheduler','scheduler-worker'),('capture','capture-1-worker'),('capture','capture-2-worker'),('index','index-worker'),('api','api')]:
                owned.start(name,[sys.executable,'-m','tests.support.runtime',role],ROOT,env)
            with httpx.Client(base_url=base,headers={'X-Parity-Token':env['PARITY_ADMIN_TOKEN']},trust_env=False,timeout=190) as client:
                def ready():
                    owned.check()
                    try:return client.get('/health/ready').status_code==200 and httpx.get(portal+'/health/ready',trust_env=False).status_code==200
                    except httpx.HTTPError:return False
                eventually(ready,90)
                response=client.post('/api/sources',json={'name':'Structured acceptance','root_url':portal+'/en/metrics','settings':{'scope_mode':'page','max_pages':1,'max_depth':0,'interval':10,'delay':0}})
                response.raise_for_status();source=response.json()
                with sync_playwright() as pw:
                    browser=pw.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                    context.on('request',lambda request: report.__setitem__('series_requests',report.get('series_requests',0)+1) if '/api/dashboard/series' in request.url else None)
                    page=context.new_page();page.on('pageerror',lambda error:(report['console_errors'].append(str(error)),print('Browser JS error: '+str(error),flush=True)))
                    page.goto(base);page.request.post(base+'/api/session',data={'token':env['PARITY_ADMIN_TOKEN']})
                    assert page.get_by_role('button',name='Settings',exact=True).count()==0
                    for retired in ['/api/demo/sessions','/api/demo-source']:
                        assert client.post(retired,json={}).status_code==404
                    assert client.get('/static/index.html').status_code==404
                    passed('Settings UI, retired sample endpoints and legacy static app are absent')
                    page.locator('.nav-item').filter(has_text='Sources').click()
                    page.locator('.source-select').filter(has_text='Structured acceptance').click()
                    page.get_by_role('button',name='Add tracked information').click()
                    dialog=page.get_by_role('dialog');dialog.get_by_role('button',name='Next',exact=True).click()
                    dialog.get_by_label('Monitoring instructions').fill('Track Current Price, Promoter holding, Quarterly results and Announcements')
                    expect(dialog.get_by_label('Check frequency',exact=True)).to_have_value('10')
                    dialog.get_by_label('Check frequency',exact=True).fill('12')
                    dialog.get_by_role('button',name='Start automatically',exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=90000)
                    expect(page.get_by_role('heading',name='Dashboard',exact=True)).to_be_visible()
                    passed('Automatic URL/instructions setup creates scalar/table/list widgets and opens Dashboard without selectors or layout steps')
                    assert client.get('/api/list/sources').json()['items'][0]['config']['interval']==12
                    eventually(lambda:all(r['status'] not in ('queued','running') for r in client.get('/api/list/jobs?source_id='+source['id']).json()['items']))
                    client.patch('/api/sources/'+source['id'],json={'settings':{'interval':10}}).raise_for_status()
                    passed('Frequency entered during automatic setup is saved; later schedule edits persist')
                    page.locator('.nav-item').filter(has_text='Dashboard').click()
                    price=page.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Current Price',exact=True))
                    expect(price.locator('.observed-value')).to_have_text('1200.5 INR',timeout=25000)
                    expect(page.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Promoter holding',exact=True)).locator('.observed-value')).to_have_text('0 %')
                    # Existing captures and a stopped semantic service must not prevent values.
                    dashboard=client.get('/api/dashboard').json()
                    assert len(dashboard['widgets'])==4 and len(client.get('/api/dashboard').json()['widgets'])==4
                    field=next(f for f in dashboard['widgets'] if f['name']=='Current Price');original_capture=field['capture_id']
                    if not args.with_models:assert client.get('/api/runtime').json()['embedding']['status']=='unavailable'
                    passed('Dashboard zero/currency/table/list rendering and normal source inclusion with PostgreSQL')
                    expect(page.locator('.data-chart, .history-chart')).to_have_count(0)
                    expect(page.get_by_role('button',name='Arrange dashboard',exact=True)).to_have_count(0)
                    expect(page.get_by_role('group',name='Graph time range',exact=True)).to_have_count(0)
                    price.get_by_role('button',name='View details for Current Price',exact=True).focus();page.keyboard.press('Enter')
                    detail=page.get_by_role('dialog').last
                    expect(detail.get_by_role('heading',name='Current Price',exact=True)).to_be_visible()
                    detail.get_by_role('button',name='View evidence',exact=True).click()
                    expect(page.get_by_role('dialog').last.get_by_text('Stored source evidence',exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    detail=page.get_by_role('dialog').last
                    detail.get_by_role('button',name='View history',exact=True).click()
                    expect(page.get_by_role('dialog').last.locator('.field-history-row').first).to_be_visible()
                    expect(page.get_by_role('dialog').last.locator('.history-chart')).to_have_count(0)
                    page.keyboard.press('Escape');page.keyboard.press('Escape')
                    announcements=page.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Announcements',exact=True))
                    announcements.get_by_role('button').click()
                    expect(page.get_by_role('dialog').get_by_text('First observed',exact=False).first).to_be_visible()
                    page.keyboard.press('Escape')
                    page.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Quarterly results',exact=True)).get_by_role('button').click()
                    expect(page.get_by_role('dialog').get_by_role('table')).to_be_visible()
                    passed('Name/value tiles, no graphs or arrangement controls, keyboard tile evidence/history and first-observed announcement dates')
                    page.evaluate("id=>{window.acceptanceEvents=0;window.acceptanceStream=new EventSource('/api/events?after='+id);window.acceptanceStream.addEventListener('update',()=>window.acceptanceEvents++);}",dashboard['event_id'])
                    httpx.post(portal+'/admin/modify-honours',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},trust_env=False).raise_for_status()
                    expect(price.locator('.observed-value')).to_have_text('1250 INR',timeout=30000)
                    expect(page.locator('.cell-changed')).to_have_count(1)
                    expect(page.get_by_role('dialog').get_by_role('table')).to_be_visible()
                    page.wait_for_function('window.acceptanceEvents > 0',timeout=15000)
                    assert '1,200.50' in client.get('/api/captures/'+original_capture).json()['text']
                    passed('Scheduled changes delivered by SSE without chat or Check now; immutable original evidence retained')
                    page.keyboard.press('Escape')
                    # Background updates preserve tile details and open evidence.
                    price.get_by_role('button').click()
                    page.get_by_role('dialog').get_by_role('button',name='View evidence',exact=True).click()
                    evidence=page.get_by_role('dialog').last;expect(evidence.get_by_text('Stored source evidence',exact=True)).to_be_visible()
                    checked=next(f for f in client.get('/api/dashboard').json()['widgets'] if f['id']==field['id'])['last_checked_at']
                    changes=client.get('/api/monitor-changes?kind=changed').json()['total']
                    httpx.post(portal+'/admin/noise-only',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},trust_env=False).raise_for_status()
                    eventually(lambda:next(f for f in client.get('/api/dashboard').json()['widgets'] if f['id']==field['id'])['last_checked_at']>checked)
                    assert client.get('/api/monitor-changes?kind=changed').json()['total']==changes
                    expect(evidence).to_be_visible();page.keyboard.press('Escape');page.keyboard.press('Escape')
                    passed('Unrelated page changes advance verification without field changes; evidence panel and expanded details preserved')
                    # API fault becomes a retained-value warning, then recovers.
                    httpx.post(portal+'/admin/fault',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},json={'target':'metrics','status':403},trust_env=False).raise_for_status()
                    expect(page.locator('.source-attention-link')).to_be_visible(timeout=30000)
                    expect(price.locator('.observed-value')).to_have_text('1250 INR',)
                    httpx.post(portal+'/admin/clear-faults',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},trust_env=False).raise_for_status()
                    expect(page.locator('.source-attention-link')).not_to_be_visible(timeout=30000)
                    passed('Failed HTTP check retains previous verified value and warning; next successful check recovers')
                    page.screenshot(path=str(output/'desktop.png'),full_page=True);report['screenshots'].append(str((output/'desktop.png').relative_to(ROOT)))
                    # Disable streaming to exercise the actual polling path.
                    page.route('**/api/events*',lambda route:route.abort());page.reload()
                    expect(price.locator('.observed-value')).to_have_text('1250 INR',timeout=20000)
                    page.wait_for_event('request',predicate=lambda request:'/api/list/sources?' in request.url,timeout=15000)
                    httpx.post(portal+'/admin/add-notice',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},trust_env=False).raise_for_status()
                    announcements.get_by_role('button').click()
                    expect(page.get_by_role('link',name='New reassessment notice',exact=False)).to_be_visible(timeout=30000)
                    passed('Polling fallback delivers scheduled announcement updates')
                    page.keyboard.press('Escape')
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='Open navigation',exact=True).click();page.keyboard.press('Tab')
                    assert page.locator('.sidebar').evaluate('(el)=>el.contains(document.activeElement)')
                    page.locator('.sidebar').get_by_role('button',name='Close navigation',exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/'narrow.png'),full_page=True);report['screenshots'].append(str((output/'narrow.png').relative_to(ROOT)))
                    passed('390px layout, keyboard navigation, focus management and reduced-motion setting')
                    # Closing the tab does not stop worker services.
                    page.close();httpx.post(portal+'/admin/reset',headers={'X-Fixture-Token':env['PARITY_FIXTURE_TOKEN']},trust_env=False).raise_for_status()
                    eventually(lambda:any(f['name']=='Current Price' and f['value']=='1200.5' for f in client.get('/api/dashboard').json()['widgets']))
                    passed('Scheduled monitoring continues with browser tab closed')
                    # A normal unlabelled JS price is discovered without choosing a rendering mode.
                    planned=client.post('/api/monitors/auto-preview',json={'root_url':portal+'/en/automatic-price','instructions':'Track current price','settings':{}})
                    planned.raise_for_status();draft=planned.json()
                    assert draft['source']['config']['render_mode']=='browser'
                    assert len(draft['fields'])==1 and draft['fields'][0]['preview']['value']=='42.5'
                    activated=client.post('/api/monitors',json={'draft_id':draft['draft_id'],'fields':draft['fields']})
                    activated.raise_for_status()
                    assert activated.json()['source']['config']['interval']==900
                    passed('Automatically selects Chromium for a JavaScript-only price and validates baseline before activation')
                    # More than one monitor belongs to the same website, never a separate source section.
                    extra_field={**field,'id':str(uuid.uuid4()),'name':'Secondary price'}
                    extra=client.post('/api/monitors/preview',json={'source_id':source['id'],'fields':[extra_field]})
                    extra.raise_for_status();extra_draft=extra.json()
                    extra_saved=client.post('/api/monitors',json={'draft_id':extra_draft['draft_id'],'fields':extra_draft['fields'],'name':'Additional price check'})
                    extra_saved.raise_for_status();extra_id=extra_saved.json()['monitor']['fields'][0]['id']
                    other_id=activated.json()['monitor']['fields'][0]['id']
                    preferences=client.get('/api/dashboard/layout').json();preferences['order']=[other_id]+preferences['order']
                    client.put('/api/dashboard/layout',json=preferences).raise_for_status()
                    page=context.new_page();page.goto(base)
                    groups=page.locator('.source-overview')
                    expect(groups).to_have_count(2,timeout=20000)
                    primary=groups.filter(has=page.get_by_role('heading',name='Structured acceptance',exact=True))
                    expect(primary.locator('.monitor-widget')).to_have_count(5)
                    expect(primary.get_by_role('heading',name='Secondary price',exact=True)).to_be_visible()
                    expect(primary.get_by_role('heading',name='Promoter holding',exact=True)).to_be_visible()
                    expect(primary.locator('.field-tile')).to_have_count(5)
                    expect(primary.locator('.source-overview-meta')).to_have_count(0)
                    other=groups.filter(has=page.get_by_role('heading',name=activated.json()['source']['name'],exact=True))
                    expect(other.locator('.monitor-widget')).to_have_count(1)
                    assert other.get_by_role('heading',name='Secondary price',exact=True).count()==0
                    price=primary.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Current Price',exact=True))
                    search=page.get_by_role('textbox',name='Search dashboard',exact=True)
                    search.fill('Structured acceptance')
                    expect(groups).to_have_count(1)
                    search.fill('Secondary price')
                    expect(groups).to_have_count(1)
                    expect(primary.locator('.field-tile')).to_have_count(5)
                    search.fill('no-matching-source-4829')
                    expect(page.get_by_role('heading',name='No matching sources',exact=True)).to_be_visible()
                    page.get_by_role('button',name='Clear dashboard search',exact=True).click()
                    expect(groups).to_have_count(2)
                    expect(page.get_by_role('button',name='Arrange dashboard',exact=True)).to_have_count(0)
                    assert other_id in client.get('/api/dashboard/layout').json()['order']
                    refresh=primary.get_by_role('button',name='Check now',exact=True)
                    assert refresh.inner_text().strip()==''
                    with page.expect_response(lambda response: '/api/sources/'+source['id']+'/crawl' in response.url) as queued:
                        refresh.click()
                    assert queued.value.status==200
                    primary.get_by_role('button',name='Structured acceptance',exact=True).click()
                    expect(page.get_by_role('dialog').get_by_text('Every 10 seconds',exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    price.get_by_role('button').click()
                    page.get_by_role('dialog').get_by_role('button',name='View history',exact=True).click()
                    expect(page.get_by_role('dialog').last.get_by_text('Current Price — observed history',exact=True)).to_be_visible()
                    page.keyboard.press('Escape');page.keyboard.press('Escape')
                    page.screenshot(path=str(output/'source-grouped.png'),full_page=True);report['screenshots'].append(str((output/'source-grouped.png').relative_to(ROOT)))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    expect(primary.get_by_role('heading',name='Secondary price',exact=True)).to_be_visible()
                    page.screenshot(path=str(output/'source-grouped-narrow.png'),full_page=True);report['screenshots'].append(str((output/'source-grouped-narrow.png').relative_to(ROOT)))
                    passed('Wireframe tile groups combine monitors, server search finds source/field names and handles no matches, icon refresh queues a check, and source/tile details retain schedules and keyboard history at desktop/390px')
                    page.close()

                    if args.with_models:
                        eventually(lambda:client.get('/api/runtime').json()['embedding']['status']=='ready',90)
                        eventually(lambda:client.post('/api/chat/test').status_code==200,120)
                        result=client.post('/api/chat',json={'message':'What is the Current Price?','source_ids':[source['id']]}).json()
                        assert result['status']=='answered' and result['citations'],result
                        assert all(c['capture_id'] or c['version_id'] for c in result['citations'])
                        passed('Native free Qwen chat selects immutable evidence with shared MiniLM available')
                    # Removal is a reversible user action; history/evidence remain addressable.
                    page=context.new_page();page.goto(base)
                    page.locator('.nav-item').filter(has_text='Sources').click()
                    page.locator('.source-select').filter(has_text='Structured acceptance').click()
                    page.get_by_role('button',name='Remove source',exact=True).click()
                    confirmation=page.get_by_role('dialog');expect(confirmation.get_by_text('Collected history',exact=False)).to_be_visible()
                    confirmation.get_by_role('button',name='Remove source',exact=True).click()
                    expect(confirmation).not_to_be_visible()
                    eventually(lambda:all(s['id']!=source['id'] for s in client.get('/api/list/sources').json()['items']))
                    assert client.get('/api/captures/'+original_capture).status_code==200
                    page.get_by_label('Source visibility').select_option('removed')
                    page.locator('.source-select').filter(has_text='Structured acceptance').click()
                    expect(page.get_by_text('History and evidence are retained.',exact=False)).to_be_visible()
                    page.get_by_role('button',name='Restore source',exact=True).click()
                    eventually(lambda:any(s['id']==source['id'] and s['paused'] for s in client.get('/api/list/sources').json()['items']))
                    page.get_by_label('Source visibility').select_option('active')
                    page.locator('.source-select').filter(has_text='Structured acceptance').click()
                    page.get_by_role('tab',name='Configuration',exact=True).click()
                    expect(page.get_by_role('button',name='Resume monitoring',exact=True)).to_be_visible()
                    passed('Remove/restore UI retains immutable evidence, hides active source and restores with monitoring paused')
                    assert report.get('series_requests',0)==0,report
                    assert not report['console_errors'],report['console_errors']
                    browser.close()
        finally:owned.close()
    report['status']='passed';target=ROOT/'docs/verification'/('browser-models.json' if args.with_models else 'browser-no-models.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
    print('Browser acceptance report: '+str(target.relative_to(ROOT)),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
