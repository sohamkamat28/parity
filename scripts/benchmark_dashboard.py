"""Compare dashboard service calls on the same isolated PostgreSQL workload.

Run once with --source-root pointing at an archived baseline revision and once
against the current checkout. No network, model calls, or installation data.
"""
import argparse,json,math,os,platform,statistics,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root',default=str(ROOT));p.add_argument('--mode',choices=['history','series'],required=True)
p.add_argument('--database-env',default='DATABASE_URL');p.add_argument('--output',required=True)
a=p.parse_args();sys.path.insert(0,str(Path(a.source_root).resolve()))
from parity import config,monitor_schema as ms
from parity.db import DB
from parity.service import Service
from parity.monitoring import MonitorService
from parity.fetch import Response
from sqlalchemy import event,select
sys.path.append(str(ROOT/'scripts'))
from benchmark_v2 import fresh_database

class Fixture:
    fixture_origin=None
    calls=0
    body='<html><body>'+''.join(f'<p><span>Metric {i}</span><output id="v{i}">{i}</output></p>' for i in range(40))+'</body></html>'
    def addresses(self,*args):return ['93.184.216.34']
    def get(self,url,*args,**kwargs):
        self.calls+=1
        return Response(url,200,{'content-type':'text/html'},self.body.encode())

with tempfile.TemporaryDirectory(prefix='parity-dashboard-') as temporary,fresh_database(os.environ[a.database_env]) as url:
    config.DATA=Path(temporary);db=DB(url);fetcher=Fixture();service=Service(db,fetcher=fetcher);m=MonitorService(service)
    fields=[dict(id=f'field-{i}',name=f'Metric {i}',type='number',rule={'kind':'scalar','selector':f'#v{i}'}) for i in range(40)]
    started=time.perf_counter();draft=m.preview(dict(root_url='https://fixture.example/',instructions='Track metrics',fields=fields,use_ai=False))
    activated=m.activate(dict(draft_id=draft['draft_id'],fields=draft['fields']));setup_ms=(time.perf_counter()-started)*1000
    original=db.all(select(ms.monitor_observations));start=time.time()-7*86400;rows=[]
    for index in range(500):
        for field,record in enumerate(original):
            rows.append({**record,'id':f'{index:04}-{field:02}','at':start+index*(7*86400/500),'value':str(round(math.sin(index/7)*100+field,4))})
    with db.tx() as c:
        c.execute(ms.monitor_observations.delete())
        for offset in range(0,len(rows),1000):c.execute(ms.monitor_observations.insert(),rows[offset:offset+1000])
    identities=[dict(monitor_id=record['monitor_id'],field_id=record['field_id']) for record in original]
    def measure(fn):
        calls=[]
        def count(*args):calls.append(1)
        event.listen(db.engine,'before_cursor_execute',count)
        try:
            began=time.perf_counter();result=fn();elapsed=(time.perf_counter()-began)*1000
        finally:event.remove(db.engine,'before_cursor_execute',count)
        return dict(ms=round(elapsed,3),sql_queries=len(calls),json_bytes=len(json.dumps(result,default=str).encode()))
    dashboard=[measure(m.dashboard) for _ in range(6)]
    if a.mode=='series':
        from parity.series import dashboard_series
        def graphs():return dashboard_series(service,dict(fields=identities,start=start,end=start+7*86400))
    else:
        def graphs():return [m.history(f['field_id'],200,monitor_id=f['monitor_id']) for f in identities]
    graphs_runs=[measure(graphs) for _ in range(6)]
    report=dict(mode=a.mode,device=dict(os=platform.platform(),cpu=platform.machine(),python=platform.python_version()),
        corpus=dict(fields=40,observations_per_field=500,total_observations=len(rows),range_days=7),
        setup=dict(ms=round(setup_ms,3),fetch_calls=fetcher.calls),dashboard=dashboard,graphs=graphs_runs,
        summary=dict(dashboard_warm_median_ms=statistics.median(r['ms'] for r in dashboard[1:]),graphs_warm_median_ms=statistics.median(r['ms'] for r in graphs_runs[1:]),graph_service_calls=1 if a.mode=='series' else 40),
        notes=['First call and five repeats; OS/database caches are not flushed.','Baseline returns the newest 200 observations per field. Series samples the full requested range.','Timings exclude HTTP transport and browser rendering.'])
    db.engine.dispose()
Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report['summary']))
