"""Database-backed operational views and an authenticated local fixture bridge."""
import os
import time
import threading
import httpx
from sqlalchemy import select, func
from . import config
from .db import sources, pages, versions, events, runs, observations, demo_sessions, cache, uid


def overview(service):
    data=service.overview()
    totals={}
    for key,table in [('sources',sources),('documents',pages),('versions',versions),('changes',events)]:
        totals[key]=service.db.one(select(func.count().label('n')).select_from(table))['n']
    totals['active_documents']=service.db.one(select(func.count().label('n')).select_from(pages.join(sources,pages.c.source_id==sources.c.id)).where(
        pages.c.availability=='active',pages.c.health!='blocked',sources.c.enabled.is_(True)))['n']
    metrics=service.db.all(select(runs.c.metrics))
    for key in ('new_vectors','reused_vectors'):
        totals[key]=sum((r['metrics'] or {}).get(key,0) for r in metrics)
    totals['new_vectors']=service.db.one(select(func.count().label('n')).select_from(cache))['n']
    data['totals']=totals
    return data


def list_changes(service,source_id=None,kind=None,offset=0,limit=50):
    statement=select(events,pages.c.title,pages.c.url,pages.c.source_id).join(pages,events.c.page_id==pages.c.id)
    if source_id:statement=statement.where(pages.c.source_id==source_id)
    if kind:statement=statement.where(events.c.kind==kind)
    return service.db.all(statement.order_by(events.c.at.desc(),events.c.id).offset(offset).limit(limit))


def run_observations(service,run_id,offset=0,limit=100):
    if not service.db.one(select(runs.c.id).where(runs.c.id==run_id)):raise ValueError('RUN_NOT_FOUND')
    total=service.db.one(select(func.count().label('n')).select_from(observations).where(observations.c.run_id==run_id))['n']
    items=service.db.all(select(observations).where(observations.c.run_id==run_id).order_by(observations.c.at,observations.c.id).offset(offset).limit(limit))
    return {'items':items,'total':total,'offset':offset,'limit':limit}


class DemoService:
    def __init__(self,service):
        self.service=service
        self.lock=threading.Lock()

    def sessions(self):
        return {'sessions':self.service.db.all(select(demo_sessions).order_by(demo_sessions.c.created_at.desc()))}

    def get(self,session_id,with_state=True):
        row=self.service.db.one(select(demo_sessions).where(demo_sessions.c.id==session_id))
        if not row:raise ValueError('DEMO_SESSION_NOT_FOUND')
        if with_state:row['state']=self._portal(session_id,'state')
        return row

    def _portal(self,session_id,action,payload=None):
        token=os.getenv('DEMO_ADMIN_TOKEN','')
        if not token:raise ValueError('Portal controls are unavailable. Start both apps with run.py.')
        if len(session_id)!=32 or any(c not in '0123456789abcdef' for c in session_id):raise ValueError('Invalid demo session')
        url=config.DEMO_ORIGIN+'/demo/'+session_id+'/admin/'+action
        try:
            with httpx.Client(trust_env=False,timeout=10) as client:
                r=client.get(url,headers={'X-Demo-Token':token}) if action=='state' else client.post(url,headers={'X-Demo-Token':token},json=payload or {})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as error:
            raise ValueError('The local demonstration portal is unavailable or rejected the action. Restart using run.py.') from error

    def create(self,name=None):
        session_id=uid();base=config.DEMO_ORIGIN+'/demo/'+session_id
        name=(name or 'Demonstration '+time.strftime('%d %b %H:%M')).strip()[:100]
        self._portal(session_id,'reset')
        s=self.service.add_source(name+' / Campus',base+'/en/circulars/',{
            'demo':True,'allow':[f'/demo/{session_id}/en/'],'deny':[f'/demo/{session_id}/admin'],
            'seeds':[base+'/en/circulars/',base+'/en/sitemap.xml'],
            'discovery_only':[f'/demo/{session_id}/en/',f'/demo/{session_id}/en/circulars/',f'/demo/{session_id}/en/sitemap.xml'],
            'selector':'article','delay':0,'interval':15,'missing_interval':2})
        b=self.service.add_source(name+' / Live Lab',base+'/en/live/notice',{
            'demo':True,'allow':[f'/demo/{session_id}/en/live/'],'deny':[f'/demo/{session_id}/admin'],
            'selector':'article','render_mode':'browser','ready_selector':'article[data-ready="true"]',
            'delay':0,'interval':30,'missing_interval':2})
        row={'id':session_id,'name':name,'static_source_id':s['id'],'browser_source_id':b['id'],
             'portal_url':base+'/en/circulars/','created_at':time.time()}
        with self.service.db.tx() as c:c.execute(demo_sessions.insert().values(**row))
        return row

    def action(self,session_id,action,crawl=True,payload=None):
        allowed={'reset','modify-honours','noise-only','delete-scholarship','restore-scholarship',
                 'add-notice','modify-pdf','modify-live','fault','clear-faults','baseline','crawl','crawl-browser'}
        if action not in allowed:raise ValueError('Unknown demo action')
        with self.lock:
            session=self.get(session_id,False)
            source_id=session['browser_source_id'] if action in ('modify-live','crawl-browser') else session['static_source_id']
            existing=self.service.db.one(select(runs).where(runs.c.source_id==source_id,runs.c.status.in_(['queued','running'])))
            if existing:raise ValueError('Wait for the current crawl to finish before the next demonstration step.')
            state=self._portal(session_id,'state') if action in ('baseline','crawl','crawl-browser') else self._portal(session_id,action,payload).get('state')
            queued=[self.service.enqueue(source_id)] if crawl else []
            return {'state':state,'runs':queued,'session_id':session_id}
