"""Two-query bounded series across any visible calculated fields."""
import math,time
from sqlalchemy import select,func,or_,and_,case,cast,Integer
from . import automation_schema as a


def calculated_series(service,payload):
    fields=payload['fields'];end=payload.get('end',time.time());start=payload.get('start',end-604800)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<end-start<=2592000:raise ValueError('Choose a time range of up to 30 days.')
    identities=[]
    for item in fields:
        if any(not isinstance(item.get(k),str) or not 1<=len(item[k])<=120 for k in ('automation_id','field_id')):raise ValueError('Calculated series require automation_id and field_id.')
        identities.append((item['automation_id'],item['field_id']))
    identities=list(dict.fromkeys(identities))
    definitions=service.db.all(select(a.automations.c.id,a.automation_revisions.c.plan).join(a.automation_revisions,a.automations.c.revision_id==a.automation_revisions.c.id).where(a.automations.c.id.in_({i for i,f in identities}),a.automations.c.archived_at.is_(None)))
    allowed={(r['id'],o['id']) for r in definitions for o in r['plan']['outputs']}
    if any(i not in allowed for i in identities):raise ValueError('Calculated field unavailable.')
    table=a.automation_values
    partition=[table.c.automation_id,table.c.field_id]
    bucket=cast(func.floor((table.c.at-start)/(end-start)*47),Integer)
    base=select(table,bucket.label('bucket'),func.count().over(partition_by=partition).label('total'),
        func.lag(table.c.at).over(partition_by=partition,order_by=[table.c.at,table.c.evaluation_id]).label('previous_at')).where(
        or_(*[and_(table.c.automation_id==i,table.c.field_id==f) for i,f in identities]),table.c.at>=start,table.c.at<=end).subquery()
    partition=[base.c.automation_id,base.c.field_id,base.c.bucket]
    signature=func.coalesce(base.c.revision_id,'')+'|'+func.coalesce(base.c.unit,'')+'|'+func.coalesce(base.c.period,'')
    interval=case({r['id']:r['plan'].get('interval',60) for r in definitions},value=base.c.automation_id,else_=60)
    ranked=select(base,func.row_number().over(partition_by=partition,order_by=[base.c.at,base.c.evaluation_id]).label('first'),
        func.row_number().over(partition_by=partition,order_by=[base.c.at.desc(),base.c.evaluation_id.desc()]).label('last'),
        func.row_number().over(partition_by=partition,order_by=[case((base.c.number.is_(None),1),else_=0),base.c.number,base.c.at,base.c.evaluation_id]).label('low'),
        func.row_number().over(partition_by=partition,order_by=[case((base.c.number.is_(None),1),else_=0),base.c.number.desc(),base.c.at,base.c.evaluation_id]).label('high'),
        func.max(case((or_(base.c.status!='ok',base.c.at-base.c.previous_at>interval*2),1),else_=0)).over(partition_by=partition).label('gap'),
        (func.min(signature).over(partition_by=partition)!=func.max(signature).over(partition_by=partition)).label('transition')).subquery()
    rows=service.db.all(select(ranked).where(or_(ranked.c.total<=200,ranked.c.first==1,ranked.c.last==1,ranked.c.low==1,ranked.c.high==1)).order_by(ranked.c.automation_id,ranked.c.field_id,ranked.c.at,ranked.c.evaluation_id))
    groups={key:[] for key in identities}
    for row in rows:groups[(row['automation_id'],row['field_id'])].append(row)
    result=[]
    for (auto_id,field_id),values in groups.items():
        previous=None;points=[]
        for row in values:
            signature=(row['revision_id'],row['unit'],row['period']);number=row['number']
            point={k:row[k] for k in ('evaluation_id','at','value','unit','period','status','error','revision_id')}
            gap=(row['gap'] or row['transition']) if row['total']>200 else row['previous_at'] is not None and row['at']-row['previous_at']>next(r['plan'].get('interval',60) for r in definitions if r['id']==auto_id)*2
            point.update(id=row['evaluation_id']+':'+field_id,number=number,break_before=bool(previous!=signature or gap))
            points.append(point);previous=signature if number is not None else None
        result.append(dict(kind='calculated',automation_id=auto_id,field_id=field_id,points=points,total=values[0]['total'] if values else 0,sampled=bool(values and values[0]['total']>len(points)),sampling='time_bucket_endpoints_and_extrema',max_points=200))
    return {'items':result,'start':start,'end':end}
