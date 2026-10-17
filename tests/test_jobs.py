"""Recovery and model-independent monitoring regression tests (no network)."""
import time
import pytest
from sqlalchemy import select,func
from parity import config
from parity.db import DB,sources,runs,pages,versions,chunks,events
from parity.service import Service
from parity.embedding import Embedder
from parity.fetch import Response
from parity.jobs import Jobs
from parity.job_schema import run_state,url_jobs,index_jobs,index_state,resource_locks,origin_locks


class FixtureFetcher:
    def __init__(self):
        self.demo_origin=config.DEMO_ORIGIN
        self.responses={};self.calls=[]
    def addresses(self,*args):return ['127.0.0.1']
    def get(self,url,source,headers=None):
        self.calls.append(url)
        value=self.responses.get(url,b'<html><body><article><h1>Notice</h1><p>Deadline 20 August</p></article></body></html>')
        return value if isinstance(value,Response) else Response(url,200,{'content-type':'text/html'},value)


class MonitorStub:
    def __init__(self):self.captures=[];self.errors=[];self.revisions=[{'revision_id':'original'}]
    def snapshot_revisions(self,source_id):return list(self.revisions)
    def process_capture(self,*args,**kwargs):self.captures.append((args,kwargs))
    def process_error(self,*args,**kwargs):self.errors.append((args,kwargs))


@pytest.fixture
def system(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    fetcher=FixtureFetcher();monitor=MonitorStub()
    monkeypatch.setattr(Jobs,'_monitor',lambda self:monitor)
    service=Service(DB('sqlite:///'+str(tmp_path/'jobs.db')),fetcher=fetcher,inline_index=False)
    source=service.add_source('Monitor',config.DEMO_ORIGIN+'/docs/one',{
        'demo':True,'delay':0,'scope_mode':'page','max_depth':0,'max_pages':1})
    return service,source,fetcher,monitor


def test_capture_is_model_independent_and_indexes_later(system,monkeypatch):
    service,source,fetcher,monitor=system
    def unavailable():raise RuntimeError('Model stopped')
    monkeypatch.setattr(service,'model',unavailable)
    result=service.run(service.enqueue(source['id'])['id'])
    assert result['status']=='succeeded'
    assert len(monitor.captures)==1
    version=service.db.one(select(versions))
    assert version['indexed_at'] is None
    assert service.db.all(select(chunks))==[]
    assert service.db.one(select(index_jobs))['status']=='queued'
    jobs=Jobs(service)
    failure=jobs.index_once()
    assert failure['error']=='Model stopped'
    assert service.db.one(select(index_state))['status']=='error'
    assert service.db.one(select(pages))['current_id']==version['id']
    monkeypatch.setattr(service,'model',lambda:Embedder('lexical'))
    with service.db.tx() as c:c.execute(index_jobs.update().values(available_at=0))
    assert jobs.index_once()['chunks']>0
    assert service.db.one(select(versions))['indexed_at'] is not None
    assert service.search('deadline',source_ids=[source['id']])['results']


def test_pending_current_never_returns_previous_evidence(system):
    service,source,fetcher,monitor=system
    service.embedder=Embedder('lexical')
    service.run(service.enqueue(source['id'])['id']);Jobs(service).index_once()
    old=service.db.one(select(versions))
    fetcher.responses[source['root_url']]=b'<html><body><article><h1>Notice</h1><p>Deadline 28 August</p></article></body></html>'
    result=service.run(service.enqueue(source['id'])['id'])
    assert result['metrics']['modified']==1
    current=service.db.one(select(pages))
    assert current['current_id']!=old['id']
    assert service.search('deadline',source_ids=[source['id']])['results']==[]
    assert service.get_page(current['id'])['version']['indexed_at'] is None


def test_retry_after_persists_without_blocking_other_origin(system):
    service,source,fetcher,monitor=system
    fetcher.responses[source['root_url']]=Response(source['root_url'],503,{'retry-after':'120'},b'')
    jobs=Jobs(service);run=service.enqueue(source['id']);jobs.initialize(run['id'])
    started=time.monotonic();result=jobs.capture_once(run['id'])
    assert time.monotonic()-started<2
    pending=service.db.one(select(url_jobs))
    assert pending['status']=='queued' and pending['available_at']>=time.time()+115
    assert result['status']=='running'
    # A second independent origin can proceed while the first origin waits.
    second=service.add_source('Other','https://other.example/docs',{'scope_mode':'page','max_pages':1,'max_depth':0})
    other=service.enqueue(second['id']);jobs.initialize(other['id'])
    claim=jobs.claim_capture(other['id'])
    assert claim and claim['source_id']==second['id']
    assert jobs.claim_capture(run['id']) is None


def expire_claim(service):
    with service.db.tx() as c:
        c.execute(url_jobs.update().where(url_jobs.c.status=='running').values(lease_until=0))
        c.execute(resource_locks.update().values(lease_until=0))
        c.execute(origin_locks.update().values(lease_until=0,next_allowed_at=0))


def test_crash_after_publish_resumes_without_duplicate_version(system,monkeypatch):
    service,source,fetcher,monitor=system
    jobs=Jobs(service);run=service.enqueue(source['id']);jobs.initialize(run['id'])
    original=service._observe
    def crash(*args,**kwargs):raise KeyboardInterrupt('simulated worker termination')
    monkeypatch.setattr(service,'_observe',crash)
    with pytest.raises(KeyboardInterrupt):jobs.capture_once(run['id'])
    assert len(service.db.all(select(versions)))==1
    assert service.db.one(select(url_jobs))['status']=='running'
    assert service.enqueue(source['id'])['id']==run['id']
    fetcher.responses[source['root_url']]=b'<html><body><p>A newer response must not replace the saved run capture.</p></body></html>'
    expire_claim(service);monkeypatch.setattr(service,'_observe',original)
    result=Jobs(service).capture_once(run['id'])
    assert result['status']=='succeeded'
    assert result['metrics']['created']==1
    assert len(service.db.all(select(versions)))==1
    assert len(service.db.all(select(index_jobs)))==1
    assert len(service.db.all(select(events)))==1
    assert len(fetcher.calls)==1
    assert result['metrics']['requests']==1


def test_generation_fences_recovered_worker(system):
    service,source,_,_=system
    run=service.enqueue(source['id']);first=Jobs(service,'first');first.initialize(run['id'])
    old=first.claim_capture(run['id']);expire_claim(service)
    new=Jobs(service,'second').claim_capture(run['id'])
    assert new['generation']>old['generation']
    service._job_context.claim=old
    with pytest.raises(ValueError,match='STALE_WORKER'):
        with service.db.tx() as c:service._guard(c,source['id'],run['id'],old['source_generation'])
    service._job_context.claim=None


def test_run_freezes_rules_and_frontier_survives_recovery(system):
    service,source,fetcher,monitor=system
    service.update_source(source['id'],settings={'scope_mode':'section','max_pages':3,'max_depth':2})
    source=service.source(source['id'])
    fetcher.responses[source['root_url']]=b'<html><body><article><h1>Notice</h1><p>Deadline</p><a href="/docs/two">Next</a></article></body></html>'
    run=service.enqueue(source['id']);monitor.revisions=[{'revision_id':'replacement'}]
    jobs=Jobs(service);jobs.initialize(run['id']);jobs.capture_once(run['id'])
    state=service.db.one(select(run_state))
    assert state['monitor_revisions']==[{'revision_id':'original'}]
    assert monitor.captures[0][1]['revisions']==[{'revision_id':'original'}]
    assert len(service.db.all(select(url_jobs)))==2
    claimed=jobs.claim_capture(run['id']);assert claimed['url'].endswith('/two')
    expire_claim(service)
    finished=Jobs(service).capture_once(run['id'])
    assert finished['status']=='succeeded'
    assert len(service.db.all(select(pages)))==2


def test_browser_slot_is_global_and_source_disable_fences(system):
    service,source,_,_=system
    service.update_source(source['id'],settings={'render_mode':'browser'})
    other=service.add_source('Other browser','https://another.example/docs',{'render_mode':'browser','scope_mode':'page','max_pages':1,'max_depth':0})
    jobs=Jobs(service);a=service.enqueue(source['id']);b=service.enqueue(other['id'])
    jobs.initialize(a['id']);jobs.initialize(b['id'])
    claim=jobs.claim_capture(a['id']);assert claim
    assert Jobs(service).claim_capture(b['id']) is None
    service.set_source(source['id'],enabled=False)
    service._job_context.claim=claim
    with pytest.raises(ValueError,match='STALE_WORKER'):
        with service.db.tx() as c:service._guard(c,source['id'],a['id'],claim['source_generation'])
    service._job_context.claim=None
