"""Server-built citation snapshots from validated structured observations."""
import json,time
from sqlalchemy import select,func,and_,or_
from .db import sources
from .monitor_schema import monitors,monitor_revisions,monitor_observations,monitor_field_states
from .embedding import tokens,STOPWORDS

def retrieve(service,query,source_ids=None,mode='current',as_of=None,limit=8):
    o=monitor_observations;r=monitor_revisions;m=monitors
    cols=[o,r.c.fields,r.c.number,m.c.name.label('monitor_name'),sources.c.name.label('source_name'),
          sources.c.id.label('source_id'),sources.c.config]
    stmt=select(*cols).select_from(o.join(r,o.c.revision_id==r.c.id).join(m,o.c.monitor_id==m.c.id)
        .join(sources,m.c.source_id==sources.c.id)).where(sources.c.enabled.is_(True),o.c.status=='ok',o.c.capture_id.is_not(None))
    if source_ids is not None:stmt=stmt.where(sources.c.id.in_(source_ids))
    else:stmt=stmt.where(sources.c.config['demo'].as_boolean().is_not(True),
        func.coalesce(sources.c.config['source_kind'].as_string(),'normal')=='normal')
    if mode=='current':
        stmt=stmt.join(monitor_field_states,and_(monitor_field_states.c.observation_id==o.c.id,
            monitor_field_states.c.revision_id==m.c.revision_id)).add_columns(
            monitor_field_states.c.status.label('current_status'),monitor_field_states.c.error.label('current_error'),
            monitor_field_states.c.last_verified_at)
        # Retained values on unavailable pages are evidence history, never current facts.
        stmt=stmt.where(monitor_field_states.c.status!='unavailable')
    else:
        newer=o.alias('newer');newer_r=r.alias('newer_revision')
        # Latest attempt at the requested time must itself have been valid.
        stmt=stmt.where(o.c.at<=as_of,~select(newer.c.id).where(newer.c.monitor_id==o.c.monitor_id,
            newer.c.field_id==o.c.field_id,newer.c.at<=as_of,
            or_(newer.c.at>o.c.at,and_(newer.c.at==o.c.at,newer.c.id>o.c.id))).exists(),
            ~select(newer_r.c.id).where(newer_r.c.monitor_id==m.c.id,newer_r.c.created_at<=as_of,newer_r.c.number>r.c.number).exists())
    qt=set(tokens(query))-STOPWORDS
    # Name/value terms filter in SQL before the bounded candidate set; no model needed.
    terms=sorted(qt)[:16]
    if terms:
        stmt=stmt.where(or_(*[or_(m.c.name.ilike('%'+term.replace('%','')+'%'),o.c.raw_text.ilike('%'+term.replace('%','')+'%'),
            # Field definitions are JSON; casting includes reviewed field names.
            r.c.fields.cast(__import__('sqlalchemy').Text).ilike('%'+term.replace('%','')+'%')) for term in terms]))
    rows=service.db.all(stmt.order_by(o.c.at.desc()).limit(200))
    candidates=[]
    for row in rows:
        field=next((field for field in row['fields'] if field['id']==row['field_id']),None)
        if not field:continue
        name=field['name'];terms=set(tokens(name+' '+row['monitor_name']+' '+row['source_name']))
        score=3*len(qt & terms)+len(qt & set(tokens(row['raw_text'] or '')))
        if not score:continue
        value=row['value'];shown=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
        text=name+': '+shown+((' '+row['unit']) if row['unit'] else '')+(('; reporting period: '+row['period']) if row['period'] else '')
        if row['raw_text'] and row['raw_text']!=shown:text+='\nSource text: '+row['raw_text']
        warnings=[]
        verified=row.get('last_verified_at') or row['at']
        if mode=='as_of':warnings.append('Historical observation collected by Parity')
        else:
            if time.time()-verified>row['config'].get('interval',900):warnings.append('Verification is older than the polling interval')
            if row.get('current_status')!='ok':warnings.append(row.get('current_error') or 'The last check could not verify this retained value')
        candidates.append({'evidence_type':'monitor','chunk_id':row['id'],'snapshot_id':row['id'],
            'page_id':row['page_id'] or row['capture_id'],'version_id':row['revision_id'],'number':row['number'],
            'capture_id':row['capture_id'],'monitor_id':row['monitor_id'],'field_id':row['field_id'],
            'title':name+' — '+row['source_name'],'text':text[:10000],'url':row['url'],'locator':row['locator'],
            'last_verified_at':verified,'period':row['period'],'unit':row['unit'],'value':value,'warnings':warnings,'score':score})
    return sorted(candidates,key=lambda item:-item['score'])[:limit]
