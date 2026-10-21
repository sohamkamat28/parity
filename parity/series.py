"""Bounded, evidence-backed series for a page of dashboard widgets."""
import math
import time
from sqlalchemy import select, func, case, cast, Float, Text, Integer, and_, or_
from .db import sources
from .monitor_schema import monitors, monitor_revisions, monitor_observations as obs


def dashboard_series(service, payload):
    fields=payload.get('fields')
    if not isinstance(fields,list) or not 1<=len(fields)<=50:
        raise ValueError('Request between 1 and 50 fields.')
    calculated=[f for f in fields if isinstance(f,dict) and f.get('kind')=='calculated']
    if calculated:
        from .automation_series import calculated_series
        result=calculated_series(service,{**payload,'fields':calculated})
        extracted=[f for f in fields if f not in calculated]
        if extracted:result['items']+=dashboard_series(service,{**payload,'fields':extracted})['items']
        return result
    identities=[]
    for field in fields:
        if not isinstance(field,dict) or any(not isinstance(field.get(k),str) or not 1<=len(field[k])<=100 for k in ('monitor_id','field_id')):
            raise ValueError('Each series needs a monitor_id and field_id.')
        identities.append((field['monitor_id'],field['field_id']))
    identities=list(dict.fromkeys(identities))
    end=payload.get('end',time.time())
    if type(end) not in (int,float) or not math.isfinite(end):raise ValueError('Invalid series end time.')
    start=payload.get('start',end-7*86400)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<end-start<=30*86400:
        raise ValueError('Choose a time range of up to 30 days.')
    definitions=service.db.all(select(monitors.c.id,monitor_revisions.c.fields,sources.c.config['interval'].as_float().label('interval')).join(
        monitor_revisions,monitors.c.revision_id==monitor_revisions.c.id).join(sources,monitors.c.source_id==sources.c.id)
        .where(monitors.c.id.in_({m for m,f in identities}),sources.c.removed_at.is_(None)))
    permitted={(r['id'],f['id']) for r in definitions for f in r['fields'] if f['type'] in ('number','currency','percentage')}
    if any(identity not in permitted for identity in identities):raise ValueError('A requested numeric field is unavailable.')
    expected=case({r['id']:r['interval'] for r in definitions},value=obs.c.monitor_id,else_=900)
    bucket=cast(func.floor((obs.c.at-start)/(end-start)*47),Integer)
    base=select(obs.c.id,obs.c.monitor_id,obs.c.field_id,obs.c.revision_id,obs.c.at,obs.c.status,
        obs.c.value,obs.c.unit,obs.c.period,obs.c.capture_id,obs.c.error,bucket.label('bucket'),expected.label('interval'),
        func.lag(obs.c.at).over(partition_by=[obs.c.monitor_id,obs.c.field_id],order_by=[obs.c.at,obs.c.id]).label('previous_at'),
        func.count().over(partition_by=[obs.c.monitor_id,obs.c.field_id]).label('total')).where(
        or_(*[and_(obs.c.monitor_id==m,obs.c.field_id==f) for m,f in identities]),obs.c.at>=start,obs.c.at<=end).subquery()
    group=[base.c.monitor_id,base.c.field_id,base.c.bucket]
    good=base.c.status=='ok'
    # Four representatives per time bucket preserve endpoints and local extrema.
    # Failures mark the whole bucket as a gap, even if that failure isn't sampled.
    numeric=case((good,cast(func.replace(cast(base.c.value,Text),'"',''),Float)),else_=None)
    signature=func.coalesce(base.c.revision_id,'')+'|'+func.coalesce(base.c.unit,'')+'|'+func.coalesce(base.c.period,'')
    ranked=select(base,
        func.row_number().over(partition_by=group,order_by=[base.c.at,base.c.id]).label('first'),
        func.row_number().over(partition_by=group,order_by=[base.c.at.desc(),base.c.id.desc()]).label('last'),
        func.row_number().over(partition_by=group,order_by=[case((good,0),else_=1),numeric,base.c.at,base.c.id]).label('low'),
        func.row_number().over(partition_by=group,order_by=[case((good,0),else_=1),numeric.desc(),base.c.at,base.c.id]).label('high'),
        func.max(case((or_(~good,base.c.at-base.c.previous_at>base.c.interval*2),1),else_=0)).over(partition_by=group).label('has_gap'),
        (func.min(signature).over(partition_by=group)!=func.max(signature).over(partition_by=group)).label('has_transition')).subquery()
    rows=service.db.all(select(ranked).where(or_(ranked.c.total<=200,ranked.c.first==1,ranked.c.last==1,ranked.c.low==1,ranked.c.high==1))
        .order_by(ranked.c.monitor_id,ranked.c.field_id,ranked.c.at,ranked.c.id))
    grouped={identity:[] for identity in identities}
    for row in rows:grouped[(row['monitor_id'],row['field_id'])].append(row)
    result=[]
    for (monitor_id,field_id),values in grouped.items():
        points=[];previous=None
        for row in values:
            number=None
            if row['status']=='ok':
                try:
                    number=float(row['value'])
                    if not math.isfinite(number):number=None
                except (TypeError,ValueError):pass
            signature=(row['revision_id'],row['unit'],row['period'])
            point={k:row[k] for k in ('id','at','status','value','unit','period','revision_id','capture_id','error')}
            gap=(row['has_gap'] or row['has_transition']) if row['total']>200 else (row['previous_at'] is not None and row['at']-row['previous_at']>row['interval']*2)
            point.update(number=number,break_before=bool(gap or previous is None or previous!=signature))
            points.append(point);previous=signature if number is not None else None
        result.append(dict(monitor_id=monitor_id,field_id=field_id,points=points,total=values[0]['total'] if values else 0,
            sampled=bool(values and values[0]['total']>len(points)),sampling='time_bucket_endpoints_and_extrema',max_points=200))
    return dict(items=result,start=start,end=end)
