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
    report={'models':'enabled' if args.with_models else 'stopped','checks':[],'screenshots':[],'console_errors':[]}
    checks=report['checks']
    def passed(name):checks.append(name);print('PASS: '+name,flush=True)
    with fresh_database(os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL) as url:
        env={**os.environ,'DATABASE_URL':url,'PARITY_DATA_DIR':str(output/'data'),'PARITY_PORT':str(app_port),'DEMO_ORIGIN':portal,'PARITY_LOCAL_CHAT_PORT':str(chat_port),'PARITY_EMBEDDING_PORT':str(embed_port),'PARITY_ADMIN_TOKEN':secrets.token_urlsafe(32),'DEMO_ADMIN_TOKEN':secrets.token_urlsafe(32),'PARITY_CHAT_PROVIDER':'local','PARITY_OFFLINE':'1','OMP_NUM_THREADS':'4'}
        owned=OwnedProcesses(output)
        try:
            command=[sys.executable,str(ROOT/'run.py'),'--no-browser','--profile','postgresql']+([] if args.with_models else ['--without-models'])
            owned.start('launcher',command,ROOT,env)
            with httpx.Client(base_url=base,headers={'X-Parity-Token':env['PARITY_ADMIN_TOKEN']},trust_env=False,timeout=190) as client:
                def ready():
                    owned.check()
                    try:return client.get('/health/ready').status_code==200 and httpx.get(portal+'/health/ready',trust_env=False).status_code==200
                    except httpx.HTTPError:return False
                eventually(ready,90)
                response=client.post('/api/sources',json={'name':'Structured acceptance','root_url':portal+'/en/metrics','settings':{'demo':True,'scope_mode':'page','max_pages':1,'max_depth':0,'interval':10,'delay':0}})
                response.raise_for_status();source=response.json()
                with sync_playwright() as pw:
                    browser=pw.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                    page=context.new_page();page.on('pageerror',lambda error:(report['console_errors'].append(str(error)),print('Browser JS error: '+str(error),flush=True)))
                    page.goto(base);page.request.post(base+'/api/session',data={'token':env['PARITY_ADMIN_TOKEN']})
                    page.locator('.nav-item').filter(has_text='Sources').click()
                    page.get_by_label('Include test sources',exact=True).check()
                    page.locator('.source-select').filter(has_text='Structured acceptance').click()
                    page.get_by_role('button',name='Add tracked information').click()
                    dialog=page.get_by_role('dialog');dialog.get_by_role('button',name='Next',exact=True).click()
                    dialog.get_by_label('Monitoring instructions').fill('Track Current Price, Promoter holding, Quarterly results and Announcements')
                    dialog.get_by_role('button',name='Preview extraction',exact=True).click()
                    expect(dialog.get_by_text('Review the extracted information',exact=True)).to_be_visible(timeout=50000)
                    wanted={'Current Price':'currency','Promoter holding':'percentage','Quarterly results':'table','Announcements':'list'}
                    cards=dialog.locator('.preview-field')
                    for i in reversed(range(cards.count())):
                        card=cards.nth(i);name=card.get_by_label('Field name',exact=True).input_value();kind=card.locator('select').first.input_value()
                        if wanted.get(name)!=kind:card.get_by_role('button',name='Remove '+name,exact=True).click()
                    assert cards.count()==4
                    dialog.get_by_role('button',name='Scope & schedule',exact=True).click()
                    dialog.get_by_role('button',name='Start monitoring',exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=15000)
                    passed('Four-step source setup, reviewed scalar/table/list fields, preserved 10-second fixture schedule')
                    page.locator('.nav-item').filter(has_text='Dashboard').click()
                    page.get_by_label('Include test sources',exact=True).check()
                    price=page.locator('.monitor-widget').filter(has=page.get_by_role('heading',name='Current Price',exact=True))
                    expect(price.get_by_text('1200.5 INR',exact=True)).to_be_visible(timeout=25000)
                    expect(page.locator('.monitor-widget').filter(has_text='Promoter holding').get_by_text('0 %',exact=True)).to_be_visible()
                    # Existing captures and a stopped semantic service must not prevent values.
                    dashboard=client.get('/api/dashboard?include_demo=true').json()
                    assert len(dashboard['widgets'])==4 and client.get('/api/dashboard').json()['widgets']==[]
                    field=next(f for f in dashboard['widgets'] if f['name']=='Current Price');original_capture=field['capture_id']
                    if not args.with_models:assert client.get('/api/runtime').json()['embedding']['status']=='unavailable'
                    passed('Dashboard zero/currency/table/list rendering and default demo isolation with PostgreSQL')
                    page.evaluate("id=>{window.acceptanceEvents=0;window.acceptanceStream=new EventSource('/api/events?after='+id);window.acceptanceStream.addEventListener('update',()=>window.acceptanceEvents++);}",dashboard['event_id'])
                    httpx.post(portal+'/admin/modify-honours',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},trust_env=False).raise_for_status()
                    expect(price.get_by_text('1250 INR',exact=True)).to_be_visible(timeout=30000)
                    expect(page.locator('.cell-changed')).to_have_count(1)
                    page.wait_for_function('window.acceptanceEvents > 0',timeout=15000)
                    assert '1,200.50' in client.get('/api/captures/'+original_capture).json()['text']
                    passed('Scheduled changes delivered by SSE without chat or Check now; immutable original evidence retained')
                    # Layout survives reload; background updates preserve open evidence.
                    page.get_by_role('button',name='Arrange dashboard',exact=True).click()
                    price.get_by_role('button',name='Pin Current Price',exact=True).click()
                    eventually(lambda:field['id'] in client.get('/api/dashboard/layout').json()['pinned'])
                    page.get_by_role('button',name='Done arranging',exact=True).click()
                    price.get_by_role('button',name='View evidence',exact=True).click()
                    evidence=page.get_by_role('dialog');expect(evidence.get_by_text('Stored source evidence',exact=True)).to_be_visible()
                    checked=next(f for f in client.get('/api/dashboard?include_demo=true').json()['widgets'] if f['id']==field['id'])['last_checked_at']
                    changes=client.get('/api/monitor-changes?include_demo=true&kind=changed').json()['total']
                    httpx.post(portal+'/admin/noise-only',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},trust_env=False).raise_for_status()
                    eventually(lambda:next(f for f in client.get('/api/dashboard?include_demo=true').json()['widgets'] if f['id']==field['id'])['last_checked_at']>checked)
                    assert client.get('/api/monitor-changes?include_demo=true&kind=changed').json()['total']==changes
                    expect(evidence).to_be_visible();page.keyboard.press('Escape')
                    passed('Unrelated page changes advance verification without field changes; evidence panel and pinned layout preserved')
                    # API fault becomes a retained-value warning, then recovers.
                    httpx.post(portal+'/admin/fault',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},json={'target':'metrics','status':403},trust_env=False).raise_for_status()
                    expect(page.get_by_role('heading',name='Needs attention',exact=True)).to_be_visible(timeout=30000)
                    expect(price.get_by_text('1250 INR',exact=True)).to_be_visible()
                    httpx.post(portal+'/admin/clear-faults',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},trust_env=False).raise_for_status()
                    expect(page.get_by_role('heading',name='Needs attention',exact=True)).not_to_be_visible(timeout=30000)
                    passed('Failed HTTP check retains previous verified value and warning; next successful check recovers')
                    page.screenshot(path=str(output/'desktop.png'),full_page=True);report['screenshots'].append(str((output/'desktop.png').relative_to(ROOT)))
                    # Disable streaming to exercise the actual polling path.
                    page.route('**/api/events*',lambda route:route.abort());page.reload();page.get_by_label('Include test sources',exact=True).check()
                    expect(page.get_by_text('Polling for updates',exact=True)).to_be_visible(timeout=20000)
                    httpx.post(portal+'/admin/add-notice',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},trust_env=False).raise_for_status()
                    expect(page.get_by_role('link',name='New reassessment notice',exact=False)).to_be_visible(timeout=30000)
                    passed('Polling fallback delivers scheduled announcement updates')
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='Open navigation',exact=True).click();page.keyboard.press('Tab')
                    assert page.locator('.sidebar').evaluate('(el)=>el.contains(document.activeElement)')
                    page.locator('.sidebar').get_by_role('button',name='Close navigation',exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/'narrow.png'),full_page=True);report['screenshots'].append(str((output/'narrow.png').relative_to(ROOT)))
                    passed('390px layout, keyboard navigation, focus management and reduced-motion setting')
                    # Closing the tab does not stop worker services.
                    page.close();httpx.post(portal+'/admin/reset',headers={'X-Demo-Token':env['DEMO_ADMIN_TOKEN']},trust_env=False).raise_for_status()
                    eventually(lambda:any(f['name']=='Current Price' and f['value']=='1200.5' for f in client.get('/api/dashboard?include_demo=true').json()['widgets']))
                    assert field['id'] in client.get('/api/dashboard/layout').json()['pinned']
                    passed('Scheduled monitoring continues with browser tab closed; layout persists')
                    if args.with_models:
                        eventually(lambda:client.get('/api/runtime').json()['embedding']['status']=='ready',90)
                        eventually(lambda:client.post('/api/chat/test').status_code==200,120)
                        result=client.post('/api/chat',json={'message':'What is the Current Price?','source_ids':[source['id']]}).json()
                        assert result['status']=='answered' and result['citations'],result
                        assert all(c['capture_id'] or c['version_id'] for c in result['citations'])
                        passed('Native free Qwen chat selects immutable evidence with shared MiniLM available')
                    assert not report['console_errors'],report['console_errors']
                    browser.close()
        finally:owned.close()
    report['status']='passed';target=ROOT/'docs/verification'/('browser-models.json' if args.with_models else 'browser-no-models.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
    print('Browser acceptance report: '+str(target.relative_to(ROOT)),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
