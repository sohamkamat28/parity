"""Database-backed operational queries shared by the API."""
from sqlalchemy import select, func
from .db import sources, pages, versions, events, runs, observations, cache


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
