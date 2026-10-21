import copy
import time
import pytest
from sqlalchemy import select,event
from parity import automation_schema as a,monitor_schema as m
from parity.automation import Automations,definition_signature,enqueue
from parity.automation_evidence import retrieve
from parity.db import sources
from tests.test_monitoring import monitor,setup_monitor


def create_calculation(monitor):
    monitoring,activated,fields=setup_monitor(monitor,names=('Current Price',))
    service=monitoring.service;automations=Automations(service)
    field=activated['monitor']['fields'][0]
    plan={'version':1,'name':'Material cost','inputs':[{'id':'price','name':'Current Price','monitor_id':activated['monitor']['id'],
        'field_id':field['id'],'signature':definition_signature(field),'unit':'INR'}],
        'parameters':[{'id':'quantity','name':'Required quantity','value':'2','unit':''}],
        'outputs':[{'id':'total','name':'Estimated material cost','expression':{'op':'multiply','args':[{'op':'input','id':'price'},{'op':'parameter','id':'quantity'}]}}],
        'rules':[]}
    draft=automations.preview({'instructions':'Calculate material cost','plan':plan,'use_ai':False})
    auto=automations.activate({'draft_id':draft['draft_id']})
    evaluated=automations.once()
    return service,automations,auto,evaluated,activated


def test_calculation_evidence_cites_exact_inputs_parameters_and_formula(monitor):
    service,automations,auto,evaluation,activated=create_calculation(monitor)
    calls=[]
    def count(*args):calls.append(1)
    event.listen(service.db.engine,'before_cursor_execute',count)
    try:evidence=retrieve(service,'What is my material cost?')
    finally:event.remove(service.db.engine,'before_cursor_execute',count)
    assert len(calls)==2 and len(evidence)==1
    item=evidence[0]
    assert item['evidence_type']=='calculation' and item['evaluation_id']==evaluation['id']
    assert item['value']=='2401' and item['unit']=='INR'
    assert 'Required quantity: 2' in item['text'] and 'Formula revision 1' in item['text']
    assert 'Current Price × Required quantity' in item['text']
    assert item['supporting_captures'][0]['capture_id']==evaluation['inputs'][0]['capture_id']
    assert item['supporting_captures'][0]['id']==evaluation['inputs'][0]['observation_id']
    assert item['url']=='/api/calculations/'+evaluation['id']
    assert automations.evidence(item['evaluation_id'])['outputs'][0]['value']=='2401'
    assert retrieve(service,'material cost',source_ids=[activated['source']['id']])
    assert not retrieve(service,'material cost',source_ids=['different-source'])
    assert not retrieve(service,'material cost',source_ids=[])
    assert not retrieve(service,'an unrelated unique topic')


@pytest.mark.parametrize('change',['overdue','failed','paused_source','removed','disabled','paused_monitor','new_observation','changed_signature','changed_unit','paused_automation','archived_automation'])
def test_current_calculation_never_falls_back_to_retained_or_pending_inputs(monitor,change):
    service,automations,auto,evaluation,activated=create_calculation(monitor)
    state=service.db.one(select(m.monitor_field_states).where(m.monitor_field_states.c.monitor_id==activated['monitor']['id']))
    with service.db.tx() as connection:
        if change=='overdue':connection.execute(m.monitor_field_states.update().where(m.monitor_field_states.c.observation_id==state['observation_id']).values(last_verified_at=time.time()-100000))
        elif change=='failed':connection.execute(m.monitor_field_states.update().where(m.monitor_field_states.c.observation_id==state['observation_id']).values(status='missing'))
        elif change=='paused_source':connection.execute(sources.update().where(sources.c.id==activated['source']['id']).values(paused=True))
        elif change=='removed':connection.execute(sources.update().where(sources.c.id==activated['source']['id']).values(removed_at=time.time()))
        elif change=='disabled':connection.execute(sources.update().where(sources.c.id==activated['source']['id']).values(enabled=False))
        elif change=='paused_monitor':connection.execute(m.monitors.update().where(m.monitors.c.id==activated['monitor']['id']).values(paused=True))
        elif change=='new_observation':connection.execute(m.monitor_field_states.update().where(m.monitor_field_states.c.observation_id==state['observation_id']).values(observation_id='new-input-awaits-calculation'))
        elif change=='changed_unit':connection.execute(m.monitor_field_states.update().where(m.monitor_field_states.c.observation_id==state['observation_id']).values(unit='USD'))
        elif change=='changed_signature':
            revision=service.db.one(select(m.monitor_revisions).where(m.monitor_revisions.c.id==state['revision_id']))
            fields=copy.deepcopy(revision['fields']);fields[0]['rule']['selector']='.other'
            connection.execute(m.monitor_revisions.update().where(m.monitor_revisions.c.id==state['revision_id']).values(fields=fields))
        elif change=='paused_automation':connection.execute(a.automations.update().where(a.automations.c.id==auto['id']).values(paused=True))
        elif change=='archived_automation':connection.execute(a.automations.update().where(a.automations.c.id==auto['id']).values(archived_at=time.time()))
    assert not retrieve(service,'material cost')
    # Current dependency failures cannot erase already published immutable evidence.
    historical=retrieve(service,'material cost',mode='as_of',as_of=evaluation['at']+.000001)
    assert historical and historical[0]['evaluation_id']==evaluation['id']
    assert automations.evidence(evaluation['id'])['outputs'][0]['value']=='2401'


def test_latest_failed_historical_evaluation_blocks_old_valid_fallback(monitor):
    service,automations,auto,baseline,activated=create_calculation(monitor)
    with service.db.tx() as connection:
        connection.execute(m.monitor_field_states.update().where(m.monitor_field_states.c.monitor_id==activated['monitor']['id']).values(status='missing'))
        enqueue(connection,auto['id'],auto['revision_id'],'failed-input')
    blocked=automations.once();assert blocked['status']=='blocked'
    assert not retrieve(service,'material cost')
    assert not retrieve(service,'material cost',mode='as_of',as_of=blocked['at']+.00001)
    assert retrieve(service,'material cost',mode='as_of',as_of=baseline['at']+.000001)[0]['evaluation_id']==baseline['id']


def test_new_revision_pending_evaluation_excludes_old_revision(monitor):
    service,automations,auto,evaluation,activated=create_calculation(monitor)
    changed=copy.deepcopy(auto['plan']);changed['parameters'][0]['value']='3'
    draft=automations.preview({'instructions':'Calculate material cost for quantity3','plan':changed,'use_ai':False})
    revised=automations.activate({'draft_id':draft['draft_id']},automation_id=auto['id'])
    assert revised['revision_id']!=auto['revision_id']
    assert not retrieve(service,'material cost')
    assert not retrieve(service,'material cost',mode='as_of',as_of=time.time())
    assert retrieve(service,'material cost',mode='as_of',as_of=evaluation['at']+.000001)
    newer=automations.once()
    assert retrieve(service,'material cost')[0]['value']=='3601.5'
    assert retrieve(service,'material cost',mode='as_of',as_of=newer['at']+.000001)[0]['number']==2


def test_test_sources_are_excluded_from_default_retrieval(monitor):
    service,automations,auto,evaluation,activated=create_calculation(monitor)
    with service.db.tx() as connection:
        config=dict(activated['source']['config'],source_kind='test')
        connection.execute(sources.update().where(sources.c.id==activated['source']['id']).values(config=config))
    assert not retrieve(service,'material cost')
    assert retrieve(service,'material cost',source_ids=[activated['source']['id']])
