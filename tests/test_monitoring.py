import copy
import time
import pytest
from sqlalchemy import select
from parity import config, monitor_schema as ms
from parity.db import DB
from parity.fetch import Response
from parity.monitoring import MonitorService
from parity.service import Service
from parity.structured import discover, extract_field, normalize, soup_for, suggest


HTML = '''<!doctype html><html><body><h1>Company</h1>
<ul id="metrics"><li><span class="name">Current Price</span><span class="value">Rs. 1,200.50</span></li>
<li><span class="name">Promoter holding</span><span class="value">0%</span></li></ul>
<h2>Quarterly results</h2><table id="quarterly"><caption>Figures in Rs. Crores</caption>
<tr><th>Metric</th><th>Mar 2026</th><th>Jun 2026</th></tr>
<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr><tr><td>Net Profit</td><td>10</td><td>0</td></tr></table>
<h2>Announcements</h2><ul id="news"><li><a href="/notice/a">First notice</a></li><li><a href="/notice/b">Second notice</a></li></ul>
<time id="deadline" datetime="2026-10-20">Deadline</time><footer>Footer 1</footer></body></html>'''
URL = 'https://fixture.example/company/'


class FixtureFetcher:
    demo_origin = 'http://127.0.0.1:8080'
    body = HTML
    def addresses(self, url, source):
        return ['93.184.216.34']
    def get(self, url, source, **kwargs):
        return Response(url, 200, {'content-type': 'text/html'}, self.body.encode())


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.delenv('PARITY_LOCAL_CHAT_TOKEN', raising=False)
    fetcher = FixtureFetcher()
    service = Service(DB('sqlite:///'+str(tmp_path/'monitor.db')), fetcher=fetcher)
    def unavailable():
        raise AssertionError('Monitoring must not load an embedding model')
    monkeypatch.setattr(service, 'model', unavailable)
    return MonitorService(service), fetcher


def setup_monitor(monitor, names=('Current Price', 'Promoter holding')):
    m, fetcher = monitor
    draft = m.preview({'name': 'Company', 'root_url': URL, 'instructions': 'Track current price and promoter holding', 'use_ai': False})
    fields = [candidate for candidate in draft['candidates'] if candidate['name'] in names]
    result = m.activate({'draft_id': draft['draft_id'], 'name': 'Company', 'fields': fields})
    return m, result, fields


def test_discovery_and_typed_fields():
    candidates = discover(HTML, URL)
    price = next(item for item in candidates if item['name'] == 'Current Price')
    assert price['valid'] and price['preview']['value'] == '1200.5'
    assert price['preview']['unit'] == 'INR'
    zero = next(item for item in candidates if item['name'] == 'Promoter holding')
    assert zero['preview']['value'] == '0' and zero['preview']['unit'] == '%'
    quarterly = next(item for item in candidates if item['type'] == 'table')
    assert quarterly['preview']['value']['rows'][0]['cells'][1]['period'] == 'Jun 2026'
    assert quarterly['preview']['unit'] == 'INR crore'
    assert any(item['name'] == 'Current Price' for item in suggest(candidates, 'Track the displayed price'))


@pytest.mark.parametrize('raw,kind,expected', [('0', 'number', '0'), ('(12.30)', 'number', '-12.3'), ('₹ 1,200 Cr.', 'currency', '1200'), ('20 October 2026', 'date', '2026-10-20')])
def test_normalization(raw, kind, expected):
    assert normalize(raw, kind)[0] == expected


@pytest.mark.parametrize('raw,kind', [('N/A','number'), ('','number'), ('1 / 2','number'), ('10/11/2026','date'), ('NaN','number')])
def test_ambiguous_values_rejected(raw, kind):
    with pytest.raises(ValueError):
        normalize(raw, kind)


def test_model_free_activation_change_failure_recovery_and_evidence(monitor):
    m, activated, _ = setup_monitor(monitor)
    src = activated['source']
    baseline = m.dashboard()['widgets'][0]
    capture_id = baseline['capture_id']
    m.process_capture(src, 'check-1', Response(URL, 200, {'content-type':'text/html'}, HTML.replace('Footer 1', 'Footer 2').encode()))
    unchanged = next(item for item in m.dashboard()['widgets'] if item['id'] == baseline['id'])
    assert unchanged['last_changed_at'] == baseline['last_changed_at']
    assert unchanged['last_verified_at'] >= baseline['last_verified_at']
    changed = HTML.replace('Rs. 1,200.50', 'Rs. 1,250')
    first = m.process_capture(src, 'check-2', Response(URL, 200, {'content-type':'text/html'}, changed.encode()))
    assert first['changed'] == 1
    assert m.process_capture(src, 'check-2', Response(URL, 200, {'content-type':'text/html'}, changed.encode()))['observations'] == 0
    price = next(item for item in m.dashboard()['widgets'] if item['name'] == 'Current Price')
    assert price['value'] == '1250'
    verified = price['last_verified_at']
    m.process_error(src, 'check-3', URL, 'The website returned 503.', 503)
    stale = next(item for item in m.dashboard()['widgets'] if item['name'] == 'Current Price')
    assert stale['value'] == '1250' and stale['last_verified_at'] == verified and stale['status'] == 'stale'
    m.process_capture(src, 'check-4', Response(URL,200,{'content-type':'text/html'},changed.encode()))
    assert m.history(price['id'])['items'][0]['kind'] == 'recovered'
    assert '1,200.50' in m.evidence(capture_id)['text']
    assert m.changes()['total'] >= 5


def test_attribute_change_independent_of_visible_text(monitor):
    m, fetcher = monitor
    draft = m.preview({'root_url': URL, 'instructions':'Deadline', 'use_ai':False})
    field = next(item for item in draft['candidates'] if item['rule'].get('attribute') == 'datetime')
    result = m.activate({'draft_id':draft['draft_id'], 'fields':[field]})
    changed = HTML.replace('datetime="2026-10-20"','datetime="2026-10-28"')
    assert soup_for(HTML).get_text() == soup_for(changed).get_text()
    assert m.process_capture(result['source'],'attributes',Response(URL,200,{'content-type':'text/html'},changed.encode()))['changed'] == 1
    assert m.dashboard()['widgets'][0]['value'] == '2026-10-28'


def test_list_reorder_and_removal_semantics(monitor):
    m, fetcher = monitor
    draft = m.preview({'root_url':URL,'instructions':'Announcements','use_ai':False})
    field = next(item for item in draft['candidates'] if item['type']=='list' and item['rule']['selector']=='#news')
    activated = m.activate({'draft_id':draft['draft_id'],'fields':[field]})
    before = '<li><a href="/notice/a">First notice</a></li><li><a href="/notice/b">Second notice</a></li>'
    reversed_html = HTML.replace(before,'<li><a href="/notice/b">Second notice</a></li><li><a href="/notice/a">First notice</a></li>')
    assert m.process_capture(activated['source'],'reverse',Response(URL,200,{},reversed_html.encode()))['changed']==0
    removed = HTML.replace('<li><a href="/notice/a">First notice</a></li>','')
    assert m.process_capture(activated['source'],'remove',Response(URL,200,{},removed.encode()))['changed']==1
    detail = m.changes()['items'][0]['detail']
    assert detail['no_longer_listed'][0]['url']=='https://fixture.example/notice/a'
    assert 'deleted' not in detail


def test_latest_period_is_explicit_and_detected(monitor):
    m, fetcher = monitor
    draft = m.preview({'root_url':URL,'instructions':'Revenue','use_ai':False})
    field = next(item for item in draft['candidates'] if item['rule'].get('row')=='Revenue')
    assert field['rule']['period_mode']=='fixed'
    field['rule']['period_mode']='latest'
    activated = m.activate({'draft_id':draft['draft_id'],'fields':[field]})
    changed = HTML.replace('<th>Jun 2026</th>','<th>Jun 2026</th><th>Sep 2026</th>').replace('<td>1,200</td>','<td>1,200</td><td>1,400</td>').replace('<td>0</td>','<td>0</td><td>20</td>')
    m.process_capture(activated['source'],'next-quarter',Response(URL,200,{},changed.encode()))
    row = m.dashboard()['widgets'][0]
    assert row['value']=='1400' and row['period']=='Sep 2026'
    assert m.history(row['id'])['items'][0]['kind']=='new_period'


def test_invalid_activation_missing_and_revision_history(monitor):
    m, activated, initial_fields = setup_monitor(monitor)
    src=activated['source']
    frozen=m.snapshot_revisions(src['id'])
    draft=m.preview({'source_id':src['id'],'instructions':'Track price','use_ai':False})
    wrong=copy.deepcopy(initial_fields[0]);wrong['rule']['selector']='#missing'
    with pytest.raises(ValueError,match='successful extraction preview'):
        m.revise(activated['monitor']['id'],{'draft_id':draft['draft_id'],'fields':[wrong]})
    modified=copy.deepcopy(initial_fields[0]);modified['name']='Share price'
    revision=m.revise(activated['monitor']['id'],{'draft_id':draft['draft_id'],'fields':[modified]})
    assert revision['monitor']['revision_number']==2
    assert m.dashboard()['widgets'][0]['name']=='Share price'
    assert m.history(m.dashboard()['widgets'][0]['id'])['total']==2
    m.process_capture(src,'old-revision',Response(URL,200,{},HTML.replace('Rs. 1,200.50','Rs. 999').encode()),revisions=frozen)
    assert m.dashboard()['widgets'][0]['value']=='1200.5'
    broken=HTML.replace('class="value"','class="changed"')
    m.process_capture(src,'broken',Response(URL,200,{},broken.encode()))
    widget=m.dashboard()['widgets'][0]
    assert widget['status']=='missing' and widget['value']=='1200.5'
    assert len(m.dashboard()['attention'])==1


def test_scope_layout_pause_and_pagination(monitor):
    m, fetcher=monitor
    draft=m.preview({'root_url':URL,'instructions':'Track price','use_ai':False})
    assert draft['source']['config']['max_pages']==1 and draft['source']['config']['max_depth']==0
    assert draft['source']['config']['interval']==900
    assert draft['scope']['included']==[URL] and draft['scope']['excluded']
    result=m.activate({'draft_id':draft['draft_id'],'fields':draft['fields']})
    field=m.dashboard()['widgets'][0]['id']
    assert m.layout({'pinned':[field],'hidden':[],'order':[field]})['pinned']==[field]
    m.set_paused(result['monitor']['id'],True)
    assert m.snapshot_revisions(result['source']['id'])==[]
    assert m.dashboard()['monitors'][0]['paused'] is True
    m.set_paused(result['monitor']['id'],False)
    assert len(m.snapshot_revisions(result['source']['id']))==1
    m.process_capture(result['source'],'more',Response(URL,200,{},HTML.encode()))
    first=m.history(field,limit=1)
    second=m.history(field,limit=1,cursor=first['next_cursor'])
    assert first['total']==2 and second['items'][0]['id']!=first['items'][0]['id']
    assert m.events_since(0)
