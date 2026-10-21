"""Immutable server-calculated evidence for current and historical chat retrieval."""
import json
import re
import time
from datetime import datetime, timezone
from sqlalchemy import select, and_, or_, Text
from . import automation_schema as a, monitor_schema as m
from .db import sources
from .embedding import tokens, STOPWORDS


def _date(at):
    try:return datetime.fromtimestamp(float(at),timezone.utc).isoformat(timespec='seconds')
    except (TypeError,ValueError,OverflowError):return 'unknown'


def _formula(node,names,depth=0):
    if not isinstance(node,dict) or depth>20:return '[invalid expression]'
    op=node.get('op','')
    if op in ('input','parameter','output'):return names.get((op,node.get('id')),str(node.get('id','?')))
    if op=='constant':return str(node.get('value'))+(' '+node['unit'] if node.get('unit') else '')
    if op in ('previous','baseline','window_average','window_min','window_max','table_sum','table_average','table_min','table_max','table_count','list_count'):
        details=[names.get(('input',node.get('id')),str(node.get('id')))]
        if node.get('seconds'):details.append(str(node['seconds'])+' seconds')
        if node.get('column'):details.append('column '+node['column'])
        if node.get('rows'):details.append('rows '+', '.join(node['rows']))
        return op+'('+', '.join(details)+')'
    args=[_formula(child,names,depth+1) for child in node.get('args',[])]
    if op=='convert':args.append(node.get('unit',''))
    operators={'add':' + ','sum':' + ','subtract':' − ','multiply':' × ','divide':' ÷ ','gt':' > ','gte':' ≥ ','lt':' < ','lte':' ≤ ','eq':' = ','ne':' ≠ ','and':' AND ','or':' OR '}
    return '('+operators[op].join(args)+')' if op in operators else op+'('+', '.join(args)+')'


def _history_rows(history):
    if isinstance(history,dict):
        for rows in history.values():
            if isinstance(rows,list):
                for row in rows:
                    if isinstance(row,dict):yield row
    elif isinstance(history,list):
        for entry in history:
            if isinstance(entry,dict):
                for row in entry.get('observations',[]):
                    if isinstance(row,dict):yield row


def _supporting(row):
    found={}
    for item in list(row.get('inputs') or [])+list(_history_rows(row.get('history'))):
        capture=item.get('capture_id')
        if not capture:continue
        observation=item.get('observation_id',item.get('id'))
        key=(capture,observation)
        if key in found:continue
        found[key]={key:item.get(key) for key in ('capture_id','value','unit','period','locator','at','url','source_id')}
        found[key]['id']=observation
    return list(found.values())


def _states(service,rows):
    bindings={(item.get('monitor_id'),item.get('field_id')) for row in rows for item in row['plan'].get('inputs',[])}
    monitor_ids={monitor for monitor,_ in bindings if monitor}
    if not monitor_ids:return {}
    query=select(m.monitor_field_states,m.monitors.c.paused.label('monitor_paused'),m.monitor_revisions.c.fields,
        sources.c.id.label('source_id'),sources.c.enabled.label('source_enabled'),sources.c.paused.label('source_paused'),
        sources.c.removed_at,sources.c.config).select_from(m.monitor_field_states.join(m.monitors,and_(
            m.monitor_field_states.c.monitor_id==m.monitors.c.id,m.monitor_field_states.c.revision_id==m.monitors.c.revision_id))
            .join(m.monitor_revisions,m.monitor_revisions.c.id==m.monitors.c.revision_id)
            .join(sources,m.monitors.c.source_id==sources.c.id)).where(m.monitors.c.id.in_(monitor_ids))
    return {(row['monitor_id'],row['field_id']):row for row in service.db.all(query) if (row['monitor_id'],row['field_id']) in bindings}


def _current_eligible(row,states,now):
    from .automation import definition_signature
    snapshots={item['id']:item for item in row.get('inputs') or []}
    for binding in row['plan'].get('inputs',[]):
        state=states.get((binding['monitor_id'],binding['field_id']));snapshot=snapshots.get(binding['id'])
        if not state or not snapshot or not state['source_enabled'] or state['source_paused'] or state['monitor_paused'] or state['removed_at'] is not None:return False
        if state['status']!='ok' or not state.get('last_verified_at') or now-state['last_verified_at']>state['config'].get('interval',900):return False
        definition=next((field for field in state['fields'] if field['id']==binding['field_id']),None)
        if not definition or definition_signature(definition)!=binding['signature']:return False
        # A committed newer input must wait for a calculation using that input.
        # A retained last-successful calculation is never promoted into a current answer.
        if snapshot.get('observation_id')!=state.get('observation_id'):return False
        if snapshot.get('period','')!=(state.get('period') or ''):return False
        if binding.get('source_unit',state.get('unit'))!=state.get('unit'):return False
    return True


def retrieve(service,query,source_ids=None,mode='current',as_of=None,limit=5):
    if mode not in ('current','as_of'):raise ValueError('Use current or as_of calculation retrieval.')
    if mode=='as_of' and (as_of is None or isinstance(as_of,bool) or not isinstance(as_of,(int,float))):raise ValueError('Historical calculations require an as-of timestamp.')
    if source_ids==[]:return []
    limit=max(1,min(int(limit),20))
    e,r,auto=a.automation_evaluations,a.automation_revisions,a.automations
    stmt=select(e,r.c.plan,r.c.number,auto.c.name.label('automation_name')).select_from(e.join(r,e.c.revision_id==r.c.id).join(auto,e.c.automation_id==auto.c.id))
    if mode=='current':
        current=a.automation_current
        stmt=stmt.join(current,and_(current.c.automation_id==auto.c.id,current.c.evaluation_id==e.c.id)).where(
            current.c.status=='ok',e.c.status=='ok',auto.c.paused.is_(False),auto.c.archived_at.is_(None),auto.c.revision_id==e.c.revision_id)
    else:
        newer=e.alias('newer_calculation');newer_revision=r.alias('newer_calculation_revision')
        stmt=stmt.where(e.c.at<=as_of,r.c.created_at<=as_of,e.c.status=='ok',
            ~select(newer.c.id).where(newer.c.automation_id==e.c.automation_id,newer.c.at<=as_of,
                or_(newer.c.at>e.c.at,and_(newer.c.at==e.c.at,newer.c.id>e.c.id))).exists(),
            ~select(newer_revision.c.id).where(newer_revision.c.automation_id==auto.c.id,newer_revision.c.created_at<=as_of,newer_revision.c.number>r.c.number).exists())
    dependencies=a.automation_dependencies
    if source_ids is not None:
        stmt=stmt.where(select(dependencies.c.input_id).where(dependencies.c.revision_id==r.c.id,dependencies.c.source_id.in_(source_ids)).exists())
    else:
        # Test-labelled inputs are excluded from default retrieval even if a user
        # creates an otherwise normal-looking calculation from them.
        test_dependencies=dependencies.join(sources,dependencies.c.source_id==sources.c.id)
        stmt=stmt.where(~select(dependencies.c.input_id).select_from(test_dependencies).where(dependencies.c.revision_id==r.c.id,
            or_(sources.c.config['demo'].as_boolean().is_(True),sources.c.config['source_kind'].as_string().in_(['demo','test']))).exists())
    qt=set(tokens(query))-STOPWORDS
    terms=sorted(qt)[:16]
    if terms:
        stmt=stmt.where(or_(*[or_(auto.c.name.ilike('%'+term+'%'),r.c.plan.cast(Text).ilike('%'+term+'%')) for term in terms]))
    rows=service.db.all(stmt.order_by(e.c.at.desc(),e.c.id.desc()).limit(100))
    states=_states(service,rows) if mode=='current' else {}
    result=[];now=time.time()
    for row in rows:
        if mode=='current' and not _current_eligible(row,states,now):continue
        plan=row['plan'];names={}
        for key,kind in [('inputs','input'),('parameters','parameter'),('outputs','output')]:
            names.update({(kind,item['id']):item.get('name',item['id']) for item in plan.get(key,[])})
        inputs=row.get('inputs') or [];source_names=' '.join(str(item.get('source_name','')) for item in inputs)
        supporting=_supporting(row)
        for output in row.get('outputs') or []:
            definition=next((item for item in plan.get('outputs',[]) if item['id']==output['id']),output)
            searchable=' '.join([row['automation_name'],output.get('name',''),source_names]+[item.get('name','') for item in plan.get('inputs',[])])
            score=3*len(qt & set(tokens(searchable)))
            if qt and not score:continue
            text=output.get('name',output['id'])+': '+str(output.get('value'))+(' '+output['unit'] if output.get('unit') else '')
            text+='\nCalculated by Parity at '+_date(row['at'])+'.'
            text+='\nFormula revision '+str(row['number'])+': '+_formula(definition.get('expression'),names)
            for item in plan.get('parameters',[]):text+='\nSupplied parameter '+item.get('name',item['id'])+': '+str(item['value'])+(' '+item['unit'] if item.get('unit') else '')
            for item in inputs:
                shown=json.dumps(item.get('value'),ensure_ascii=False) if isinstance(item.get('value'),(dict,list)) else str(item.get('value'))
                text+='\nInput '+item.get('name',item['id'])+': '+shown[:500]+(' '+item['unit'] if item.get('unit') else '')+('; reporting period '+str(item['period']) if item.get('period') else '')+'; verified '+_date(item.get('at'))+'.'
            history=row.get('history')
            if history:
                groups=history.items() if isinstance(history,dict) else [(str(i),entry.get('observations',[])) for i,entry in enumerate(history)]
                for key,observations in groups:
                    valid=[item for item in observations if isinstance(item,dict) and item.get('status','ok')=='ok']
                    times=[item['at'] for item in valid if item.get('at') is not None]
                    text+='\nHistory '+str(key)+': '+str(len(valid))+' supplied observations'+('; coverage '+_date(min(times))+' to '+_date(max(times)) if times else '')+'. Observation averages use collected samples; gaps are not interpolated.'
            warnings=['Historical calculation evaluated by Parity'] if mode=='as_of' else []
            verified=min((item['at'] for item in inputs if item.get('at') is not None),default=row['at'])
            result.append({'evidence_type':'calculation','chunk_id':row['id']+':'+output['id'],'snapshot_id':row['id'],
                'evaluation_id':row['id'],'automation_id':row['automation_id'],'field_id':output['id'],'page_id':row['automation_id'],
                'version_id':row['revision_id'],'number':row['number'],'title':output.get('name',output['id'])+' — '+row['automation_name'],
                'text':text[:10000],'url':'/api/calculations/'+row['id'],'locator':'Calculation revision '+str(row['number'])+' / '+output['id'],
                'last_verified_at':verified,'unit':output.get('unit',''),'value':output.get('value'),'warnings':warnings,'supporting_captures':supporting,'score':score})
    return sorted(result,key=lambda item:(-item['score'],-item['last_verified_at'],item['chunk_id']))[:limit]
