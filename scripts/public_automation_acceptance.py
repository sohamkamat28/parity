"""Optional real-page calculation rehearsal; uses disposable PostgreSQL and data.

Explicit test choices: PM session, INR per 10g gold, INR per kg silver. These are
supplied configuration, not claims that an LLM inferred an ambiguous denominator.
No notification destination is configured and no external POST is performed.
"""
import json,os,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from parity import config
from parity.db import DB
from parity.service import Service
from parity.fetch import Fetcher
from parity.monitoring import MonitorService
from parity.automation import Automations
from benchmark_v2 import fresh_database


def main():
    url='https://ibjarates.com/'
    instructions='Calculate the material cost of 20 grams of 916 gold, 10 grams of 750 gold and 500 grams of silver. Compare with my ₹5 lakh budget, graph the total, and alert me when it exceeds the budget.'
    report={'url':url,'optional_live_network':True,'at':time.time(),'profile':'postgresql','models':'stopped',
        'test_choices':{'session':'PM','gold_rate_unit':'INR/10g','silver_rate_unit':'INR/kg','budget':'500000 INR'},'external_notifications':False}
    original=config.DATA
    try:
        with tempfile.TemporaryDirectory(prefix='parity-public-calculation-') as temporary,fresh_database(os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL) as database_url:
            config.DATA=Path(temporary);db=DB(database_url)
            try:
                class CountedFetcher(Fetcher):
                    calls=0
                    def get(self,*args,**kwargs):
                        self.calls+=1
                        return super().get(*args,**kwargs)
                fetcher=CountedFetcher();service=Service(db,fetcher=fetcher,inline_index=False);monitor=MonitorService(service);worker=Automations(service)
                draft=monitor.auto_preview({'root_url':url,'instructions':instructions,'use_ai':False})
                report['initial_calculation_status']=draft['automation']['status']
                catalog=draft['automation']['catalog'];answers={}
                for index,name in enumerate(('Gold 916','Gold 750','Silver 999'),1):
                    choices=[f for f in catalog if f['name']==name+' — latest dated row PM']
                    assert len(choices)==1,(name,[f['name'] for f in catalog])
                    answers['field_'+str(index)]=choices[0]['id']
                    answers['unit_'+str(index)]='INR/10g' if index<3 else 'INR/kg'
                calculated=worker.preview({'instructions':instructions,'monitor_draft_id':draft['draft_id'],'answers':answers,'use_ai':False})
                assert calculated['status']=='ready',calculated.get('questions')
                activated=monitor.activate({'draft_id':draft['draft_id'],'fields':draft['fields'],'automation_draft_id':calculated['draft_id']})
                evaluation=worker.once();assert evaluation['status']=='ok',evaluation
                assert len({i['period'] for i in evaluation['inputs']})==1
                assert all(i['capture_id']==draft['capture_id'] for i in evaluation['inputs'])
                report.update(status='passed',page_fetch_calls=fetcher.calls,inputs=[{k:i[k] for k in ('name','value','unit','period')} for i in evaluation['inputs']],
                    outputs=[{k:o[k] for k in ('name','value','unit')} for o in evaluation['outputs']],questions_resolved=['publication session','price denominators'],
                    capture_reused_for_discovery_validation_calculation=True,personal_installation_modified=False)
            finally:db.engine.dispose()
    except Exception as error:
        report.update(status='failed',error=type(error).__name__+': '+str(error)[:1000])
    finally:config.DATA=original
    path=ROOT/'docs/verification/automation-public-preview.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
