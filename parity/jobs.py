"""Durable URL frontier and indexing, fenced independently of model readiness."""
import copy
import email.utils
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from xml.etree import ElementTree
from sqlalchemy import select, func, or_, and_
from . import config
from .db import uid, sources, runs, pages, versions, events
from .job_schema import run_state, url_jobs, index_jobs, index_state, worker_status, origin_locks, resource_locks
from .fetch import canonical, in_scope, origin, FetchError, Response
from .extract import extract,digest


def empty_metrics():
    return {k:0 for k in ('created','modified','unchanged','deleted','restored','missing','failed',
        'new_vectors','reused_vectors','requests','documents','discovered')} | {'budget_exhausted':False}


class Jobs:
    def __init__(self,service,worker_id=None):
        self.service=service
        self.db=service.db
        self.worker_id=worker_id or 'worker-'+uid()

    def _monitor(self):
        from .monitoring import MonitorService
        return MonitorService(self.service)

    def enqueue(self,source_id):
        revisions=self._monitor().snapshot_revisions(source_id)
        with self.db.tx() as c:
            source=c.execute(select(sources).where(sources.c.id==source_id).with_for_update()).mappings().first()
            if not source or not source['enabled']:raise ValueError('Source unavailable')
            existing=c.execute(select(runs).where(runs.c.source_id==source_id,
                runs.c.status.in_(['queued','running'])).order_by(runs.c.created_at.desc())).mappings().first()
            # Recover abandoned URL jobs in place; preserve the run's discovery frontier.
            if existing:return dict(existing)
            now=time.time()
            run={'id':uid(),'source_id':source_id,'status':'queued','created_at':now,'metrics':empty_metrics()}
            c.execute(runs.insert().values(**run))
            c.execute(run_state.insert().values(run_id=run['id'],source_snapshot=copy.deepcopy(dict(source)),
                monitor_revisions=revisions,known_count=0))
            return run

    def scheduler_once(self):
        now=time.time()
        due=self.db.all(select(sources.c.id).where(sources.c.enabled.is_(True),sources.c.paused.is_(False),sources.c.next_due<=now).limit(200))
        for source in due:self.enqueue(source['id'])
        queued=self.db.all(select(runs.c.id).where(runs.c.status=='queued').order_by(runs.c.created_at).limit(200))
        for run in queued:self.initialize(run['id'])
        for run in self.db.all(select(runs.c.id).where(runs.c.status=='running').limit(200)):
            self.finalize(run['id'])
        self.status('scheduler','ready')
        return len(queued)

    def initialize(self,run_id):
        with self.db.tx() as c:
            source_id=c.execute(select(runs.c.source_id).where(runs.c.id==run_id)).scalar()
            if source_id is None:return None
            # Always lock source -> run -> URL job, matching removal/publication.
            c.execute(select(sources.c.id).where(sources.c.id==source_id).with_for_update()).first()
            run=c.execute(select(runs).where(runs.c.id==run_id).with_for_update()).mappings().first()
            if not run:raise ValueError('RUN_NOT_FOUND')
            if run['status']!='queued':return dict(run)
            source=c.execute(select(sources).where(sources.c.id==run['source_id']).with_for_update()).mappings().first()
            if not source or not source['enabled']:
                c.execute(runs.update().where(runs.c.id==run_id).values(status='cancelled',finished_at=time.time(),error='Source disabled'))
                return None
            state=c.execute(select(run_state).where(run_state.c.run_id==run_id)).mappings().first()
            if not state:raise ValueError('Run has no saved configuration')
            frozen=state['source_snapshot'];now=time.time();generation=source['generation']+1
            c.execute(sources.update().where(sources.c.id==source['id']).values(generation=generation,
                lease_run=run_id,lease_until=now+config.LEASE_SECONDS))
            c.execute(runs.update().where(runs.c.id==run_id).values(status='running',generation=generation,started_at=now))
            known=c.execute(select(pages.c.url).where(pages.c.source_id==source['id'])).scalars().all()
            c.execute(run_state.update().where(run_state.c.run_id==run_id).values(initialized_at=now,known_count=len(known)))
            self._add_urls(c,run_id,frozen,[(url,0) for url in [*frozen['config']['seeds'],*known]])
            return dict(run)|{'status':'running','generation':generation}

    def _add_urls(self,c,run_id,source,links):
        limit=source['config']['max_pages']*3+10
        count=c.execute(select(func.count()).select_from(url_jobs).where(url_jobs.c.run_id==run_id)).scalar()
        inserted=0
        for url,depth in links:
            if count>=limit:break
            try:url=canonical(url)
            except ValueError:continue
            if not in_scope(url,source):continue
            if c.execute(select(url_jobs.c.id).where(url_jobs.c.run_id==run_id,url_jobs.c.url==url)).first():continue
            c.execute(url_jobs.insert().values(id=uid(),run_id=run_id,source_id=source['id'],url=url,depth=depth,
                status='queued',attempts=0,generation=0,lease_until=0,available_at=0,created_at=time.time(),metrics={}))
            count+=1;inserted+=1
        return inserted

    def _reserve(self,c,table,keyname,key,owner,now):
        if self.db.engine.dialect.name=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        c.execute(insert(table).values(**{keyname:key,'lease_until':0}).on_conflict_do_nothing(index_elements=[keyname]))
        row=c.execute(select(table).where(table.c[keyname]==key).with_for_update(skip_locked=True)).mappings().first()
        if not row or (row['lease_until'] or 0)>now or (row.get('next_allowed_at') or 0)>now:return False
        c.execute(table.update().where(table.c[keyname]==key).values(owner=owner,lease_until=now+config.LEASE_SECONDS))
        return True

    def claim_capture(self,run_id=None):
        now=time.time()
        with self.db.tx() as c:
            stmt=select(url_jobs).join(runs,runs.c.id==url_jobs.c.run_id).join(sources,sources.c.id==url_jobs.c.source_id).where(
                runs.c.status=='running',sources.c.enabled.is_(True),url_jobs.c.available_at<=now,
                or_(url_jobs.c.status=='queued',and_(url_jobs.c.status=='running',url_jobs.c.lease_until<now)))
            if run_id:stmt=stmt.where(url_jobs.c.run_id==run_id)
            candidates=c.execute(stmt.order_by(url_jobs.c.available_at,url_jobs.c.created_at).limit(30)).mappings().all()
            for candidate in candidates:
                source_lock=c.execute(select(sources).where(sources.c.id==candidate['source_id']).with_for_update(skip_locked=True)).mappings().first()
                if not source_lock or not source_lock['enabled'] or source_lock['removed_at'] is not None:continue
                row=c.execute(stmt.where(url_jobs.c.id==candidate['id']).with_for_update(skip_locked=True,of=url_jobs)).mappings().first()
                if not row:continue
                row=dict(row)
                state=c.execute(select(run_state).where(run_state.c.run_id==row['run_id'])).mappings().one()
                source=state['source_snapshot'];gen=row['generation']+1;token=f"{self.worker_id}:{row['id']}:{gen}"
                held=[]
                reservations=[(resource_locks,'name','run:'+row['run_id']),
                              (origin_locks,'origin',origin(row['url']))]
                if source['config'].get('render_mode')=='browser':reservations.append((resource_locks,'name','chromium'))
                for table,keyname,key in reservations:
                    if not self._reserve(c,table,keyname,key,token,now):break
                    held.append((table,keyname,key))
                if len(held)!=len(reservations):
                    for table,keyname,key in held:c.execute(table.update().where(table.c[keyname]==key,table.c.owner==token).values(owner=None,lease_until=0))
                    continue
                discovery=urlsplit(row['url']).path in source['config']['discovery_only']
                done=c.execute(select(url_jobs.c.url).where(url_jobs.c.run_id==row['run_id'],url_jobs.c.status.in_(['succeeded','failed','missing']))).scalars().all()
                used=sum(urlsplit(url).path not in source['config']['discovery_only'] for url in done)
                if not discovery and used>=source['config']['max_pages']:
                    c.execute(url_jobs.update().where(url_jobs.c.id==row['id']).values(status='skipped',finished_at=now,
                        error='The page limit was reached',metrics={'budget_exhausted':True}))
                    for table,keyname,key in held:c.execute(table.update().where(table.c[keyname]==key,table.c.owner==token).values(owner=None,lease_until=0))
                    continue
                c.execute(url_jobs.update().where(url_jobs.c.id==row['id']).values(status='running',owner=self.worker_id,
                    generation=gen,lease_until=now+config.LEASE_SECONDS,attempts=row['attempts']+1))
                run=c.execute(select(runs).where(runs.c.id==row['run_id'])).mappings().one()
                c.execute(sources.update().where(sources.c.id==row['source_id'],sources.c.lease_run==row['run_id'],
                    sources.c.generation==run['generation']).values(lease_until=now+config.LEASE_SECONDS))
                return row|{'owner':self.worker_id,'generation':gen,'attempts':row['attempts']+1,
                    'source':source,'revisions':state['monitor_revisions'],'source_generation':run['generation'],
                    'token':token,'locks':[(t.name,k,n) for t,k,n in held]}
        return None

    def _assert_claim(self,c,claim,table=url_jobs):
        row=c.execute(select(table).where(table.c.id==claim['id']).with_for_update()).mappings().first()
        if not row or row['status']!='running' or row['generation']!=claim['generation'] or row['owner']!=claim['owner'] or row['lease_until']<time.time():
            raise ValueError('STALE_WORKER')
        return row

    def renew(self,claim,index=False):
        table=index_jobs if index else url_jobs
        with self.db.tx() as c:
            if not index:
                # Match Service._guard's lock order to avoid heartbeat/publication deadlocks.
                c.execute(select(sources.c.id).where(sources.c.id==claim['source_id']).with_for_update()).first()
            self._assert_claim(c,claim,table)
            until=time.time()+config.LEASE_SECONDS
            c.execute(table.update().where(table.c.id==claim['id']).values(lease_until=until))
            if not index:
                c.execute(sources.update().where(sources.c.id==claim['source_id'],sources.c.lease_run==claim['run_id'],
                    sources.c.generation==claim['source_generation']).values(lease_until=until))
                for name,keyname,key in claim['locks']:
                    table=origin_locks if name=='origin_locks' else resource_locks
                    c.execute(table.update().where(table.c[keyname]==key,table.c.owner==claim['token']).values(lease_until=until))

    @contextmanager
    def heartbeat(self,claim,index=False):
        stopped=threading.Event()
        def beat():
            while not stopped.wait(max(.1,min(10,config.LEASE_SECONDS/3))):
                try:self.renew(claim,index=index)
                except Exception:return
                try:
                    self.status('index' if index else 'capture','working')
                except Exception:pass
        thread=threading.Thread(target=beat,daemon=True);thread.start()
        try:yield
        finally:stopped.set();thread.join(timeout=2)

    def _release(self,c,claim,retry_at=None):
        for name,keyname,key in claim['locks']:
            table=origin_locks if name=='origin_locks' else resource_locks
            values={'owner':None,'lease_until':0}
            if name=='origin_locks':values['next_allowed_at']=max(time.time()+claim['source']['config']['delay'],retry_at or 0)
            c.execute(table.update().where(table.c[keyname]==key,table.c.owner==claim['token']).values(**values))

    def _retry_at(self,response,attempt):
        delay=min(60,2**attempt)
        raw=response.headers.get('retry-after','') if response else ''
        try:delay=max(delay,float(raw))
        except ValueError:
            try:delay=max(delay,email.utils.parsedate_to_datetime(raw).timestamp()-time.time())
            except (ValueError,TypeError,OverflowError):pass
        return time.time()+min(max(delay,0),86400)

    def _saved_response(self,claim):
        saved=(claim.get('metrics') or {}).get('_capture')
        if not saved:return None
        body=(config.DATA/'artifacts'/saved['raw_key']).read_bytes()
        if digest(body)!=saved['raw_key']:raise ValueError('Stored capture failed its integrity check')
        return Response(saved['url'],saved['status'],saved['headers'],body)

    def _store_response(self,claim,response):
        import os,tempfile
        key=digest(response.body);directory=config.DATA/'artifacts';directory.mkdir(parents=True,exist_ok=True)
        target=directory/key
        if not target.exists():
            with tempfile.NamedTemporaryFile(dir=directory,delete=False) as f:
                temporary=f.name;f.write(response.body);f.flush();os.fsync(f.fileno())
            os.replace(temporary,target)
        saved={'raw_key':key,'url':response.url,'status':response.status,'headers':{
            k:v for k,v in response.headers.items() if k.lower() in ('content-type','etag','last-modified')}}
        with self.db.tx() as c:
            row=self._assert_claim(c,claim)
            values=dict(row['metrics'] or {});values['_capture']=saved
            c.execute(url_jobs.update().where(url_jobs.c.id==claim['id']).values(metrics=values))

    def capture_once(self,run_id=None):
        if run_id:self.initialize(run_id)
        claim=self.claim_capture(run_id)
        if not claim:
            if run_id:self.finalize(run_id)
            return None
        source=claim['source'];url=claim['url'];metrics=empty_metrics()
        response=None;links=[];outcome='succeeded';error=None;retry_at=None
        page=self.db.one(select(pages).where(pages.c.source_id==source['id'],pages.c.url==url))
        discovery=urlsplit(url).path in source['config']['discovery_only']
        self.service._job_context.claim=claim
        try:
            with self.heartbeat(claim):
                self.status('capture','working',url)
                response=self._saved_response(claim)
                if response is None:
                    with self.db.tx() as c:
                        row=self._assert_claim(c,claim);saved=dict(row['metrics'] or {})
                        saved['requests']=saved.get('requests',0)+1
                        c.execute(url_jobs.update().where(url_jobs.c.id==claim['id']).values(metrics=saved))
                    if source['config'].get('render_mode')=='browser':
                        from .browser import capture
                        response=capture(url,source,getattr(self.service.fetcher,"fixture_origin",None))
                    else:
                        # Full captures preserve attribute evidence even when text is unchanged.
                        response=self.service.fetcher.get(url,source,{})
                    if response.status not in (429,500,502,503,504):self._store_response(claim,response)
                if response.status in (429,500,502,503,504):
                    raise FetchError('The website returned '+str(response.status))
                with self.db.tx() as c:self.service._guard(c,source['id'],claim['run_id'],claim['source_generation'])
                if response.status in (404,410):
                    outcome='missing';metrics['missing']=1
                    self._monitor().process_error(source,claim['run_id'],url,'The page is unavailable',status=response.status,revisions=claim['revisions'])
                    self.service._observe(claim['run_id'],url,response.status,'missing')
                elif response.status==200:
                    if not discovery:
                        self._monitor().process_capture(source,claim['run_id'],response,page_id=page['id'] if page else None,revisions=claim['revisions'])
                    mime=response.headers.get('content-type','').split(';')[0].lower()
                    if 'xml' in mime or urlsplit(url).path.endswith('.xml'):
                        if b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():raise ValueError('XML entities are not allowed')
                        tree=ElementTree.fromstring(response.body)
                        links=[e.text for e in tree.iter() if e.tag.split('}')[-1]=='loc' and e.text][:1000]
                    else:
                        rules=source['config'] if not discovery else source['config']|{'selector':''}
                        document=extract(response.body,mime,response.url,rules);links=document.links
                        if not discovery:self.service._publish(source,claim['run_id'],claim['source_generation'],url,page,response,document,metrics)
                    if discovery:self.service._observe(claim['run_id'],url,200,'discovery')
                else:raise FetchError('The website returned '+str(response.status))
        except Exception as exc:
            error=str(exc)[:1000]
            if error in ('STALE_WORKER','STALE_PAGE'):raise
            if response is None:response=getattr(exc,'response',None)
            transient=(response is None and isinstance(exc,(FetchError,TimeoutError,OSError)) and getattr(exc,'transient',True)) or (response and response.status in (429,500,502,503,504))
            if transient and claim['attempts']<3:
                outcome='queued';retry_at=self._retry_at(response,claim['attempts'])
            else:
                outcome='failed';metrics['failed']=1
                self.service._error(source,claim['run_id'],claim['source_generation'],page,url,response,error)
                self._monitor().process_error(source,claim['run_id'],url,error,status=response.status if response else None,revisions=claim['revisions'])
        finally:
            self.service._job_context.claim=None
        with self.db.tx() as c:
            self._assert_claim(c,claim)
            prior=c.execute(select(url_jobs.c.metrics).where(url_jobs.c.id==claim['id'])).scalar() or {}
            metrics['requests']=prior.get('requests',0)
            if prior.get('_capture'):metrics['_capture']=prior['_capture']
            if not discovery and outcome!='queued':metrics['documents']=1
            c.execute(url_jobs.update().where(url_jobs.c.id==claim['id']).values(status=outcome,owner=None,lease_until=0,
                available_at=retry_at or 0,finished_at=None if outcome=='queued' else time.time(),
                error=error,http_status=response.status if response else None,metrics=metrics))
            if outcome=='succeeded' and claim['depth']<source['config']['max_depth']:
                self._add_urls(c,claim['run_id'],source,[(link,claim['depth']+1) for link in links])
            self._release(c,claim,retry_at)
            progress=empty_metrics()
            for saved in c.execute(select(url_jobs.c.metrics).where(url_jobs.c.run_id==claim['run_id'])).scalars():
                for key,value in (saved or {}).items():
                    if key=='budget_exhausted':progress[key]|=bool(value)
                    elif key in progress:progress[key]+=value
            progress['discovered']=c.execute(select(func.count()).select_from(url_jobs).where(url_jobs.c.run_id==claim['run_id'])).scalar()
            c.execute(runs.update().where(runs.c.id==claim['run_id']).values(metrics=progress))
        self.finalize(claim['run_id'])
        self.status('capture','ready')
        return self.db.one(select(runs).where(runs.c.id==claim['run_id']))

    def finalize(self,run_id):
        with self.db.tx() as c:
            source_id=c.execute(select(runs.c.source_id).where(runs.c.id==run_id)).scalar()
            if source_id is None:return None
            # Always lock source -> run -> URL job, matching removal/publication.
            c.execute(select(sources.c.id).where(sources.c.id==source_id).with_for_update()).first()
            run=c.execute(select(runs).where(runs.c.id==run_id).with_for_update()).mappings().first()
            if not run or run['status']!='running':return
            jobs=c.execute(select(url_jobs).where(url_jobs.c.run_id==run_id)).mappings().all()
            if any(j['status'] in ('queued','running') for j in jobs):return
            state=c.execute(select(run_state).where(run_state.c.run_id==run_id)).mappings().one()
            source=state['source_snapshot'];metrics=empty_metrics()
            for job in jobs:
                for key,value in (job['metrics'] or {}).items():
                    if key=='budget_exhausted':metrics[key]|=bool(value)
                    elif key in metrics:metrics[key]+=value
            metrics['discovered']=len(jobs)
            missing=[j for j in jobs if j['status']=='missing']
            mass=state['known_count']>=3 and len(missing)/state['known_count']>=.8
            current=c.execute(select(sources).where(sources.c.id==source['id']).with_for_update()).mappings().one()
            if not current['enabled'] or current['lease_run']!=run_id or current['generation']!=run['generation']:return
            now=time.time()
            # Finalize availability and run completion atomically after all URL attempts.
            for job in missing:
                p=c.execute(select(pages).where(pages.c.source_id==source['id'],pages.c.url==job['url']).with_for_update()).mappings().first()
                if not p:continue
                if p['availability']=='deleted':
                    c.execute(pages.update().where(pages.c.id==p['id']).values(checked_at=now));continue
                count=p['missing_count'] or 0
                eligible=p['missing_run']!=run_id and (p['missing_at'] is None or now-p['missing_at']>=source['config']['missing_interval'])
                if eligible:count+=1
                deleted=count>=3 and not mass
                self.service._close(c,p['id'],now)
                values={'availability':'deleted' if deleted else 'missing_candidate','checked_at':now,'missing_count':count,
                    'health':'source_unavailable','last_error':'Mass missing response: confirmation suspended' if mass else 'HTTP 404/410'}
                if eligible:values.update(missing_at=now,missing_run=run_id)
                if deleted:
                    values['current_id']=None;metrics['deleted']+=1;metrics['missing']-=1
                    c.execute(events.insert().values(id=uid(),page_id=p['id'],run_id=run_id,kind='DELETED',old_version_id=p['last_version_id'],at=now,detail={'confirmations':count}))
                c.execute(pages.update().where(pages.c.id==p['id']).values(**values))
            # Recover counts from committed publications if interruption preceded URL completion.
            counts=dict(c.execute(select(events.c.kind,func.count()).where(events.c.run_id==run_id).group_by(events.c.kind)).all())
            for key in ('created','modified','restored'):metrics[key]=counts.get(key.upper(),0)
            metrics['modified']+=counts.get('PIPELINE_REPROCESSED',0)
            status='partial' if metrics['failed'] or metrics['budget_exhausted'] else 'succeeded'
            c.execute(runs.update().where(runs.c.id==run_id).values(status=status,finished_at=now,metrics=metrics,
                error='The page limit was reached' if metrics['budget_exhausted'] else None))
            c.execute(sources.update().where(sources.c.id==source['id']).values(lease_run=None,lease_until=0,next_due=now+source['config']['interval']))
            from .monitor_schema import monitor_events
            c.execute(monitor_events.insert().values(source_id=source['id'],kind='check_completed',at=now,detail={'run_id':run_id,'status':status}))

    def drain(self,run_id):
        self.initialize(run_id)
        while True:
            run=self.db.one(select(runs).where(runs.c.id==run_id))
            if not run or run['status'] not in ('queued','running'):return run
            if self.capture_once(run_id) is None:time.sleep(.05)

    def claim_index(self):
        now=time.time()
        with self.db.tx() as c:
            row=c.execute(select(index_jobs).where(index_jobs.c.available_at<=now,
                or_(index_jobs.c.status=='queued',and_(index_jobs.c.status=='running',index_jobs.c.lease_until<now)))
                .order_by(index_jobs.c.created_at).limit(1).with_for_update(skip_locked=True)).mappings().first()
            if not row:return None
            claim=dict(row)|{'owner':self.worker_id,'generation':row['generation']+1,'attempts':row['attempts']+1}
            c.execute(index_jobs.update().where(index_jobs.c.id==row['id']).values(status='running',owner=self.worker_id,
                generation=claim['generation'],attempts=claim['attempts'],lease_until=now+config.LEASE_SECONDS))
            c.execute(index_state.update().where(index_state.c.version_id==row['version_id']).values(status='indexing',updated_at=now,error=None))
            return claim

    def index_once(self):
        claim=self.claim_index()
        if not claim:
            self.status('index','ready')
            return None
        error=None;result=None
        self.service._job_context.index_claim=claim
        try:
            with self.heartbeat(claim,index=True):
                self.status('index','working',claim['version_id'])
                result=self.service.index_version(claim['version_id'])
        except Exception as exc:error=str(exc)[:1000]
        finally:self.service._job_context.index_claim=None
        with self.db.tx() as c:
            self._assert_claim(c,claim,index_jobs)
            now=time.time()
            c.execute(index_jobs.update().where(index_jobs.c.id==claim['id']).values(status='queued' if error else 'succeeded',
                owner=None,lease_until=0,available_at=now+min(300,2**min(claim['attempts'],8)) if error else 0,
                error=error,finished_at=None if error else now))
            if error:c.execute(index_state.update().where(index_state.c.version_id==claim['version_id']).values(status='error',updated_at=now,error=error))
        self.status('index','waiting' if error else 'ready',error)
        return result or {'error':error,'version_id':claim['version_id']}

    def status(self,role,status,detail=None):
        with self.db.tx() as c:
            values={'role':role,'status':status,'heartbeat_at':time.time(),'detail':detail}
            if c.execute(select(worker_status.c.id).where(worker_status.c.id==self.worker_id)).first():
                c.execute(worker_status.update().where(worker_status.c.id==self.worker_id).values(**values))
            else:c.execute(worker_status.insert().values(id=self.worker_id,**values))
