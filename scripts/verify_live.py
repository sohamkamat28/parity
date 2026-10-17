"""Exercise the running Windows release using real models and real API requests.
Run with PARITY_ADMIN_TOKEN matching the current launcher. Never records secrets.
"""
import json,os,time,sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'verification';out.mkdir(exist_ok=True)
client=httpx.Client(base_url=os.getenv('PARITY_URL','http://127.0.0.1:8000'),trust_env=False,timeout=240,
    headers={'X-Parity-Token':os.environ['PARITY_ADMIN_TOKEN']})
records=[];state={}
def call(method,path,**kwargs):
    r=client.request(method,path,**kwargs);r.raise_for_status();return r.json()
def record(name,fn):
    tick=time.perf_counter()
    try:
        detail=fn();row={'name':name,'passed':True,'seconds':round(time.perf_counter()-tick,2),'detail':detail}
    except Exception as error:
        row={'name':name,'passed':False,'seconds':round(time.perf_counter()-tick,2),'error':str(error)[:1500]}
    records.append(row);(out/'live-results.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(json.dumps(row),flush=True)
    if not row['passed']:raise RuntimeError('Verification failed: '+name)
def wait(run):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        row=call('GET','/api/crawl-runs/'+run['id'])
        if row['status'] not in ('queued','running'):return row
        time.sleep(.4)
    raise TimeoutError('Crawl did not finish')
def action(name,**body):
    result=call('POST','/api/demo/sessions/'+state['session']['id']+'/actions/'+name,json=body)
    return wait(result['runs'][0]) if result['runs'] else result
def pages():return [p for p in call('GET','/api/overview')['pages'] if p['source_id']==state['session']['static_source_id']]
def search(query,**kwargs):return call('POST','/api/search',json={'query':query,'source_ids':[state['session']['static_source_id']],**kwargs})['results']
def ask(message,**kwargs):return call('POST','/api/chat',json={'message':message,'source_ids':[state['session']['static_source_id']],**kwargs})
def initial():
    state['session']=call('POST','/api/demo/sessions',json={'name':'Verified Windows presentation'})
    r=action('baseline');assert r['status']=='succeeded' and r['metrics']['created']==3,r
    state['honours']=next(p for p in pages() if 'honours' in p['url']);state['scholarship']=next(p for p in pages() if 'scholarship' in p['url'])
    state['as_of']=time.time();return r['metrics']
def original_chat():
    r=ask('What is the honours registration deadline?');assert '20 August' in r['answer'] and r['citations'],r
    assert all(c['number']==1 and c['version_id'] for c in r['citations']);state['conversation']=r['conversation_id'];return r
def update():
    r=action('modify-honours');assert r['metrics']['modified']==1,r
    diff=call('GET',f"/api/pages/{state['honours']['id']}/diff?v1=1&v2=2")
    assert '-Registration closes on 20 August' in diff['diff'] and '+Registration closes on 28 August' in diff['diff'] and 'NOC' in diff['diff'],diff
    return diff
def updated_chat():
    r=ask('What is the deadline now, and which new document is required?',conversation_id=state['conversation'])
    assert '28 August' in r['answer'] and 'NOC' in r['answer'] and any(c['number']==2 for c in r['citations']) and 'scholarship' not in r['answer'].lower(),r
    return r
def historical():
    hits=search('honours registration deadline',mode='as_of',as_of=state['as_of'])
    assert any('20 August' in h['text'] and h['number']==1 for h in hits),hits
    r=ask('What was the honours registration deadline?',mode='as_of',as_of=state['as_of'])
    assert '20 August' in r['answer'] and r['citations'],r
    for c in r['citations']:
        page=call('GET',f"/api/pages/{c['page_id']}?version={c['number']}");assert page['version']['id']==c['version_id']
    return r
def noise():
    r=action('noise-only');assert r['metrics']['modified']==0 and r['metrics']['new_vectors']==0,r;return r['metrics']
def pdf():
    first=action('add-notice');assert first['metrics']['created']==2,first
    pdf=next(p for p in pages() if p['url'].endswith('.pdf'))
    second=action('modify-pdf');assert second['metrics']['modified']==1,second
    diff=call('GET',f"/api/pages/{pdf['id']}/diff?v1=1&v2=2");assert '7 October' in diff['diff']
    hits=search('innovation grant application deadline');assert any(h['url'].endswith('.pdf') and h['number']==2 for h in hits),hits
    return {'published':first['metrics'],'revised':second['metrics'],'diff':diff}
def javascript():
    session=state['session'];source=next(s for s in call('GET','/api/sources') if s['id']==session['browser_source_id'])
    shell=client.get(source['root_url']).content
    first=action('crawl-browser');assert first['metrics']['created']==2,first
    changed=action('modify-live');assert changed['metrics']['modified']==1,changed
    assert shell==client.get(source['root_url']).content
    hits=call('POST','/api/search',json={'query':'innovation lab application deadline','source_ids':[session['browser_source_id']]})['results']
    assert any('25 November' in h['text'] and h['number']==2 for h in hits),hits
    return {'baseline':first['metrics'],'changed':changed['metrics'],'shell_unchanged':True}
def deletion():
    first=action('delete-scholarship');pid=state['scholarship']['id']
    assert first['metrics']['missing']==1,first
    assert not any(h['page_id']==pid for h in search('scholarship renewal'))
    time.sleep(2.1);second=action('crawl');time.sleep(2.1);third=action('crawl')
    assert third['metrics']['deleted']==1,third
    state['gap']=time.time();restored=action('restore-scholarship');assert restored['metrics']['restored']==1,restored
    assert not any(h['page_id']==pid for h in search('scholarship renewal',mode='as_of',as_of=state['gap']))
    return {'first':first['metrics'],'second':second['metrics'],'confirmed':third['metrics'],'restored':restored['metrics']}
def transient():
    before=call('GET','/api/pages/'+state['honours']['id'])['page'];r=action('fault',target='honours-registration',status=503)
    after=call('GET','/api/pages/'+state['honours']['id'])['page']
    assert before['verified_at']==after['verified_at'] and before['current_id']==after['current_id'] and after['health']=='error'
    assert any(h['page_id']==before['id'] for h in search('honours deadline'))
    action('clear-faults');return {'metrics':r['metrics'],'verified_at_unchanged':True,'version_retained':True}
def schedule():
    sid=state['session']['static_source_id'];call('PATCH','/api/sources/'+sid,json={'paused':False})
    # Reset creates a true content change without an explicit enqueue.
    action('reset',crawl=False);deadline=time.monotonic()+45
    try:
        while time.monotonic()<deadline:
            p=call('GET','/api/pages/'+state['honours']['id'])
            if p['version'] and '20 August' in p['version']['content'] and p['version']['number']>2:
                return {'detected_version':p['version']['number'],'seconds_limit':45}
            time.sleep(1)
        raise AssertionError('Scheduler did not detect update')
    finally:call('PATCH','/api/sources/'+sid,json={'paused':True})
def public_sites():
    result=[]
    for mode,url in [('static','https://quotes.toscrape.com/'),('browser','https://quotes.toscrape.com/js/')]:
        source=call('POST','/api/sources',json={'name':'Public '+mode+' verification','root_url':url,'settings':{'selector':'.quote','render_mode':mode,'ready_selector':'.quote' if mode=='browser' else '', 'max_pages':1,'max_depth':0,'allow':['/'],'deny':['/login'],'delay':.5}})
        run=wait(call('POST','/api/sources/'+source['id']+'/crawl',json={}))
        observations=call('GET','/api/crawl-runs/'+run['id']+'/observations')
        result.append({'mode':mode,'url':url,'run':run,'observations':observations})
    (out/'public-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    assert all(r['run']['metrics']['created']>=1 for r in result),result
    return result
def mcp_check():
    result=call('POST','/api/integrations/mcp/test',json={})
    assert result['status']=='passed' and len(result['tools'])==5,result
    return result

if __name__=='__main__':
    record('runtime readiness',lambda:call('GET','/api/runtime'))
    for name,fn in [('baseline with real MiniLM',initial),('free local cited chat v1',original_chat),('deadline and exact diff',update),('follow-up cited chat v2',updated_chat),('historical evidence and chat',historical),('footer noise',noise),('PDF versioning',pdf),('JavaScript JSON-only update',javascript),('missing deletion restoration gap',deletion),('transient failure',transient),('scheduled polling',schedule),('five-tool MCP protocol',mcp_check),('public static and rendered websites',public_sites)]:record(name,fn)
    (out/'session.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
