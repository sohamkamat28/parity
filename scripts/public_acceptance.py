"""Optional live-network extraction checks; no AI or embeddings required."""
import json
from pathlib import Path
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from parity import config
from parity.db import DB
from parity.service import Service
from parity.monitoring import MonitorService
from benchmark_v2 import fresh_database


def main():
    original=config.DATA;output=ROOT/'outputs/runtime'/('public-'+uuid.uuid4().hex);output.mkdir(parents=True);config.DATA=output
    report={'checked_at':time.time(),'optional_live_network':True,'results':[]}
    cases=[('https://books.toscrape.com/','currency',{'kind':'scalar','selector':'ol.row > li:first-child .price_color'}),('https://books.toscrape.com/','list',{'kind':'list','selector':'ol.row','item_selector':':scope > li'}),('https://www.w3schools.com/html/html_tables.asp','table',{'kind':'table','selector':'#customers'})]
    try:
        with fresh_database(config.DATABASE_URL) as url:
            db=DB(url);monitor=MonitorService(Service(db,inline_index=False))
            try:
                for url,kind,rule in cases:
                    row={'url':url,'type':kind,'rule':rule}
                    try:
                        preview=monitor.preview({'root_url':url,'use_ai':False,'fields':[{'id':'public-field','name':'Public '+kind,'type':kind,'rule':rule}]})
                        field=preview['fields'][0];assert field['valid'],field['error']
                        saved=monitor.activate({'draft_id':preview['draft_id']})
                        widget=monitor.dashboard(saved['source']['id'])['widgets'][0]
                        assert widget['capture_id'] and widget['value'] is not None
                        row.update(status='passed',normalized_sample=str(widget['value'])[:300],unit=widget['unit'])
                    except Exception as error:row.update(status='failed',error=str(error)[:500])
                    report['results'].append(row);print(json.dumps(row),flush=True)
            finally:db.engine.dispose()
    finally:config.DATA=original
    destination=ROOT/'docs/verification/public-pages.json';destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(report,indent=2)+'\n')
    return int(any(row['status']!='passed' for row in report['results']))


if __name__=='__main__':raise SystemExit(main())
