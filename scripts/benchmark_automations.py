"""Isolated PostgreSQL measurements of calculations, series and committed alerts.

Finite synthetic workload; no public network, embeddings, model or user database.
Includes capture publication and sequential durable evaluation, not HTTP crawling
capacity or a prediction of deployment-wide throughput.
"""
import json,os,platform,statistics,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import event,select,func
from parity import config,automation_schema as a
from parity.db import DB
from parity.service import Service
from parity.monitoring import MonitorService
from parity.automation import Automations,definition_signature
from parity.series import dashboard_series
from parity.fetch import Response
from tests.test_monitoring import FixtureFetcher,HTML,URL
from benchmark_v2 import fresh_database


def main():
    output=ROOT/'outputs/runtime'/('automation-benchmark-'+uuid.uuid4().hex);output.mkdir(parents=True)
    original=config.DATA;config.DATA=output/'data';config.DATA.mkdir()
    result={'profile':'postgresql','fixture':'one price field, 20 automations, two arithmetic outputs and one threshold rule each; 12 alternating price checks',
        'models':'stopped','platform':platform.platform(),'python':platform.python_version(),
        'scope':'Sequential durable worker evaluation includes database publication; no network latency, true cold caches or total deployment memory measurement.'}
    try:
        with fresh_database(os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL) as url:
            db=DB(url);service=Service(db,fetcher=FixtureFetcher(),inline_index=False);monitor=MonitorService(service);worker=Automations(service)
            draft=monitor.preview({'root_url':URL,'instructions':'Track Current Price','use_ai':False})
            field=next(f for f in draft['candidates'] if f['name']=='Current Price')
            saved=monitor.activate({'draft_id':draft['draft_id'],'fields':[field]});field=saved['monitor']['fields'][0]
            plan={'version':1,'name':'Budget','inputs':[{'id':'price','name':'Current Price','monitor_id':saved['monitor']['id'],'field_id':field['id'],'signature':definition_signature(field),'unit':'INR'}],
                'parameters':[{'id':'quantity','name':'Quantity','value':'2','unit':''},{'id':'budget','name':'Budget','value':'2500','unit':'INR'}],
                'outputs':[{'id':'cost','name':'Estimated cost','expression':{'op':'multiply','args':[{'op':'input','id':'price'},{'op':'parameter','id':'quantity'}]},'display':'budget'},
                    {'id':'remaining','name':'Budget remaining','expression':{'op':'subtract','args':[{'op':'parameter','id':'budget'},{'op':'output','id':'cost'}]}}],
                'rules':[{'id':'over','name':'Over budget','condition':{'op':'gt','args':[{'op':'output','id':'cost'},{'op':'parameter','id':'budget'}]},'cooldown_seconds':0}]}
            ids=[]
            for index in range(20):
                plan['name']='Budget '+str(index+1)
                preview=worker.preview({'plan':plan,'instructions':'Fixture budget','use_ai':False})
                ids.append(worker.activate({'draft_id':preview['draft_id']})['id'])
            while worker.once():pass
            ticks=[];alert_ticks=[];processed=0
            for index in range(12):
                start=time.perf_counter();price='1500' if index%2 else '1000'
                monitor.process_capture(saved['source'],'benchmark-'+str(index),Response(URL,200,{'content-type':'text/html'},HTML.replace('Rs. 1,200.50','Rs. '+price).encode()))
                count=0
                while worker.once():count+=1
                elapsed=time.perf_counter()-start;ticks.append(elapsed);processed+=count
                if index%2:alert_ticks.append(elapsed)
            result.update(evaluations=processed,checks=12,automations=20,outputs=40,
                capture_to_last_evaluation_ms={'median':statistics.median(ticks)*1000,'max':max(ticks)*1000},
                capture_to_all_20_alerts_ms={'median':statistics.median(alert_ticks)*1000,'max':max(alert_ticks)*1000},
                observed_evaluations_per_second=processed/sum(ticks),alerts=db.one(select(func.count().label('n')).select_from(a.automation_alerts))['n'])
            measures=[]
            for count in (1,20):
                latencies=[];sql=[];sizes=[]
                for _ in range(5):
                    calls=[]
                    def before(*args):calls.append(1)
                    event.listen(db.engine,'before_cursor_execute',before)
                    start=time.perf_counter();page=worker.listing(limit=count);latencies.append((time.perf_counter()-start)*1000)
                    event.remove(db.engine,'before_cursor_execute',before);sql.append(len(calls));sizes.append(len(json.dumps(page).encode()))
                measures.append({'automations':count,'warm_median_ms':statistics.median(latencies),'sql_statements':sql,'response_bytes':sizes[-1]})
            result['dashboard_queries']=measures
            calls=[]
            def before(*args):calls.append(1)
            event.listen(db.engine,'before_cursor_execute',before)
            start=time.perf_counter();series=dashboard_series(service,{'fields':[{'kind':'calculated','automation_id':i,'field_id':'cost'} for i in ids]})
            series_ms=(time.perf_counter()-start)*1000;event.remove(db.engine,'before_cursor_execute',before)
            result['batched_series']={'fields':20,'sql_statements':len(calls),'elapsed_ms':series_ms,'response_bytes':len(json.dumps(series).encode()),'points':sum(len(r['points']) for r in series['items'])}
            db.engine.dispose()
    finally:config.DATA=original
    target=ROOT/'docs/verification/automation-benchmark.json';target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
