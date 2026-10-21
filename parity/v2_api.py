"""Bounded operational queries and committed monitoring event notifications."""
import asyncio,base64,json,os,time
from fastapi import APIRouter,Query,Request,HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select,func,and_,or_
from .db import sources,pages,runs,events,versions
from .job_schema import url_jobs,index_jobs,worker_status
from .monitor_schema import monitor_events,monitor_changes,monitors,monitor_observations

def service_status(service):
    now=time.time()
    workers=service.db.all(select(worker_status).where(worker_status.c.heartbeat_at>now-30))
    result={}
    for key,roles in [('monitoring',('capture','scheduler')),('indexing',('index',)),('automation',('automation',)),('notifications',('notification',))]:
        relevant=[w for w in workers if w['role'] in roles]
        ready=all(any(w['role']==r and w['status'] in ('ready','working') for w in relevant) for r in roles)
        result[key]={'status':'ready' if ready else ('degraded' if relevant else 'stopped'),'workers':relevant,
            'error':next((w['detail'] for w in relevant if w['status']=='error'),None)}
    result['worker']=result['monitoring']
    try:
        import httpx
        with httpx.Client(trust_env=False,timeout=.8) as client:
            response=client.get(os.getenv('PARITY_EMBEDDING_URL','http://127.0.0.1:8092')+'/health/ready')
            result['embedding']=response.json()
    except Exception:result['embedding']={'status':'unavailable','error':'Start the embedding service to enable semantic search. Website monitoring continues.'}
    if result['embedding'].get('status')!='ready' and result['indexing']['status']!='stopped':
        result['indexing'].update(status='degraded',error='Embedding service unavailable. Captures and monitored values continue; indexing will retry.')
    return result

def _normal(stmt):
    return stmt.where(sources.c.config['demo'].as_boolean().is_not(True),
        func.coalesce(sources.c.config['source_kind'].as_string(),'normal')=='normal')

def paginate(db,stmt,sort,idcol,limit,cursor):
    total_stmt=select(func.count()).select_from(stmt.order_by(None).subquery())
    with db.engine.connect() as c:total=c.execute(total_stmt).scalar_one()
    if cursor:
        try:
            value,key=json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            stmt=stmt.where(or_(sort<value,and_(sort==value,idcol<key)))
        except Exception:raise ValueError('Invalid page cursor; refresh this list')
    rows=db.all(stmt.order_by(sort.desc(),idcol.desc()).limit(limit+1))
    more=len(rows)>limit;rows=rows[:limit]
    # Explicit aliases isolate continuation fields from joined columns.
    next_cursor=base64.urlsafe_b64encode(json.dumps([rows[-1]['_cursor_at'],rows[-1]['_cursor_id']]).encode()).decode() if more else None
    for row in rows:row.pop('_cursor_at',None);row.pop('_cursor_id',None)
    return {'items':rows,'next_cursor':next_cursor,'total':total}

def event_batch(db, cursor):
    bounds=db.one(select(func.min(monitor_events.c.id).label('first'),func.max(monitor_events.c.id).label('last')))
    latest=bounds['last'] or 0
    if cursor>latest or (cursor and bounds['first'] and cursor<bounds['first']-1):
        return latest, None
    rows=db.all(select(monitor_events).where(monitor_events.c.id>cursor).order_by(monitor_events.c.id).limit(201))
    return (latest,None) if len(rows)>200 else (cursor,rows)

def create_router(service,chat):
    from .monitoring import MonitorService
    monitor=MonitorService(service);router=APIRouter()
    from .automation_api import create_automation_router
    router.include_router(create_automation_router(service))

    @router.get('/api/list/{kind}')
    def listing(kind:str,source_id:str|None=None,cursor:str|None=None,limit:int=Query(50,ge=1,le=200),include_demo:bool=False,status:str|None=None,q:str|None=None,kind_filter:str|None=Query(None,alias='kind'),removed:bool=False):
        if kind=='sources':
            table=sources;sort=sources.c.created_at;idcol=sources.c.id
            docs=select(func.count()).select_from(pages).where(pages.c.source_id==sources.c.id).correlate(sources).scalar_subquery()
            verified=select(func.max(pages.c.verified_at)).where(pages.c.source_id==sources.c.id).correlate(sources).scalar_subquery()
            stmt=select(sources,docs.label('document_count'),verified.label('last_verified_at'))
        elif kind=='documents':
            table=pages;sort=func.coalesce(pages.c.checked_at,0);idcol=pages.c.id
            stmt=select(pages,versions.c.indexed_at).join(sources,pages.c.source_id==sources.c.id).outerjoin(versions,pages.c.current_id==versions.c.id)
        elif kind=='jobs':
            table=runs;sort=runs.c.created_at;idcol=runs.c.id
            stmt=select(runs).join(sources,runs.c.source_id==sources.c.id)
        elif kind=='url-jobs':
            table=url_jobs;sort=url_jobs.c.created_at;idcol=url_jobs.c.id
            stmt=select(url_jobs).join(sources,url_jobs.c.source_id==sources.c.id)
        elif kind=='changes':
            table=events;sort=events.c.at;idcol=events.c.id
            stmt=select(events,pages.c.title,pages.c.url,pages.c.source_id).join(pages,events.c.page_id==pages.c.id).join(sources,pages.c.source_id==sources.c.id)
        elif kind=='field-changes':
            table=monitor_changes;sort=table.c.at;idcol=table.c.id
            stmt=select(table,monitors.c.source_id).join(monitors,table.c.monitor_id==monitors.c.id).join(sources,monitors.c.source_id==sources.c.id)
        else:raise HTTPException(404,'Unknown list')
        if kind=='sources':stmt=stmt.where(sources.c.removed_at.is_not(None) if removed else sources.c.removed_at.is_(None))
        if source_id:stmt=stmt.where(sources.c.id==source_id)
        if q:
            needle=q[:200].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            stmt=stmt.where(or_(sources.c.name.ilike('%'+needle+'%',escape='\\'),sources.c.root_url.ilike('%'+needle+'%',escape='\\')))
        if not include_demo:stmt=_normal(stmt)
        if status and 'status' in table.c:stmt=stmt.where(table.c.status==status)
        if kind_filter and 'kind' in table.c:stmt=stmt.where(table.c.kind==kind_filter)
        stmt=stmt.add_columns(sort.label('_cursor_at'),idcol.label('_cursor_id'))
        result=paginate(service.db,stmt,sort,idcol,limit,cursor)
        if kind=='sources':
            for row in result['items']:row['is_demo']=row['config'].get('demo',False) or row['config'].get('source_kind')=='demo'
        return result

    @router.post('/api/monitors/preview')
    def preview(body:dict):return monitor.automation_preview(monitor.preview(body),body)
    @router.post('/api/monitors/auto-preview')
    def auto_preview(body:dict):return monitor.auto_preview(body)
    @router.post('/api/monitors')
    def activate(body:dict):return monitor.activate(body)
    @router.get('/api/monitors')
    def monitors_list(source_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):return monitor.list_monitors(source_id,limit,cursor)
    @router.get('/api/monitor-changes')
    def tracked_changes(source_id:str|None=None,monitor_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:str|None=None,include_demo:bool=False,kind:str|None=None,q:str|None=None):
        return monitor.changes(source_id,monitor_id,limit,cursor,include_demo,kind,q)
    @router.patch('/api/monitors/{monitor_id}')
    def revise(monitor_id:str,body:dict):
        if set(body)=={'paused'}:
            if not isinstance(body['paused'],bool):raise ValueError('paused must be true or false')
            return monitor.set_paused(monitor_id,body['paused'])
        return monitor.revise(monitor_id,body)
    @router.get('/api/monitors/{monitor_id}/history')
    def history(monitor_id:str,field_id:str,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):
        found=service.db.one(select(monitors.c.id).where(monitors.c.id==monitor_id))
        if not found:raise HTTPException(404,'Monitor not found')
        # A field ID must belong to this monitor, including previous revisions.
        from .monitor_schema import monitor_revisions
        revisions=service.db.all(select(monitor_revisions.c.fields).where(monitor_revisions.c.monitor_id==monitor_id))
        if not any(f['id']==field_id for revision in revisions for f in revision['fields']):raise HTTPException(404,'Field not found')
        return monitor.history(field_id,limit,cursor,monitor_id=monitor_id)
    @router.get('/api/captures/{capture_id}')
    def evidence(capture_id:str):return monitor.evidence(capture_id)
    @router.get('/api/dashboard')
    def dashboard(source_id:str|None=None,include_demo:bool=False,limit:int=Query(50,ge=1,le=100),cursor:str|None=None):return monitor.dashboard(source_id,include_demo,limit,cursor)
    @router.get('/api/dashboard/widgets')
    def widgets(monitor_ids:list[str]=Query(min_length=1,max_length=100),source_id:str|None=None,include_demo:bool=False):
        return monitor.dashboard(source_id,include_demo,100,monitor_ids=monitor_ids)
    @router.get('/api/dashboard/series')
    def read_dashboard_series(fields:list[str]=Query(min_length=1,max_length=50),start:float|None=None,end:float|None=None):
        from .series import dashboard_series
        if any(len(field)>400 for field in fields):raise ValueError('Invalid series identity.')
        payload={'fields':[json.loads(field) for field in fields]}
        if start is not None:payload['start']=start
        if end is not None:payload['end']=end
        return dashboard_series(service,payload)
    @router.post('/api/dashboard/series')
    def dashboard_series(body:dict):
        from .series import dashboard_series
        return dashboard_series(service,body)
    @router.get('/api/dashboard/layout')
    def get_layout():return monitor.layout()
    @router.put('/api/dashboard/layout')
    def put_layout(body:dict):return monitor.layout(body)
    @router.get('/api/events')
    async def stream(request:Request,after:int|None=None):
        raw=request.headers.get('last-event-id') or after or 0
        try:cursor=max(0,int(raw))
        except ValueError:raise HTTPException(400,'Invalid event ID')
        async def generate():
            nonlocal cursor
            ticks=0
            while not await request.is_disconnected():
                watermark,rows=await asyncio.to_thread(event_batch,service.db,cursor)
                if rows is None:
                    cursor=watermark
                    yield f'id: {cursor}\nevent: reset\ndata: {{"reason":"refresh_snapshot"}}\n\n'
                else:
                    for row in rows:
                        cursor=row['id']
                        yield f'id: {cursor}\nevent: update\ndata: {json.dumps(row)}\n\n'
                ticks+=1
                if ticks%15==0:yield ': keepalive\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return router
