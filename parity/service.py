import time, json, difflib, math, threading, re, hashlib
from collections import Counter, deque
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from sqlalchemy import select, update, and_, or_, func, union, literal_column
from .db import DB, uid, sources, runs, pages, versions, cache, chunks, intervals, events, observations
from .fetch import Fetcher, FetchError, canonical, in_scope, origin
from .extract import extract, chunk, digest
from .embedding import Embedder, tokens, cosine, STOPWORDS
from . import config

class Service:
    def __init__(self,db=None,embedder=None,fetcher=None,inline_index=None):
        self.db=db or DB()
        self.embedder=embedder
        self.fetcher=fetcher or Fetcher()
        self._embed_lock=threading.Lock()
        # Explicit injected models keep the original synchronous integration contract.
        # Normal application workers never need an embedding model to capture evidence.
        self.inline_index = (embedder is not None) if inline_index is None else bool(inline_index)
        self._job_context = threading.local()

    def model(self):
        with self._embed_lock:
            if self.embedder is None:
                try:self.embedder=Embedder()
                except Exception as error:
                    raise ValueError('Semantic search is unavailable. Install the cached MiniLM model and start the embedding service. Monitoring continues.') from error
        return self.embedder

    def _prepare_source(self,name,root_url,settings=None):
        root_url=canonical(root_url)
        settings=settings or {}
        if settings.get("demo") and origin(root_url)!=config.DEMO_ORIGIN:
            raise ValueError("Demo exception is restricted to the configured fixture origin")
        if not name.strip(): raise ValueError("Source name is required")
        defaults={"allow":["/"],"deny":["/admin","/login"],"selector":"","exclude":".render-timestamp,#cookie-banner",
                  "seeds":[root_url],"discovery_only":[],"max_pages":100,"max_depth":3,
                  "delay":1.0,"interval":21600,"missing_interval":21600,"max_bytes":10*1024*1024,"demo":False,
                  "render_mode":"static","ready_selector":"","resource_origins":[],
                  "source_kind":"normal","scope_mode":"section"}
        allowed=set(defaults)|{"max_bytes"}
        if set(settings)-allowed: raise ValueError("Unknown source configuration field")
        defaults.update(settings)
        if defaults['source_kind'] not in ('normal','demo','benchmark'):raise ValueError('Invalid source_kind')
        if defaults['scope_mode'] not in ('page','section','site'):raise ValueError('Invalid scope_mode')
        if defaults['demo']:defaults['source_kind']='demo'
        for field,lo,hi in [("max_pages",1,500),("max_depth",0,6),("delay",0,60),
                            ("interval",10,604800),("missing_interval",0,604800),("max_bytes",1,10*1024*1024)]:
            if not isinstance(defaults[field],(float,int)) or not lo<=defaults[field]<=hi:
                raise ValueError("Invalid "+field)
        for field in ("max_pages","max_depth","max_bytes"):
            if type(defaults[field]) is not int:raise ValueError(field+" must be an integer")
        if defaults['render_mode'] not in ('static','browser'):raise ValueError('render_mode must be static or browser')
        for field in ("selector","exclude","ready_selector"):
            if not isinstance(defaults[field],str):raise ValueError(field+" must be a string")
            if len(defaults[field])>1000:raise ValueError(field+' is too long')
        import soupsieve
        for field in ('selector','exclude','ready_selector'):
            if defaults[field]:
                try:soupsieve.compile(defaults[field])
                except Exception as error:raise ValueError('Invalid CSS selector: '+field) from error
        if not defaults["demo"]:
            defaults["delay"]=max(0.5,defaults["delay"])
            defaults["missing_interval"]=max(60,defaults["missing_interval"])
        for key in ["allow","deny","seeds","discovery_only","resource_origins"]:
            if not isinstance(defaults[key],list) or not all(isinstance(x,str) for x in defaults[key]):
                raise ValueError(key+" must be a list of strings")
        source={"id":uid(),"name":name[:100],"root_url":root_url,"config":defaults,"enabled":True,
                "paused":True,"generation":0,"lease_until":0,"next_due":0,"created_at":time.time()}
        for seed in defaults["seeds"]:
            if not in_scope(seed,source): raise ValueError("Seed outside source scope")
        self.fetcher.addresses(root_url,source)
        normalized=[]
        for extra in defaults['resource_origins']:
            resource_origin=origin(extra)
            if canonical(extra).rstrip('/')!=resource_origin:raise ValueError('Resource origins cannot contain paths or queries')
            normalized.append(resource_origin)
        defaults['resource_origins']=list(dict.fromkeys(normalized))
        for extra in defaults['resource_origins']:self.fetcher.addresses(extra,source)
        return source

    def add_source(self,name,root_url,settings=None):
        source=self._prepare_source(name,root_url,settings)
        with self.db.tx() as c:
            c.execute(sources.insert().values(**source))
        return source

    def update_source(self,source_id,name=None,settings=None,enabled=None,paused=None):
        current=self.source(source_id)
        if name is not None or settings is not None:
            if self.db.one(select(runs.c.id).where(runs.c.source_id==source_id,runs.c.status.in_(['queued','running']))):
                raise ValueError('Wait for the active crawl before editing source rules')
            checked=self._prepare_source(name if name is not None else current['name'],current['root_url'],{**current['config'],**(settings or {})})
            with self.db.tx() as c:c.execute(sources.update().where(sources.c.id==source_id).values(name=checked['name'],config=checked['config']))
        return self.set_source(source_id,enabled,paused) if enabled is not None or paused is not None else self.source(source_id)

    def test_source(self,name,root_url,settings=None):
        started=time.perf_counter();source=self._prepare_source(name,root_url,settings)
        if source['config']['render_mode']=='browser':
            from .browser import capture
            response=capture(root_url,source,self.fetcher.demo_origin)
        else:response=self.fetcher.get(root_url,source)
        if response.status!=200:raise ValueError('Source returned HTTP '+str(response.status))
        doc=extract(response.body,response.headers.get('content-type','').split(';')[0],response.url,source['config'])
        return {'title':doc.title,'text':doc.content[:12000],'links':doc.links[:30],
                'render_mode':source['config']['render_mode'],'elapsed_ms':round((time.perf_counter()-started)*1000)}

    def pipeline_signature(self,source):
        rules={key:source['config'].get(key,'') for key in ('selector','exclude','render_mode','ready_selector')}
        rules['resource_origins']=sorted(source['config'].get('resource_origins',[]))
        signature='extract-v3:'+hashlib.sha256(json.dumps(rules,sort_keys=True).encode()).hexdigest()[:16]
        return signature+':'+self.model().signature if self.inline_index else signature

    def seed_demo(self):
        existing=self.db.one(select(sources).where(sources.c.root_url==config.DEMO_ORIGIN+"/en/circulars/"))
        if existing:return existing
        return self.add_source("KJSCE · demonstration",config.DEMO_ORIGIN+"/en/circulars/",
            {"demo":True,"allow":["/en/"],"deny":["/admin","/test"],
             "seeds":[config.DEMO_ORIGIN+"/en/circulars/",config.DEMO_ORIGIN+"/en/sitemap.xml"],
             "discovery_only":["/en/","/en/circulars/","/en/sitemap.xml"],
             "selector":"article","delay":0,"interval":60,"missing_interval":2})

    def source(self,source_id):
        s=self.db.one(select(sources).where(sources.c.id==source_id))
        if not s:raise ValueError("SOURCE_NOT_FOUND")
        return s

    def enqueue(self,source_id):
        if not self.inline_index:
            from .jobs import Jobs
            return Jobs(self).enqueue(source_id)
        with self.db.tx() as c:
            s=c.execute(select(sources).where(sources.c.id==source_id).with_for_update()).mappings().first()
            if not s or not s["enabled"]:raise ValueError("Source unavailable")
            existing=c.execute(select(runs).where(runs.c.source_id==source_id,
                runs.c.status.in_(["queued","running"])).order_by(runs.c.created_at.desc())).mappings().first()
            if existing and (existing["status"]=="queued" or s["lease_until"]>time.time()):
                return dict(existing)
            if existing:
                c.execute(update(runs).where(runs.c.id==existing["id"]).values(status="failed",error="Lease expired; safe to retry"))
            run={"id":uid(),"source_id":source_id,"status":"queued","created_at":time.time(),"metrics":{}}
            c.execute(runs.insert().values(**run))
            return run

    def _guard(self,c,source_id,run_id,generation):
        s=c.execute(select(sources).where(sources.c.id==source_id).with_for_update()).mappings().first()
        if not s or not s["enabled"] or s["generation"]!=generation or s["lease_run"]!=run_id or s["lease_until"]<time.time():
            raise ValueError("STALE_WORKER")
        job=getattr(self._job_context,'claim',None)
        if job:
            from .job_schema import url_jobs
            active=c.execute(select(url_jobs).where(url_jobs.c.id==job['id']).with_for_update()).mappings().first()
            if not active or active['status']!='running' or active['generation']!=job['generation'] or active['owner']!=job['owner'] or active['lease_until']<time.time():
                raise ValueError('STALE_WORKER')
        c.execute(update(sources).where(sources.c.id==source_id).values(lease_until=time.time()+config.LEASE_SECONDS))

    def run(self,run_id):
        if not self.inline_index:
            from .jobs import Jobs
            return Jobs(self).drain(run_id)
        # Loading/downloading the model must never consume a claimed source lease.
        try:self.model()
        except Exception as error:
            with self.db.tx() as c:
                c.execute(update(runs).where(runs.c.id==run_id,runs.c.status=='queued').values(
                    status='failed',finished_at=time.time(),error='Embedding model failed to load: '+str(error)[:300]))
            return self.db.one(select(runs).where(runs.c.id==run_id))
        now=time.time()
        with self.db.tx() as c:
            run=c.execute(select(runs).where(runs.c.id==run_id).with_for_update()).mappings().first()
            if not run:raise ValueError("RUN_NOT_FOUND")
            if run["status"]!="queued":return dict(run)
            src=c.execute(select(sources).where(sources.c.id==run["source_id"]).with_for_update()).mappings().first()
            if not src["enabled"]:raise ValueError("Source disabled")
            if src["lease_until"]>now:return dict(run)
            generation=src["generation"]+1
            c.execute(update(sources).where(sources.c.id==src["id"]).values(
                generation=generation,lease_run=run_id,lease_until=now+config.LEASE_SECONDS))
            c.execute(update(runs).where(runs.c.id==run_id).values(status="running",started_at=now,generation=generation))
        source=self.source(src["id"])
        heartbeat_stop=threading.Event()
        def heartbeat():
            while not heartbeat_stop.wait(max(.2,min(10,config.LEASE_SECONDS/3))):
                try:
                    with self.db.tx() as c:self._guard(c,source['id'],run_id,generation)
                except Exception:return
        heartbeat_thread=threading.Thread(target=heartbeat,daemon=True)
        heartbeat_thread.start()
        metrics={"created":0,"modified":0,"unchanged":0,"deleted":0,"restored":0,"missing":0,"failed":0,
                 "new_vectors":0,"reused_vectors":0,"requests":0,"documents":0,"discovered":0,"budget_exhausted":False}
        failure=None
        try:
            self.model()
            # Extend the lease after potentially slow first model loading.
            with self.db.tx() as c:self._guard(c,source["id"],run_id,generation)
            known=self.db.all(select(pages).where(pages.c.source_id==source["id"]))
            queue=deque((u,0) for u in source["config"]["seeds"])
            queue.extend((p["url"],0) for p in known)
            seen=set();missing=[]
            max_requests=source["config"]["max_pages"]*3+10
            while queue and len(seen)<max_requests:
                url,depth=queue.popleft()
                try:url=canonical(url)
                except ValueError:continue
                if url in seen or not in_scope(url,source):continue
                seen.add(url)
                is_discovery=urlsplit(url).path in source["config"]["discovery_only"]
                if not is_discovery and metrics["documents"]>=source["config"]["max_pages"]:
                    metrics["budget_exhausted"]=True
                    continue
                with self.db.tx() as c:self._guard(c,source["id"],run_id,generation)
                page=self.db.one(select(pages).where(pages.c.source_id==source["id"],pages.c.url==url))
                headers={}
                last_version=self.db.one(select(versions).where(versions.c.id==page["current_id"])) if page and page["current_id"] else None
                compatible=last_version and last_version["signature"]==self.pipeline_signature(source)
                rendered=source['config'].get('render_mode','static')=='browser'
                if not rendered and page and page["current_id"] and compatible and time.time()-(page["audit_at"] or 0)<86400:
                    if page["etag"]:headers["If-None-Match"]=page["etag"]
                    elif page["last_modified"]:headers["If-Modified-Since"]=page["last_modified"]
                response=None
                try:
                    # Retry transient transport/status failures, bounded.
                    for attempt in range(3):
                        metrics["requests"]+=1
                        try:
                            if rendered:
                                from .browser import capture
                                response=capture(url,source,self.fetcher.demo_origin)
                            else:response=self.fetcher.get(url,source,headers)
                        except FetchError:
                            if attempt==2:raise
                            time.sleep(0.2*(2**attempt));continue
                        if response.status not in (429,500,502,503,504) or attempt==2:break
                        wait=response.headers.get("retry-after","")
                        time.sleep(min(2,float(wait)) if wait.isdigit() else 0.2*(2**attempt))
                    if not is_discovery:metrics["documents"]+=1
                    if response.status in (404,410):
                        if page:missing.append((page,response))
                        self._observe(run_id,url,response.status,"missing")
                        continue
                    if response.status==304:
                        if not page or not page["current_id"]:
                            response=self.fetcher.get(url,source,{})
                            metrics["requests"]+=1
                        else:
                            self._unchanged(source,run_id,generation,page,response,metrics)
                            continue
                    if response.status!=200:
                        raise FetchError("HTTP "+str(response.status))
                    mime=response.headers.get("content-type","").split(";")[0].lower()
                    links=[]
                    if "xml" in mime or urlsplit(url).path.endswith(".xml"):
                        if b"<!DOCTYPE" in response.body.upper() or b"<!ENTITY" in response.body.upper():
                            raise ValueError("XML entities are not allowed")
                        tree=ElementTree.fromstring(response.body)
                        links=[e.text for e in tree.iter() if e.tag.split("}")[-1]=="loc" and e.text][:1000]
                    else:
                        rules=source["config"] if not is_discovery else {**source["config"],"selector":""}
                        doc=extract(response.body,mime,response.url,rules)
                        links=doc.links
                        if not is_discovery:self._publish(source,run_id,generation,url,page,response,doc,metrics)
                    if depth<source["config"]["max_depth"]:
                        queue.extend((u,depth+1) for u in links if in_scope(u,source))
                    if is_discovery:self._observe(run_id,url,response.status,"discovery")
                except Exception as e:
                    metrics["failed"]+=1
                    self._error(source,run_id,generation,page,url,response,str(e))
                metrics["discovered"]=len(seen)
                with self.db.tx() as c:
                    self._guard(c,source["id"],run_id,generation)
                    c.execute(update(runs).where(runs.c.id==run_id).values(metrics=metrics.copy()))
            metrics["budget_exhausted"] |= bool(queue)
            # Suspend mass deletion confirmation for a source-wide disappearance.
            mass=len(known)>=3 and len(missing)/len(known)>=0.8
            for page,response in missing:
                self._missing(source,run_id,generation,page,metrics,suspend=mass)
        except Exception as e:
            failure=str(e)
        finally:
            heartbeat_stop.set();heartbeat_thread.join(timeout=2)
            with self.db.tx() as c:
                s=c.execute(select(sources).where(sources.c.id==source["id"])).mappings().first()
                if s["generation"]==generation and s["lease_run"]==run_id:
                    c.execute(update(sources).where(sources.c.id==source["id"]).values(
                        lease_until=0,lease_run=None,next_due=time.time()+source["config"]["interval"]))
                    c.execute(update(runs).where(runs.c.id==run_id).values(
                        status="failed" if failure else ("partial" if metrics["failed"] or metrics["budget_exhausted"] else "succeeded"),
                        metrics=metrics,finished_at=time.time(),error=failure))
        return self.db.one(select(runs).where(runs.c.id==run_id))

    def _observe(self,run_id,url,status,outcome,detail=""):
        with self.db.tx() as c:
            claim=getattr(self._job_context,'claim',None)
            if claim:
                self._guard(c,claim['source_id'],run_id,claim['source_generation'])
                observation_id=hashlib.sha256((run_id+'\0'+url).encode()).hexdigest()[:32]
                if c.execute(select(observations.c.id).where(observations.c.id==observation_id)).first():return
            else:observation_id=uid()
            c.execute(observations.insert().values(id=observation_id,run_id=run_id,url=url,at=time.time(),
                status=status,outcome=outcome,detail=detail[:1000]))

    def _close(self,c,page_id,at):
        c.execute(update(intervals).where(intervals.c.page_id==page_id,intervals.c.end.is_(None)).values(end=at))

    def _unchanged(self,source,run_id,generation,page,response,metrics):
        now=time.time()
        with self.db.tx() as c:
            self._guard(c,source["id"],run_id,generation)
            if page["availability"]!="active":
                c.execute(intervals.insert().values(id=uid(),page_id=page["id"],version_id=page["current_id"],start=now))
            c.execute(update(pages).where(pages.c.id==page["id"]).values(availability="active",health="healthy",
                checked_at=now,verified_at=now,missing_count=0,missing_at=None,missing_run=None,last_error=None))
        metrics["unchanged"]+=1
        self._observe(run_id,page["url"],response.status,"UNCHANGED")

    def _publish(self,source,run_id,generation,url,page,response,doc,metrics):
        if self.inline_index:
            return self._publish_inline(source,run_id,generation,url,page,response,doc,metrics)
        from .job_schema import index_jobs,index_state
        import os,tempfile
        now=time.time()
        old=self.db.one(select(versions).where(versions.c.id==page['last_version_id'])) if page and page['last_version_id'] else None
        signature=self.pipeline_signature(source)
        if old and old['hash']==doc.hash and old['signature']==signature and page['availability']!='deleted':
            self._unchanged(source,run_id,generation,page,response,metrics)
            with self.db.tx() as c:
                self._guard(c,source['id'],run_id,generation)
                c.execute(pages.update().where(pages.c.id==page['id']).values(
                    etag=response.headers.get('etag'),last_modified=response.headers.get('last-modified'),audit_at=now))
            return old['id']
        raw_hash=digest(response.body)
        directory=config.DATA/'artifacts';directory.mkdir(parents=True,exist_ok=True)
        target=directory/raw_hash
        if not target.exists():
            with tempfile.NamedTemporaryFile(dir=directory,delete=False) as f:
                temporary=f.name;f.write(response.body);f.flush();os.fsync(f.fileno())
            os.replace(temporary,target)
        with self.db.tx() as c:
            self._guard(c,source['id'],run_id,generation)
            current=c.execute(select(pages).where(pages.c.source_id==source['id'],pages.c.url==url).with_for_update()).mappings().first()
            if (current['last_version_id'] if current else None)!=(page['last_version_id'] if page else None):
                raise ValueError('STALE_PAGE')
            page_id=current['id'] if current else uid()
            if not current:c.execute(pages.insert().values(id=page_id,source_id=source['id'],url=url))
            number=(c.execute(select(func.max(versions.c.number)).where(versions.c.page_id==page_id)).scalar() or 0)+1
            version_id=uid()
            c.execute(versions.insert().values(id=version_id,page_id=page_id,number=number,title=doc.title,
                content=doc.content,hash=doc.hash,raw_hash=raw_hash,raw_key=raw_hash,observed_at=now,
                indexed_at=None,signature=signature,sections=doc.sections))
            self._close(c,page_id,now)
            c.execute(intervals.insert().values(id=uid(),page_id=page_id,version_id=version_id,start=now))
            kind='CREATED' if not old else ('RESTORED' if page['availability']=='deleted' else
                 ('PIPELINE_REPROCESSED' if old['hash']==doc.hash else 'MODIFIED'))
            c.execute(pages.update().where(pages.c.id==page_id).values(title=doc.title,current_id=version_id,
                last_version_id=version_id,availability='active',health='healthy',checked_at=now,verified_at=now,
                missing_count=0,missing_at=None,missing_run=None,last_error=None,
                etag=response.headers.get('etag'),last_modified=response.headers.get('last-modified'),audit_at=now))
            c.execute(events.insert().values(id=uid(),page_id=page_id,run_id=run_id,kind=kind,
                old_version_id=old['id'] if old else None,new_version_id=version_id,at=now,
                detail={'new_vectors':0,'reused_vectors':0,'chunks':0,'index_status':'pending'}))
            c.execute(index_jobs.insert().values(id=uid(),version_id=version_id,status='queued',attempts=0,
                generation=0,lease_until=0,available_at=now,created_at=now))
            c.execute(index_state.insert().values(version_id=version_id,status='pending',updated_at=now))
        metrics[kind.lower() if kind!='PIPELINE_REPROCESSED' else 'modified']+=1
        self._observe(run_id,url,200,kind)
        return version_id

    def index_version(self,version_id):
        """Publish complete chunks atomically; capture/current-version publication is independent."""
        from .extract import Document
        from .job_schema import index_jobs,index_state
        v=self.db.one(select(versions).where(versions.c.id==version_id))
        if not v:raise ValueError('VERSION_NOT_FOUND')
        model=self.model()
        state=self.db.one(select(index_state).where(index_state.c.version_id==version_id))
        if state and state['status']=='ready' and state['model_signature']==model.signature and v['indexed_at']:
            return {'version_id':version_id,'new_vectors':0,'reused_vectors':0,'already_indexed':True}
        doc=Document(v['title'],v['sections'] or [],[],v['content'],v['hash'])
        items=chunk(doc,model)
        keys=list(dict.fromkeys(digest(model.signature+'\0'+item['input']) for item in items))
        found={}
        for start in range(0,len(keys),200):
            found.update({row['key']:row for row in self.db.all(select(cache).where(cache.c.key.in_(keys[start:start+200])))})
        pending={digest(model.signature+'\0'+item['input']):item['input'] for item in items if digest(model.signature+'\0'+item['input']) not in found}
        encoded={}
        pending_items=list(pending.items())
        for start in range(0,len(pending_items),32):
            batch=pending_items[start:start+32];texts=[text for _,text in batch]
            vectors=model.encode_many(texts) if hasattr(model,'encode_many') else [model.encode(text) for text in texts]
            if len(vectors)!=len(batch):raise ValueError('Embedding service returned an incomplete batch')
            for (key,text),vector in zip(batch,vectors):
                if len(vector)!=384 or not all(math.isfinite(float(x)) for x in vector):raise ValueError('Invalid embedding vector')
                encoded[key]={'id':uid(),'key':key,'signature':model.signature,'input':text,'vector':vector}
        now=time.time();new_count=0
        with self.db.tx() as c:
            # Lock the version: two recovery attempts cannot replace each other's chunks.
            c.execute(select(versions.c.id).where(versions.c.id==version_id).with_for_update()).first()
            claim=getattr(self._job_context,'index_claim',None)
            if claim:
                active=c.execute(select(index_jobs).where(index_jobs.c.id==claim['id']).with_for_update()).mappings().first()
                if not active or active['status']!='running' or active['owner']!=claim['owner'] or active['generation']!=claim['generation'] or active['lease_until']<now:
                    raise ValueError('STALE_INDEX_WORKER')
            for key,entry in encoded.items():
                # Different versions may share a cache key. ON CONFLICT avoids poisoning
                # a PostgreSQL transaction when another index worker inserts it first.
                if self.db.engine.dialect.name=='postgresql':
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                inserted=c.execute(insert(cache).values(**entry).on_conflict_do_nothing(index_elements=['key']))
                new_count+=max(inserted.rowcount,0)
                found[key]=dict(c.execute(select(cache).where(cache.c.key==key)).mappings().one())
            from .search_schema import projection
            c.execute(projection.delete().where(projection.c.version_id==version_id))
            c.execute(chunks.delete().where(chunks.c.version_id==version_id))
            if items:
                c.execute(chunks.insert(),[{'id':uid(),'version_id':version_id,'ordinal':i,
                    'heading':item['heading'],'locator':item['locator'],'text':item['text'],
                    'cache_id':found[digest(model.signature+'\0'+item['input'])]['id']} for i,item in enumerate(items)])
            c.execute(versions.update().where(versions.c.id==version_id).values(indexed_at=now))
            values={'status':'ready','model_signature':model.signature,'updated_at':now,'error':None}
            if c.execute(select(index_state.c.version_id).where(index_state.c.version_id==version_id)).first():
                c.execute(index_state.update().where(index_state.c.version_id==version_id).values(**values))
            else:c.execute(index_state.insert().values(version_id=version_id,**values))
            c.execute(events.update().where(events.c.new_version_id==version_id).values(detail={
                'new_vectors':new_count,'reused_vectors':len(items)-new_count,'chunks':len(items),'index_status':'ready'}))
            from .search import project_version
            project_version(self,version_id,connection=c)
            from .monitor_schema import monitor_events
            c.execute(monitor_events.insert().values(kind='index_updated',at=now,detail={'version_id':version_id}))
        return {'version_id':version_id,'new_vectors':new_count,'reused_vectors':len(items)-new_count,'chunks':len(items)}

    def _publish_inline(self,source,run_id,generation,url,page,response,doc,metrics):
        now=time.time();model=self.model()
        old=self.db.one(select(versions).where(versions.c.id==page["last_version_id"])) if page and page["last_version_id"] else None
        signature=self.pipeline_signature(source)
        if old and old["hash"]==doc.hash and old["signature"]==signature and page["availability"]!="deleted":
            self._unchanged(source,run_id,generation,page,response,metrics)
            with self.db.tx() as c:
                self._guard(c,source["id"],run_id,generation)
                c.execute(update(pages).where(pages.c.id==page["id"]).values(
                    etag=response.headers.get("etag"),last_modified=response.headers.get("last-modified"),audit_at=now))
            return
        items=chunk(doc,model);vectors=[];new_vectors=0;reused=0
        for item in items:
            key=digest(model.signature+"\0"+item["input"])
            prior=self.db.one(select(cache).where(cache.c.key==key))
            if prior:reused+=1;vectors.append((item,prior))
            else:
                vec=model.encode(item["input"])
                entry={"id":uid(),"key":key,"signature":model.signature,"input":item["input"],"vector":vec}
                # Cache writes can survive a later publication failure.
                with self.db.tx() as c:
                    self._guard(c,source["id"],run_id,generation)
                    prior=c.execute(select(cache).where(cache.c.key==key)).mappings().first()
                    if prior:entry=dict(prior)
                    else:c.execute(cache.insert().values(**entry))
                new_vectors+=1;vectors.append((item,entry))
        raw_hash=digest(response.body)
        raw_dir=config.DATA/"artifacts";raw_dir.mkdir(exist_ok=True)
        raw_path=raw_dir/raw_hash
        if not raw_path.exists():raw_path.write_bytes(response.body)
        with self.db.tx() as c:
            self._guard(c,source["id"],run_id,generation)
            current=c.execute(select(pages).where(pages.c.source_id==source["id"],pages.c.url==url).with_for_update()).mappings().first()
            if (current["last_version_id"] if current else None)!=(page["last_version_id"] if page else None):
                raise ValueError("STALE_PAGE")
            page_id=current["id"] if current else uid()
            if not current:
                c.execute(pages.insert().values(id=page_id,source_id=source["id"],url=url))
            number=(c.execute(select(func.max(versions.c.number)).where(versions.c.page_id==page_id)).scalar() or 0)+1
            version_id=uid()
            c.execute(versions.insert().values(id=version_id,page_id=page_id,number=number,title=doc.title,
                content=doc.content,hash=doc.hash,raw_hash=raw_hash,raw_key=raw_hash,
                observed_at=now,indexed_at=time.time(),signature=signature,sections=doc.sections))
            for i,(item,entry) in enumerate(vectors):
                c.execute(chunks.insert().values(id=uid(),version_id=version_id,ordinal=i,
                    heading=item["heading"],locator=item["locator"],text=item["text"],cache_id=entry["id"]))
            published_at=time.time()
            self._close(c,page_id,published_at)
            c.execute(intervals.insert().values(id=uid(),page_id=page_id,version_id=version_id,start=published_at))
            c.execute(versions.update().where(versions.c.id==version_id).values(indexed_at=published_at))
            kind="CREATED" if not old else ("RESTORED" if page["availability"]=="deleted" else
                 ("PIPELINE_REPROCESSED" if old["hash"]==doc.hash else "MODIFIED"))
            c.execute(pages.update().where(pages.c.id==page_id).values(title=doc.title,current_id=version_id,
                last_version_id=version_id,availability="active",health="healthy",checked_at=now,verified_at=now,
                missing_count=0,missing_at=None,missing_run=None,last_error=None,
                etag=response.headers.get("etag"),last_modified=response.headers.get("last-modified"),audit_at=now))
            c.execute(events.insert().values(id=uid(),page_id=page_id,run_id=run_id,kind=kind,
                old_version_id=old["id"] if old else None,new_version_id=version_id,at=now,
                detail={"new_vectors":new_vectors,"reused_vectors":reused,"chunks":len(items)}))
            from .search import project_version
            project_version(self,version_id,connection=c)
        metrics[kind.lower() if kind!="PIPELINE_REPROCESSED" else "modified"]+=1
        metrics["new_vectors"]+=new_vectors;metrics["reused_vectors"]+=reused
        self._observe(run_id,url,200,kind)

    def _missing(self,source,run_id,generation,page,metrics,suspend=False):
        now=time.time()
        with self.db.tx() as c:
            self._guard(c,source["id"],run_id,generation)
            p=c.execute(select(pages).where(pages.c.id==page["id"])).mappings().first()
            if p["availability"]=="deleted":
                c.execute(update(pages).where(pages.c.id==p["id"]).values(checked_at=now))
                return
            count=p["missing_count"]
            eligible=p["missing_run"]!=run_id and (p["missing_at"] is None or now-p["missing_at"]>=source["config"]["missing_interval"])
            if eligible:count+=1
            deleted=count>=3 and not suspend
            self._close(c,p["id"],now)
            values={"availability":"deleted" if deleted else "missing_candidate","checked_at":now,
                    "missing_count":count,"health":"source_unavailable",
                    "last_error":"Mass missing response: confirmation suspended" if suspend else "HTTP 404/410"}
            if eligible:values.update(missing_at=now,missing_run=run_id)
            if deleted:
                values["current_id"]=None
                c.execute(events.insert().values(id=uid(),page_id=p["id"],run_id=run_id,kind="DELETED",
                    old_version_id=p["last_version_id"],at=now,detail={"confirmations":count}))
            c.execute(pages.update().where(pages.c.id==p["id"]).values(**values))
        metrics["deleted" if deleted else "missing"]+=1

    def _error(self,source,run_id,generation,page,url,response,message):
        if page:
            with self.db.tx() as c:
                self._guard(c,source["id"],run_id,generation)
                status=response.status if response else 0
                blocked=status in (401,403) or "ROBOTS" in message or "Authentication" in message
                c.execute(pages.update().where(pages.c.id==page["id"]).values(
                    health="blocked" if blocked else "error",checked_at=time.time(),last_error=message[:1000],
                    # Never bind a failed candidate's validator to the current version.
                    etag=None,last_modified=None))
        self._observe(run_id,url,response.status if response else None,"ERROR",message)

    def history(self,page_id):
        self.get_page(page_id,metadata_only=True)
        return {"versions":self.db.all(select(versions.c.id,versions.c.number,versions.c.title,versions.c.observed_at,
                    versions.c.indexed_at,versions.c.hash).where(versions.c.page_id==page_id).order_by(versions.c.number)),
                "events":self.db.all(select(events).where(events.c.page_id==page_id).order_by(events.c.at)),
                "intervals":self.db.all(select(intervals).where(intervals.c.page_id==page_id).order_by(intervals.c.start))}

    def get_page(self,page_id,version=None,metadata_only=False):
        page=self.db.one(select(pages).where(pages.c.id==page_id))
        if not page:raise ValueError("PAGE_NOT_FOUND")
        if metadata_only:return page
        v=None
        if version is not None:
            v=self.db.one(select(versions).where(versions.c.page_id==page_id,versions.c.number==version))
            if not v:raise ValueError("VERSION_NOT_FOUND")
        elif page["availability"]=="active" and page["health"]!="blocked" and self.source(page["source_id"])["enabled"]:
            v=self.db.one(select(versions).where(versions.c.id==page["current_id"]))
        return {"page":page,"version":v,"historical":version is not None}

    def diff(self,page_id,v1,v2):
        a=self.get_page(page_id,v1)["version"];b=self.get_page(page_id,v2)["version"]
        lines=list(difflib.unified_diff(a["content"].splitlines(),b["content"].splitlines(),
            fromfile="version "+str(v1),tofile="version "+str(v2),lineterm=""))
        return {"page_id":page_id,"v1":v1,"v2":v2,"diff":"\n".join(lines),
                "added_lines":sum(x.startswith("+") and not x.startswith("+++") for x in lines),
                "removed_lines":sum(x.startswith("-") and not x.startswith("---") for x in lines)}

    def search(self,query,source_ids=None,limit=5,mode="current",as_of=None,include_unavailable=False):
        from .search import search
        return search(self,query,source_ids,limit,mode,as_of,include_unavailable)

    def overview(self):
        return {"sources":self.db.all(select(sources).order_by(sources.c.created_at)),
                "pages":self.db.all(select(pages).order_by(pages.c.title)),
                "runs":self.db.all(select(runs).order_by(runs.c.created_at.desc()).limit(30)),
                "changes":self.db.all(select(events, pages.c.title,pages.c.url).join(
                    pages,events.c.page_id==pages.c.id).order_by(events.c.at.desc()).limit(50)),
                "database":self.db.engine.dialect.name,"embedding_mode":config.EMBEDDER}

    def worker_once(self):
        if not self.inline_index:
            from .jobs import Jobs
            jobs=Jobs(self);jobs.scheduler_once()
            return jobs.capture_once()
        now=time.time()
        # Recover abandoned running work even when the source uses manual scheduling.
        expired=self.db.all(select(sources).where(sources.c.enabled.is_(True),
            sources.c.lease_run.is_not(None),sources.c.lease_until<now))
        for old in expired:
            self.enqueue(old["id"])
        for s in self.db.all(select(sources).where(sources.c.enabled.is_(True),sources.c.paused.is_(False),sources.c.next_due<=now)):
            self.enqueue(s["id"])
        job=self.db.one(select(runs).where(runs.c.status=="queued").order_by(runs.c.created_at))
        if job:return self.run(job["id"])
        return None

    def set_source(self,source_id,enabled=None,paused=None):
        values={}
        if enabled is not None:values["enabled"]=bool(enabled)
        if paused is not None:values["paused"]=bool(paused)
        with self.db.tx() as c:
            s=c.execute(select(sources).where(sources.c.id==source_id).with_for_update()).mappings().first()
            if not s:raise ValueError("SOURCE_NOT_FOUND")
            if enabled is False:
                values.update(generation=s["generation"]+1,lease_until=0,lease_run=None)
                c.execute(runs.update().where(runs.c.source_id==source_id,runs.c.status.in_(["queued","running"])).values(
                    status="cancelled",error="Source disabled",finished_at=time.time()))
            c.execute(sources.update().where(sources.c.id==source_id).values(**values))
        return self.source(source_id)
