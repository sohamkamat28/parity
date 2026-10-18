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
    def get(self, url, source, headers=None, **kwargs):
        return Response(url, 200, {'content-type': 'text/html'}, self.body.encode())


@pytest.fixture
def monitor(tmp_path, monkeypatch, database_url):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.delenv('PARITY_LOCAL_CHAT_TOKEN', raising=False)
    fetcher = FixtureFetcher()
    service = Service(DB(database_url), fetcher=fetcher)
    def unavailable():
        raise AssertionError('Monitoring must not load an embedding model')
    monkeypatch.setattr(service, 'model', unavailable)
    yield MonitorService(service), fetcher
    service.db.engine.dispose()


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

@pytest.mark.parametrize('markup,instruction,expected',[
    ('<main><h1>Widget</h1><p class="price_color">£51.77</p></main>', 'Track the current price', '51.77'),
    ('<div><span>Revenue</span><strong>1200</strong></div>', 'Monitor revenue', '1200'),
    ('<p>Current price: $0</p>', 'Track current price', '0'),
    ('<section><h2>Current price</h2><div><span>$42.50</span></div></section>', 'Track price', '42.5'),
    ('<meta itemprop="price" content="19.99">', 'Track price', '19.99'),
])
def test_automatic_discovery_without_fixture_classes(markup,instruction,expected):
    fields=suggest(discover(markup,URL),instruction)
    assert len(fields)==1 and fields[0]['valid']
    assert fields[0]['preview']['value']==expected
    assert fields[0]['type'] in ('number','currency')
    assert extract_field(markup,fields[0],URL)['value']==expected


def test_automatic_rules_capture_changes_and_fail_on_shifted_labels():
    body='<section><span>Revenue</span><strong>1200</strong></section>'
    field=suggest(discover(body,URL),'Track revenue')[0]
    assert extract_field(body.replace('1200','1300'),field,URL)['value']=='1300'
    with pytest.raises(LookupError):extract_field(body.replace('Revenue','Expenses'),field,URL)
    assert not suggest(discover('<div hidden><p>Current price: $99</p></div>',URL),'Track price')


def test_automatic_setup_publishes_widgets_without_field_edits(monitor,monkeypatch):
    m,_=monitor
    monkeypatch.setattr(m,'_ai_suggest',lambda *args:[])  # A model may find no selection.
    draft=m.auto_preview({'root_url':URL,'instructions':'Track current price, promoter holding, quarterly results and announcements'})
    result=m.activate({'draft_id':draft['draft_id'],'fields':draft['fields']})
    widgets=m.dashboard()['widgets']
    assert {w['type'] for w in widgets}=={'currency','percentage','table','list'}
    assert len(widgets)==4 and all(w['capture_id'] for w in widgets)
    assert result['source']['config']['interval']==900
    again=m.activate({'draft_id':draft['draft_id'],'fields':draft['fields']})
    assert again['monitor']['id']==result['monitor']['id'] and len(m.dashboard()['widgets'])==4


def test_automatic_setup_chooses_rendering_only_when_needed(monitor,monkeypatch):
    from parity import browser
    m,fetcher=monitor;fetcher.body='<main>Loading…</main>';calls=[]
    def render(service,url,source):
        calls.append(source['config'])
        return Response(url,200,{'content-type':'text/html'},b'<p>Current price: $15</p>')
    monkeypatch.setattr(browser,'preview_capture',render)
    draft=m.auto_preview({'root_url':URL,'instructions':'Track price','use_ai':False})
    result=m.activate({'draft_id':draft['draft_id'],'fields':draft['fields']})
    assert len(calls)==1 and calls[0]['resource_origins']==[]
    assert result['source']['config']['render_mode']=='browser'
    assert m.dashboard()['widgets'][0]['value']=='15'


def test_unmatched_automatic_setup_never_activates_unrelated_values(monitor,monkeypatch):
    from parity import browser
    m,fetcher=monitor;fetcher.body='<p>Welcome</p>'
    monkeypatch.setattr(browser,'preview_capture',lambda *args:Response(URL,200,{},b'<p>Still no requested value</p>'))
    with pytest.raises(ValueError,match='could not identify'):
        m.auto_preview({'root_url':URL,'instructions':'Track price','use_ai':False})
    assert m.dashboard()['totals']['monitors']==0


def test_automatic_price_ignores_hidden_fields_and_table_header_periods():
    body='''<main><h1>Widget</h1><p class="price">£12</p>
    <table><tr><th>SKU</th><td>123456</td></tr><tr><th>Price (incl. tax)</th><td>£12</td></tr></table>
    <p hidden>Current price: £999</p></main>'''
    fields=suggest(discover(body,URL),'Track current price')
    assert len(fields)==1 and fields[0]['preview']['value']=='12'
    assert fields[0]['preview']['period']==''
    tax=suggest(discover(body,URL),'Track price including tax')
    assert all(f['preview']['period']=='' for f in tax)


def test_automatic_selection_omits_boilerplate_matching_generic_words():
    fields=suggest(discover(HTML+'<p>These are synthetic company results.</p>',URL),'Track current price, quarterly results and announcements')
    assert {f['type'] for f in fields}=={'currency','table','list'}
    assert len(fields)==3


def test_discovered_product_properties_follow_labels_after_reordering():
    price='<tr><th>Price</th><td>£12</td></tr>'
    stock='<tr><th>Stock</th><td>100</td></tr>'
    field=suggest(discover('<table>'+price+stock+'</table>',URL),'Track price')[0]
    assert extract_field('<table>'+stock+price+'</table>',field,URL)['value']=='12'
    with pytest.raises(LookupError):extract_field('<table>'+stock+'</table>',field,URL)


def test_automatic_price_does_not_activate_a_heading(monitor,monkeypatch):
    from parity import browser
    m,fetcher=monitor;fetcher.body='<h1>Current price</h1>'
    monkeypatch.setattr(browser,'preview_capture',lambda *args:Response(URL,200,{},b'<h1>Current price</h1>'))
    with pytest.raises(ValueError,match='could not identify'):
        m.auto_preview({'root_url':URL,'instructions':'Track current price','use_ai':False})
    assert m.dashboard()['totals']['monitors']==0
