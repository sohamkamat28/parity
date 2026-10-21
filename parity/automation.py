"""Validated, durable calculations over immutable monitoring observations."""
import copy
import math
import json
import re
import time
import uuid
from sqlalchemy import select, func, and_, or_
from . import automation_schema as a, monitor_schema as m
from .db import sources, uid
from .structured import fingerprint


def definition_signature(field):
    rule={k:v for k,v in field.get('rule',{}).items() if k!='url'}
    return fingerprint({'type':field['type'],'rule':rule})


def calculation_requested(instructions):
    return bool(re.search(r'\b(calculat\w*|budget|ratio|sum|total cost|material cost|percent(?:age)? change|alert|notify|threshold|average|convert|difference between)\b',instructions or '',re.I))


def enqueue_affected(connection,source_id,reason):
    """Called inside the capture/lifecycle transaction; no model or network work."""
    identities=connection.execute(select(a.automation_dependencies.c.revision_id,a.automations.c.id).join(
        a.automations,a.automations.c.revision_id==a.automation_dependencies.c.revision_id).where(
        a.automation_dependencies.c.source_id==source_id,a.automations.c.paused.is_(False),a.automations.c.archived_at.is_(None))).all()
    for revision_id,automation_id in set(identities):
        enqueue(connection,automation_id,revision_id,reason)


def enqueue(connection,automation_id,revision_id,reason):
    job_id=fingerprint([automation_id,revision_id,reason])[:32]
    if connection.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    connection.execute(insert(a.automation_jobs).values(id=job_id,automation_id=automation_id,revision_id=revision_id,
        reason=str(reason)[:300],status='queued',attempts=0,generation=0,lease_until=0,available_at=0,created_at=time.time())
        .on_conflict_do_nothing(index_elements=['id']))
    return job_id


def _event(c,kind,automation_id,**detail):
    c.execute(m.monitor_events.insert().values(kind=kind,at=time.time(),detail={'automation_id':automation_id,**detail}))


class Automations:
    def __init__(self,service):
        self.service,self.db=service,service.db
        self.owner=uuid.uuid4().hex

    def catalog(self,connection=None,monitor_draft_id=None):
        statement=select(m.monitors.c.id.label('monitor_id'),m.monitors.c.source_id,m.monitor_revisions.c.fields,
            sources.c.name.label('source_name'),m.monitors.c.name.label('monitor_name')).join(
            m.monitor_revisions,m.monitors.c.revision_id==m.monitor_revisions.c.id).join(sources,m.monitors.c.source_id==sources.c.id).where(sources.c.removed_at.is_(None))
        rows=connection.execute(statement).mappings().all() if connection is not None else self.db.all(statement)
        states_stmt=select(m.monitor_field_states).join(m.monitors,m.monitors.c.revision_id==m.monitor_field_states.c.revision_id)
        states=connection.execute(states_stmt).mappings().all() if connection is not None else self.db.all(states_stmt)
        state_map={(r['monitor_id'],r['field_id']):r for r in states}
        items=[]
        for row in rows:
            for field in row['fields']:
                state=state_map.get((row['monitor_id'],field['id']),{})
                items.append(dict(id=row['monitor_id']+':'+field['id'],field_id=field['id'],monitor_id=row['monitor_id'],source_id=row['source_id'],
                    source_name=row['source_name'],name=field['name'],monitor_name=row['monitor_name'],type=field['type'],
                    signature=definition_signature(field),value=state.get('value'),unit=state.get('unit') or '',period=state.get('period') or '',
                    status=state.get('status'),at=state.get('last_verified_at'),capture_id=state.get('capture_id')))
        if monitor_draft_id:
            draft=self.db.one(select(m.monitor_drafts).where(m.monitor_drafts.c.id==monitor_draft_id))
            if not draft:raise ValueError('Extraction preview not found. Preview the source again.')
            candidates={f['id']:f for f in draft['candidates'] if f.get('valid')}
            candidates.update({f['id']:f for f in draft['fields'] if f.get('valid')})
            for field in candidates.values():
                if field.get('enabled',True) and field.get('valid'):
                    preview=field.get('preview') or {}
                    items.append(dict(id='draft:'+draft['id']+':'+field['id'],field_id=field['id'],monitor_id='draft:'+draft['id'],source_id=draft['source']['id'],
                        source_name=draft['source']['name'],name=field['name'],type=field['type'],signature=definition_signature(field),
                        value=preview.get('value'),unit=preview.get('unit') or '',period=preview.get('period') or '',
                        status='ok',at=draft['created_at'],capture_id=draft['capture_id']))
        return items

    def preview(self,payload):
        from .automation_expr import validate_plan,evaluate_plan
        from .automation_planner import compile_instructions
        instructions=str(payload.get('instructions') or '')[:4000]
        draft_id=payload.get('monitor_draft_id')
        catalog=self.catalog(monitor_draft_id=draft_id)
        if payload.get('plan') is not None:
            proposed=copy.deepcopy(payload['plan'])
            known={(f['monitor_id'],f['field_id']):f for f in catalog}
            if isinstance(proposed,dict) and isinstance(proposed.get('inputs'),list):
                for binding in proposed['inputs']:
                    if not isinstance(binding,dict):continue
                    field=known.get((binding.get('monitor_id'),binding.get('field_id')))
                    if field:
                        binding.setdefault('signature',field['signature'])
                        if not binding.get('unit'):binding['unit']=field['unit']
                        binding.setdefault('name',field['name'])
            plan=validate_plan(proposed)
            compiled={'status':'ready','plan':plan,'questions':[]}
        else:
            compiled=compile_instructions(instructions,catalog,answers=payload.get('answers') or {},use_ai=payload.get('use_ai',True))
            plan=compiled.get('plan')
        status=compiled.get('status','needs_input');questions=compiled.get('questions') or []
        errors=[];result=None
        if status=='ready' and plan:
            plan=validate_plan(plan)
            known={(f['monitor_id'],f['field_id']):f for f in catalog}
            values={}
            for binding in plan['inputs']:
                field=known.get((binding.get('monitor_id'),binding.get('field_id')))
                if not field:raise ValueError('A calculation input is not an available monitored field.')
                if binding.get('signature') and binding['signature']!=field['signature']:raise ValueError('The extraction mapping changed. Preview again.')
                binding['signature']=field['signature'];binding['source_id']=field['source_id'];binding['source_unit']=field['unit'];binding.setdefault('name',field['name'])
                values[binding['id']]={**field,'unit':binding.get('unit') or field['unit']}
            try:
                result=evaluate_plan(plan,values,history=self._preview_history(plan))
            except (ValueError,LookupError,ArithmeticError) as exc:
                errors=[str(exc)]
                # Missing historical samples are allowed to start collecting; all
                # other invalid arithmetic is blocked until inputs are repaired.
                if str(exc) not in ('Not enough comparable observation history.','No previous comparable observation exists.','No observation history is available.'):
                    status='needs_input'
                    questions.append({'id':'calculation','question':str(exc)})
            if not plan.get('allow_cross_period') and len({v.get('period') for v in values.values() if v.get('period')})>1:
                status='needs_input';questions.append({'id':'periods','question':'The selected reporting periods differ. Choose matching inputs or explicitly allow cross-period calculation.'})
        row=dict(id=uid(),instructions=instructions,plan=plan,status=status,questions=questions,created_at=time.time(),monitor_draft_id=draft_id)
        with self.db.tx() as c:c.execute(a.automation_drafts.insert().values(**row))
        return dict(draft_id=row['id'],status=status,questions=questions,plan=plan,preview=result,catalog=catalog,errors=errors)

    def _preview_history(self,plan):
        def history(input_id,mode,seconds=None):
            binding=next(b for b in plan['inputs'] if b['id']==input_id)
            if binding['monitor_id'].startswith('draft:'):return []
            with self.db.engine.connect() as c:return self._history(c,binding,mode,seconds,time.time())
        return history

    def checked_draft(self,draft_id):
        row=self.db.one(select(a.automation_drafts).where(a.automation_drafts.c.id==draft_id))
        if not row or time.time()-row['created_at']>86400:raise ValueError('Calculation preview expired. Preview it again.')
        if row['status']!='ready':raise ValueError('Answer the calculation questions before starting monitoring.')
        return row

    def activate(self,payload,automation_id=None):
        draft=self.checked_draft(payload.get('draft_id'))
        if draft['monitor_draft_id'] and not draft['activated_id']:raise ValueError('Activate this calculation together with its source preview.')
        if draft['activated_id']:
            if automation_id and draft['activated_id']!=automation_id:raise ValueError('Preview belongs to a different automation.')
            return self.get(draft['activated_id'])
        with self.db.tx() as c:
            self._lock_sources(c,draft['plan'])
            identity=self._activate(c,draft,automation_id)
        return self.get(identity)

    def _lock_sources(self,c,plan):
        ids=sorted({b.get('source_id') for b in plan['inputs'] if b.get('source_id')})
        if ids:c.execute(select(sources.c.id).where(sources.c.id.in_(ids)).order_by(sources.c.id).with_for_update()).all()

    def _activate(self,c,draft,automation_id=None,remap=None):
        from .automation_expr import validate_plan
        locked=c.execute(select(a.automation_drafts).where(a.automation_drafts.c.id==draft['id']).with_for_update()).mappings().one()
        if locked['activated_id']:return locked['activated_id']
        plan=copy.deepcopy(draft['plan'])
        if remap:
            for binding in plan['inputs']:
                key=(binding['monitor_id'],binding['field_id'])
                if key in remap:binding.update(remap[key])
        plan=validate_plan(plan)
        known={(f['monitor_id'],f['field_id']):f for f in self.catalog(c)}
        for binding in plan['inputs']:
            field=known.get((binding['monitor_id'],binding['field_id']))
            if not field or field['signature']!=binding['signature']:raise ValueError('A calculation mapping changed. Preview again before activation.')
            binding['source_id']=field['source_id']
        old=c.execute(select(a.automations).where(a.automations.c.id==automation_id).with_for_update()).mappings().first() if automation_id else None
        if automation_id and not old:raise ValueError('Automation not found.')
        now=time.time();identity=automation_id or uid();revision_id=uid()
        number=c.execute(select(func.max(a.automation_revisions.c.number)).where(a.automation_revisions.c.automation_id==identity)).scalar() or 0
        record=dict(name=plan['name'],instructions=draft['instructions'],revision_id=revision_id,paused=False,updated_at=now,next_due=now)
        if old:
            c.execute(a.automations.update().where(a.automations.c.id==identity).values(**record))
            c.execute(a.automation_jobs.update().where(a.automation_jobs.c.automation_id==identity,a.automation_jobs.c.status.in_(['queued','running'])).values(status='cancelled',generation=a.automation_jobs.c.generation+1))
            c.execute(a.automation_deliveries.update().where(a.automation_deliveries.c.automation_id==identity,a.automation_deliveries.c.status.in_(['queued','running'])).values(status='disabled',generation=a.automation_deliveries.c.generation+1))
        else:c.execute(a.automations.insert().values(id=identity,created_at=now,**record))
        c.execute(a.automation_revisions.insert().values(id=revision_id,automation_id=identity,number=number+1,plan=plan,created_at=now))
        if plan['inputs']:c.execute(a.automation_dependencies.insert(),[dict(revision_id=revision_id,input_id=b['id'],monitor_id=b['monitor_id'],field_id=b['field_id'],source_id=b['source_id'],signature=b['signature']) for b in plan['inputs']])
        c.execute(a.automation_drafts.update().where(a.automation_drafts.c.id==draft['id']).values(activated_id=identity))
        enqueue(c,identity,revision_id,'activation:'+revision_id)
        _event(c,'automation_updated',identity,revision_id=revision_id)
        return identity

    def _records(self,rows):
        if not rows:return []
        revisions={r['id']:r for r in self.db.all(select(a.automation_revisions).where(a.automation_revisions.c.id.in_([r['revision_id'] for r in rows])))}
        states={r['automation_id']:r for r in self.db.all(select(a.automation_current).where(a.automation_current.c.automation_id.in_([r['id'] for r in rows])))}
        evaluation_ids={state[key] for state in states.values() for key in ('evaluation_id','valid_evaluation_id') if state[key]}
        # History is fetched only in the immutable evidence panel, never in every
        # dashboard card. The number of SQL statements is independent of cards.
        evaluations={r['id']:r for r in self.db.all(select(*(a.automation_evaluations.c[k] for k in ('id','automation_id','revision_id','at','status','error','inputs','outputs','conditions'))).where(a.automation_evaluations.c.id.in_(evaluation_ids)))} if evaluation_ids else {}
        source_ids={b['source_id'] for revision in revisions.values() for b in revision['plan']['inputs']}
        names={r['id']:r['name'] for r in self.db.all(select(sources.c.id,sources.c.name).where(sources.c.id.in_(source_ids)))} if source_ids else {}
        from .automation_evidence import _states,_current_eligible
        checked=[dict(evaluations[state['evaluation_id']],plan=revisions[row['revision_id']]['plan']) for row in rows if (state:=states.get(row['id'])) and state['evaluation_id'] in evaluations]
        dependency_states=_states(self.service,checked)
        result=[]
        for row in rows:
            revision=revisions[row['revision_id']];state=states.get(row['id'])
            current=copy.deepcopy(evaluations.get(state['evaluation_id'])) if state else None
            if current and current['revision_id']!=row['revision_id']:current=None
            if current and current['status']=='ok' and not _current_eligible(dict(current,plan=revision['plan']),dependency_states,time.time()):
                current.update(status='pending',last_valid_evaluation_id=current['id'],last_valid_at=current['at'],error='Waiting for valid, current source inputs and a calculation using their latest observations.')
            if current and current['status']!='ok' and state['valid_evaluation_id']:
                previous=evaluations.get(state['valid_evaluation_id'])
                if previous and previous['revision_id']==row['revision_id']:
                    current.update(outputs=previous['outputs'],last_valid_at=previous['at'],last_valid_evaluation_id=previous['id'])
            ids=sorted({b['source_id'] for b in revision['plan']['inputs']})
            result.append(dict(row,plan=revision['plan'],revision_number=revision['number'],current=current,source_ids=ids,source_names=[names[i] for i in ids if i in names]))
        return result

    def get(self,identity):
        row=self.db.one(select(a.automations).where(a.automations.c.id==identity))
        if not row:raise ValueError('Automation not found.')
        return self._records([row])[0]

    def listing(self,source_id=None,limit=50,cursor=None,archived=False):
        from .v2_api import paginate
        stmt=select(a.automations).where(a.automations.c.archived_at.is_not(None) if archived else a.automations.c.archived_at.is_(None))
        if source_id:stmt=stmt.where(a.automations.c.revision_id.in_(select(a.automation_dependencies.c.revision_id).where(a.automation_dependencies.c.source_id==source_id)))
        stmt=stmt.add_columns(a.automations.c.created_at.label('_cursor_at'),a.automations.c.id.label('_cursor_id'))
        page=paginate(self.db,stmt,a.automations.c.created_at,a.automations.c.id,limit,cursor)
        page['items']=self._records(page['items'])
        return page

    def patch(self,identity,payload):
        if payload.get('draft_id'):return self.activate(payload,identity)
        old=self.get(identity)
        if 'parameters' in payload:
            plan=copy.deepcopy(old['plan']);supplied=payload['parameters']
            if not isinstance(supplied,dict) or set(supplied)-{p['id'] for p in plan['parameters']}:raise ValueError('Unknown calculation parameter.')
            for p in plan['parameters']:
                if p['id'] in supplied:p['value']=supplied[p['id']]
            draft=self.preview({'instructions':old['instructions'],'plan':plan})
            return self.activate({'draft_id':draft['draft_id']},identity)
        if set(payload)!={'paused'} or type(payload['paused']) is not bool:raise ValueError('Supply paused, parameters, or a validated draft_id.')
        with self.db.tx() as c:
            c.execute(select(a.automations.c.id).where(a.automations.c.id==identity).with_for_update()).first()
            c.execute(a.automations.update().where(a.automations.c.id==identity).values(paused=payload['paused'],updated_at=time.time(),next_due=0))
            if payload['paused']:
                c.execute(a.automation_jobs.update().where(a.automation_jobs.c.automation_id==identity,a.automation_jobs.c.status.in_(['queued','running'])).values(status='cancelled',generation=a.automation_jobs.c.generation+1))
                c.execute(a.automation_deliveries.update().where(a.automation_deliveries.c.automation_id==identity,a.automation_deliveries.c.status.in_(['queued','running'])).values(status='disabled',generation=a.automation_deliveries.c.generation+1))
            else:enqueue(c,identity,old['revision_id'],'resume:'+uid())
            _event(c,'automation_updated',identity)
        return self.get(identity)

    def archive(self,identity):
        self.patch(identity,{'paused':True})
        with self.db.tx() as c:
            c.execute(a.automations.update().where(a.automations.c.id==identity).values(archived_at=time.time()))
            _event(c,'automation_updated',identity)
        return self.get(identity)

    def evidence(self,evaluation_id):
        row=self.db.one(select(a.automation_evaluations).where(a.automation_evaluations.c.id==evaluation_id))
        if not row:raise ValueError('Calculation evidence not found.')
        revision=self.db.one(select(a.automation_revisions).where(a.automation_revisions.c.id==row['revision_id']))
        return dict(row,plan=revision['plan'])

    def history(self,identity,limit=50,cursor=None):
        from .v2_api import paginate
        stmt=select(a.automation_evaluations).where(a.automation_evaluations.c.automation_id==identity).add_columns(a.automation_evaluations.c.at.label('_cursor_at'),a.automation_evaluations.c.id.label('_cursor_id'))
        return paginate(self.db,stmt,a.automation_evaluations.c.at,a.automation_evaluations.c.id,limit,cursor)

    def alerts(self,limit=50,cursor=None):
        from .v2_api import paginate
        stmt=select(a.automation_alerts).add_columns(a.automation_alerts.c.at.label('_cursor_at'),a.automation_alerts.c.id.label('_cursor_id'))
        return paginate(self.db,stmt,a.automation_alerts.c.at,a.automation_alerts.c.id,limit,cursor)

    def acknowledge(self,identity):
        with self.db.tx() as c:
            row=c.execute(select(a.automation_alerts).where(a.automation_alerts.c.id==identity).with_for_update()).mappings().first()
            if not row:raise ValueError('Alert not found.')
            if not row['acknowledged_at']:c.execute(a.automation_alerts.update().where(a.automation_alerts.c.id==identity).values(acknowledged_at=time.time()))
            _event(c,'alert_updated',row['automation_id'],alert_id=identity)
        return self.db.one(select(a.automation_alerts).where(a.automation_alerts.c.id==identity))

    def scheduler_once(self):
        now=time.time()
        rows=self.db.all(select(a.automations).where(a.automations.c.paused.is_(False),a.automations.c.archived_at.is_(None),a.automations.c.next_due<=now).order_by(a.automations.c.next_due).limit(100))
        with self.db.tx() as c:
            for row in rows:
                # Deduplicate clock ticks across schedulers and process interruption.
                enqueue(c,row['id'],row['revision_id'],'clock:'+str(int(now)))
                c.execute(a.automations.update().where(a.automations.c.id==row['id'],a.automations.c.revision_id==row['revision_id']).values(next_due=now+60))
        return len(rows)

    def claim(self):
        now=time.time()
        with self.db.tx() as c:
            stmt=select(a.automation_jobs).where(a.automation_jobs.c.available_at<=now,or_(a.automation_jobs.c.status=='queued',and_(a.automation_jobs.c.status=='running',a.automation_jobs.c.lease_until<now)))
            for candidate in c.execute(stmt.order_by(a.automation_jobs.c.created_at).limit(20)).mappings().all():
                auto=c.execute(select(a.automations).where(a.automations.c.id==candidate['automation_id']).with_for_update(skip_locked=True)).mappings().first()
                if not auto:continue
                row=c.execute(stmt.where(a.automation_jobs.c.id==candidate['id']).with_for_update(skip_locked=True)).mappings().first()
                if not row:continue
                if not auto or auto['paused'] or auto['archived_at'] or auto['revision_id']!=row['revision_id']:
                    c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==row['id']).values(status='cancelled'));continue
                claim=dict(row,owner=self.owner,generation=row['generation']+1,lease_until=now+60,attempts=row['attempts']+1)
                c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==row['id']).values(**{k:claim[k] for k in ('owner','generation','lease_until','attempts')},status='running'))
                return claim
        return None

    def renew(self,claim):
        with self.db.tx() as c:
            row=c.execute(select(a.automation_jobs).where(a.automation_jobs.c.id==claim['id']).with_for_update()).mappings().one()
            self._assert_claim(row,claim)
            c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==claim['id']).values(lease_until=time.time()+60))

    def _assert_claim(self,row,claim):
        if row['status']!='running' or row['owner']!=claim['owner'] or row['generation']!=claim['generation'] or row['lease_until']<time.time():raise ValueError('STALE_WORKER')

    def _keep_claim(self,c,claim):
        row=c.execute(select(a.automation_jobs).where(a.automation_jobs.c.id==claim['id'])).mappings().one()
        self._assert_claim(row,claim)
        if row['lease_until']<time.time()+30:
            c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==claim['id']).values(lease_until=time.time()+60))

    def once(self):
        claim=self.claim()
        if not claim:return None
        try:return self.evaluate(claim)
        except Exception as exc:
            with self.db.tx() as c:
                row=c.execute(select(a.automation_jobs).where(a.automation_jobs.c.id==claim['id']).with_for_update()).mappings().one()
                if row['generation']==claim['generation'] and row['owner']==claim['owner'] and row['status']=='running':
                    c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==claim['id']).values(status='failed' if claim['attempts']>=5 else 'queued',available_at=time.time()+min(60,2**claim['attempts']),error='Evaluation could not complete; retry pending.' if claim['attempts']<5 else 'Evaluation failed after five attempts.',owner=None,lease_until=0))
            raise exc

    def _history(self,c,binding,mode,seconds,at):
        revisions=c.execute(select(m.monitor_revisions.c.id,m.monitor_revisions.c.fields).where(m.monitor_revisions.c.monitor_id==binding['monitor_id'])).mappings().all()
        eligible=[r['id'] for r in revisions if any(f['id']==binding['field_id'] and definition_signature(f)==binding['signature'] for f in r['fields'])]
        state=c.execute(select(m.monitor_field_states).join(m.monitors,m.monitors.c.revision_id==m.monitor_field_states.c.revision_id).where(m.monitor_field_states.c.monitor_id==binding['monitor_id'],m.monitor_field_states.c.field_id==binding['field_id'])).mappings().first()
        stmt=select(m.monitor_observations).where(m.monitor_observations.c.monitor_id==binding['monitor_id'],m.monitor_observations.c.field_id==binding['field_id'],m.monitor_observations.c.revision_id.in_(eligible),m.monitor_observations.c.at<=at)
        if state:stmt=stmt.where(m.monitor_observations.c.period==state['period'],m.monitor_observations.c.unit==state['unit'])
        if mode=='baseline':stmt=stmt.where(m.monitor_observations.c.status=='ok').order_by(m.monitor_observations.c.at,m.monitor_observations.c.id).limit(1)
        elif mode=='previous':stmt=stmt.where(m.monitor_observations.c.status=='ok').order_by(m.monitor_observations.c.at.desc(),m.monitor_observations.c.id.desc()).limit(2)
        else:stmt=stmt.where(m.monitor_observations.c.at>=at-(seconds or 604800)).order_by(m.monitor_observations.c.at,m.monitor_observations.c.id).limit(10001)
        rows=[dict(r) for r in c.execute(stmt).mappings()]
        if len(rows)>10000:raise ValueError('History exceeds 10,000 observations. Choose a smaller time window.')
        for r in rows:
            r['definition_signature']=binding['signature']
            if binding.get('unit'):r['unit']=binding['unit']
        return rows

    def evaluate(self,claim):
        from .automation_expr import evaluate_plan
        revision=self.db.one(select(a.automation_revisions).where(a.automation_revisions.c.id==claim['revision_id']))
        plan=revision['plan'];now=time.time()
        with self.db.tx() as c:
            self._lock_sources(c,plan)
            auto=c.execute(select(a.automations).where(a.automations.c.id==claim['automation_id']).with_for_update()).mappings().one()
            job=c.execute(select(a.automation_jobs).where(a.automation_jobs.c.id==claim['id']).with_for_update()).mappings().one()
            self._assert_claim(job,claim)
            if auto['revision_id']!=revision['id'] or auto['paused'] or auto['archived_at']:raise ValueError('STALE_WORKER')
            inputs=[];values={};errors=[];expiry=[now+plan.get('interval',60)];history_evidence={}
            for binding in plan['inputs']:
                self._keep_claim(c,claim)
                mon=c.execute(select(m.monitors).where(m.monitors.c.id==binding['monitor_id'])).mappings().first()
                source=c.execute(select(sources).where(sources.c.id==binding['source_id'])).mappings().first()
                rev=c.execute(select(m.monitor_revisions).where(m.monitor_revisions.c.id==mon['revision_id'])).mappings().first() if mon else None
                definition=next((f for f in rev['fields'] if f['id']==binding['field_id']),None) if rev else None
                state=c.execute(select(m.monitor_field_states).where(m.monitor_field_states.c.revision_id==rev['id'],m.monitor_field_states.c.field_id==binding['field_id'])).mappings().first() if rev else None
                reason=None
                if not definition or definition_signature(definition)!=binding['signature']:reason='Extraction mapping changed; repair the calculation.'
                elif not source or source['removed_at'] or not source['enabled'] or source['paused'] or mon['paused']:reason='Source monitoring is paused, removed or disabled.'
                elif not state or state['status']!='ok':reason='The latest extraction attempt is not valid.'
                elif state['unit']!=binding.get('source_unit',state['unit']):reason='The source unit changed; review the calculation mapping.'
                elif not state['last_verified_at'] or now-state['last_verified_at']>source['config']['interval']:reason='The input is overdue for verification.'
                snapshot={**binding,'value':state['value'] if state else None,'unit':binding.get('unit') or (state['unit'] if state else ''),'period':state['period'] if state else '',
                    'revision_id':rev['id'] if rev else None,'definition_signature':binding['signature'],
                    'at':state['last_verified_at'] if state else None,'capture_id':state['capture_id'] if state else None,'observation_id':state['observation_id'] if state else None,
                    'locator':state['locator'] if state else None,'status':'blocked' if reason else 'ok','error':reason,'source_name':source['name'] if source else ''}
                inputs.append(snapshot);values[binding['id']]=snapshot
                if reason:errors.append(binding['name']+': '+reason)
                else:expiry.append(state['last_verified_at']+source['config']['interval']+.01)
            periods={i['period'] for i in inputs if i.get('period')}
            if len(periods)>1 and not plan.get('allow_cross_period'):errors.append('Reporting periods or sessions do not match.')
            def history(input_id,mode,seconds=None):
                self._keep_claim(c,claim)
                key=f'{input_id}:{mode}:{seconds}'
                if key in history_evidence:return history_evidence[key]
                binding=next(b for b in plan['inputs'] if b['id']==input_id)
                rows=self._history(c,binding,mode,seconds,now)
                if len(rows)+sum(len(r) for r in history_evidence.values())>50000:raise ValueError('The calculation exceeds 50,000 historical samples. Use a smaller window or fewer inputs.')
                history_evidence[key]=rows
                return rows
            result={'outputs':[],'conditions':{}}
            if not errors:
                try:result=evaluate_plan(plan,values,history=history)
                except (ValueError,LookupError,ArithmeticError) as exc:errors.append(str(exc))
            evaluation_id=fingerprint(['evaluation',job['id']])[:32]
            record=dict(id=evaluation_id,automation_id=auto['id'],revision_id=revision['id'],job_id=job['id'],at=now,
                status='blocked' if errors else 'ok',error='; '.join(errors)[:2000] or None,inputs=inputs,outputs=result['outputs'],conditions=result['conditions'],history=history_evidence)
            c.execute(a.automation_evaluations.insert().values(**record))
            outputs={o['id']:o for o in record['outputs']}
            for definition in plan['outputs']:
                output=outputs.get(definition['id'],{})
                try:
                    number=float(output['value']) if type(output.get('value')) is not bool else None
                    if number is not None and not math.isfinite(number):number=None
                except (KeyError,ValueError,TypeError):number=None
                c.execute(a.automation_values.insert().values(evaluation_id=evaluation_id,field_id=definition['id'],automation_id=auto['id'],revision_id=revision['id'],at=now,status=record['status'],error=record['error'],value=output.get('value'),number=number,unit=output.get('unit'),period=' | '.join(sorted(periods))))
            previous=c.execute(select(a.automation_current).where(a.automation_current.c.automation_id==auto['id'])).mappings().first()
            if previous and previous['valid_evaluation_id'] and not errors:
                previous_evaluation=c.execute(select(a.automation_evaluations.c.inputs).where(a.automation_evaluations.c.id==previous['valid_evaluation_id'])).scalar()
                old_inputs={i['id']:i for i in previous_evaluation or []}
                for i in inputs:
                    before=old_inputs.get(i['id'])
                    if before and i['at'] and before.get('at') and i['at']-before['at']>next(s['config']['interval'] for s in c.execute(select(sources).where(sources.c.id==i['source_id'])).mappings()):
                        c.execute(a.automation_rule_states.update().where(a.automation_rule_states.c.revision_id==revision['id']).values(true_since=None))
                        break
            current=dict(evaluation_id=evaluation_id,status=record['status'],error=record['error'],at=now)
            if not errors:current['valid_evaluation_id']=evaluation_id
            if previous:c.execute(a.automation_current.update().where(a.automation_current.c.automation_id==auto['id']).values(**current))
            else:c.execute(a.automation_current.insert().values(automation_id=auto['id'],**current))
            self._rules(c,auto,revision,record,expiry)
            c.execute(a.automations.update().where(a.automations.c.id==auto['id']).values(next_due=max(now+1,min(expiry))))
            self._keep_claim(c,claim)
            c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id==job['id']).values(status='succeeded',finished_at=now,owner=None,lease_until=0))
            _event(c,'automation_updated',auto['id'],revision_id=revision['id'],evaluation_id=evaluation_id)
        return record

    def _rules(self,c,auto,revision,evaluation,expiry):
        now=evaluation['at']
        for rule in revision['plan']['rules']:
            key=and_(a.automation_rule_states.c.revision_id==revision['id'],a.automation_rule_states.c.rule_id==rule['id'])
            previous=c.execute(select(a.automation_rule_states).where(key).with_for_update()).mappings().first()
            state=dict(previous) if previous else dict(revision_id=revision['id'],rule_id=rule['id'],last_condition=None,true_since=None,notified=False,last_notified_at=None,episode=0,alert_id=None)
            valid=evaluation['status']=='ok'
            if not valid:state['true_since']=None
            else:
                condition=bool(evaluation['conditions'][rule['id']])
                if condition:
                    if state['true_since'] is None:state['true_since']=now
                    due=state['true_since']+rule.get('sustain_seconds',0)
                    cooldown=(state['last_notified_at'] or 0)+rule.get('cooldown_seconds',900)
                    if not state['notified'] and now>=due and now>=cooldown:
                        state['episode']+=1
                        state['alert_id']=self._alert(c,auto,revision,evaluation,rule,'triggered',state['episode'])
                        state.update(notified=True,last_notified_at=now)
                    elif not state['notified']:expiry.append(max(due,cooldown))
                else:
                    if state['alert_id'] and state['last_condition']:
                        c.execute(a.automation_alerts.update().where(a.automation_alerts.c.id==state['alert_id']).values(status='resolved',resolved_at=now))
                        if rule.get('notify_recovery'):self._alert(c,auto,revision,evaluation,rule,'recovered',state['episode'])
                    state.update(true_since=None,notified=False,alert_id=None)
                state['last_condition']=condition
            if previous:c.execute(a.automation_rule_states.update().where(key).values(**state))
            else:c.execute(a.automation_rule_states.insert().values(**state))

    def _alert(self,c,auto,revision,evaluation,rule,kind,episode):
        alert_id=fingerprint([revision['id'],rule['id'],episode,kind])[:32]
        now=evaluation['at']
        c.execute(a.automation_alerts.insert().values(id=alert_id,automation_id=auto['id'],revision_id=revision['id'],rule_id=rule['id'],evaluation_id=evaluation['id'],name=rule['name'],kind=kind,status='open' if kind=='triggered' else 'resolved',at=now))
        payload=dict(event=kind,alert_id=alert_id,automation_id=auto['id'],name=rule['name'],revision_id=revision['id'],evaluation_id=evaluation['id'],at=now,
            outputs=evaluation['outputs'],inputs=[{k:i.get(k) for k in ('name','value','unit','period','at','observation_id','capture_id')} for i in evaluation['inputs']])
        if len(json.dumps(payload).encode())>65536:payload['inputs']=[{k:i.get(k) for k in ('name','unit','at','observation_id','capture_id')} for i in evaluation['inputs']]
        for connection_id in dict.fromkeys(rule.get('connections',[])):
            c.execute(a.automation_deliveries.insert().values(id=fingerprint([alert_id,connection_id])[:32],alert_id=alert_id,automation_id=auto['id'],revision_id=revision['id'],connection_id=connection_id,payload=payload,status='queued',attempts=0,generation=0,lease_until=0,available_at=0,created_at=now))
        _event(c,'alert_created',auto['id'],alert_id=alert_id)
        return alert_id


def _nodes(value):
    if isinstance(value,dict):
        if 'op' in value:yield value
        for child in value.values():yield from _nodes(child)
    elif isinstance(value,list):
        for child in value:yield from _nodes(child)
