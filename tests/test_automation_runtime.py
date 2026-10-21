"""Calculations consume real immutable fixture captures, with no AI or embeddings."""
import copy
import time

import pytest
from sqlalchemy import func, select

from parity import automation as runtime, automation_schema as a, monitor_schema as ms
from parity.automation import Automations, definition_signature
from parity.db import sources, uid
from parity.fetch import Response
from tests.test_monitoring import monitor, setup_monitor, HTML, URL


def input_for(activated, field, identity='price'):
    return {'id': identity, 'name': field['name'], 'monitor_id': activated['monitor']['id'],
            'field_id': field['id'], 'signature': definition_signature(field),
            'unit': 'INR' if field['type'] == 'currency' else '%' if field['type'] == 'percentage' else ''}


def cost_plan(activated, *, threshold='2000', sustain=0, recovery=False):
    field = next(f for f in activated['monitor']['fields'] if f['name'] == 'Current Price')
    return {'version': 1, 'name': 'Material budget', 'inputs': [input_for(activated, field)],
            'parameters': [{'id': 'quantity', 'name': 'Quantity', 'value': '2', 'unit': ''},
                           {'id': 'budget', 'name': 'Budget', 'value': threshold, 'unit': 'INR'}],
            'outputs': [{'id': 'cost', 'name': 'Estimated cost', 'display': 'budget',
                         'expression': {'op': 'multiply', 'args': [{'op': 'input', 'id': 'price'},
                                                                 {'op': 'parameter', 'id': 'quantity'}]}}],
            'rules': [{'id': 'over_budget', 'name': 'Over budget', 'condition': {'op': 'gt', 'args': [
                {'op': 'output', 'id': 'cost'}, {'op': 'parameter', 'id': 'budget'}]},
                       'sustain_seconds': sustain, 'cooldown_seconds': 0, 'notify_recovery': recovery}]}


def activate(m, plan):
    worker = Automations(m.service)
    preview = worker.preview({'instructions': 'Calculate material cost and compare with budget', 'plan': plan, 'use_ai': False})
    assert preview['status'] == 'ready', preview
    result = worker.activate({'draft_id': preview['draft_id']})
    return worker, result, preview


def drain(worker):
    results = []
    for _ in range(30):
        result = worker.once()
        if result is None:
            return results
        results.append(result)
    pytest.fail('Automation queue did not drain within bounded fixture workload')


def queue(worker, identity, reason=None):
    auto = worker.get(identity)
    with worker.db.tx() as c:
        runtime.enqueue(c, identity, auto['revision_id'], reason or uid())


def capture(m, activated, run, price='1250'):
    return m.process_capture(activated['source'], run, Response(URL, 200, {'content-type': 'text/html'},
        HTML.replace('Rs. 1,200.50', 'Rs. ' + price).encode()))


def alerts(worker, identity):
    return worker.db.all(select(a.automation_alerts).where(a.automation_alerts.c.automation_id == identity)
                         .order_by(a.automation_alerts.c.at, a.automation_alerts.c.id))


def test_activation_idempotence_actual_values_evidence_and_duplicate_publication(monitor):
    m, activated, _ = setup_monitor(monitor)
    worker, auto, preview = activate(m, cost_plan(activated))
    repeated = worker.activate({'draft_id': preview['draft_id']})
    assert repeated['id'] == auto['id']
    assert len(drain(worker)) == 1
    current = worker.get(auto['id'])['current']
    assert current['outputs'][0]['value'] == '2401'
    assert current['outputs'][0]['unit'] == 'INR'
    assert len(alerts(worker, auto['id'])) == 1
    evidence = worker.evidence(current['id'])
    original_capture = evidence['inputs'][0]['capture_id']
    assert evidence['inputs'][0]['observation_id']
    assert '1,200.50' in m.evidence(original_capture)['text']
    capture(m, activated, 'first', '1300')
    assert len(drain(worker)) == 1
    assert worker.get(auto['id'])['current']['outputs'][0]['value'] == '2600'
    assert capture(m, activated, 'first', '1300')['observations'] == 0
    assert drain(worker) == []
    assert len(alerts(worker, auto['id'])) == 1
    assert worker.history(auto['id'])['total'] == 2
    assert '1,200.50' in m.evidence(original_capture)['text']


def test_failed_missing_overdue_and_recovery_preserve_last_valid_value(monitor):
    m, activated, _ = setup_monitor(monitor)
    worker, auto, _ = activate(m, cost_plan(activated, threshold='999999'))
    drain(worker)
    baseline = worker.get(auto['id'])['current']
    m.process_error(activated['source'], 'network-failure', URL, 'HTTP 503', 503)
    assert drain(worker)[-1]['status'] == 'blocked'
    current = worker.get(auto['id'])['current']
    assert current['outputs'][0]['value'] == '2401'
    assert current['last_valid_evaluation_id'] == baseline['id']
    assert not alerts(worker, auto['id'])
    broken = HTML.replace('class="value"', 'class="missing"')
    m.process_capture(activated['source'], 'missing-field', Response(URL, 200, {}, broken.encode()))
    assert drain(worker)[-1]['status'] == 'blocked'
    capture(m, activated, 'recovery', '0')
    recovered = drain(worker)[-1]
    assert recovered['status'] == 'ok'
    assert recovered['outputs'][0]['value'] == '0'
    with worker.db.tx() as c:
        c.execute(ms.monitor_field_states.update().where(ms.monitor_field_states.c.monitor_id == activated['monitor']['id'])
                  .values(last_verified_at=time.time() - 10000))
    queue(worker, auto['id'])
    assert drain(worker)[-1]['status'] == 'blocked'
    assert worker.get(auto['id'])['current']['outputs'][0]['value'] == '0'


def test_removed_and_restored_sources_block_claimed_calculation_until_explicit_resume(monitor):
    m, activated, _ = setup_monitor(monitor)
    worker, auto, _ = activate(m, cost_plan(activated))
    claim = worker.claim()
    m.service.remove_source(activated['source']['id'])
    result = worker.evaluate(claim)
    assert result['status'] == 'blocked'
    assert not alerts(worker, auto['id'])
    original_capture = result['inputs'][0]['capture_id']
    assert m.evidence(original_capture)['text']
    m.service.remove_source(activated['source']['id'], restore=True)
    assert drain(worker)[-1]['status'] == 'blocked'
    m.service.set_source(activated['source']['id'], paused=False)
    assert drain(worker)[-1]['status'] == 'ok'
    assert worker.get(auto['id'])['id'] == auto['id']
    assert m.evidence(original_capture)['text']


def test_worker_interruption_lease_recovery_and_duplicate_evaluation_fence(monitor):
    m, activated, _ = setup_monitor(monitor)
    first, auto, _ = activate(m, cost_plan(activated))
    abandoned = first.claim()
    with first.db.tx() as c:
        c.execute(a.automation_jobs.update().where(a.automation_jobs.c.id == abandoned['id']).values(lease_until=0))
    second = Automations(m.service)
    recovered = second.claim()
    assert recovered['generation'] == abandoned['generation'] + 1
    with pytest.raises(ValueError, match='STALE_WORKER'):
        first.evaluate(abandoned)
    second.renew(recovered)
    assert second.evaluate(recovered)['status'] == 'ok'
    with pytest.raises(ValueError, match='STALE_WORKER'):
        second.evaluate(recovered)
    assert second.history(auto['id'])['total'] == 1
    assert len(alerts(second, auto['id'])) == 1


def test_automation_revision_fences_old_work_and_keeps_old_calculation_evidence(monitor):
    m, activated, _ = setup_monitor(monitor)
    worker, auto, _ = activate(m, cost_plan(activated))
    drain(worker)
    old = worker.get(auto['id'])['current']
    queue(worker, auto['id'])
    claimed = worker.claim()
    revised = worker.patch(auto['id'], {'parameters': {'quantity': '3'}})
    assert revised['revision_number'] == 2
    with pytest.raises(ValueError, match='STALE_WORKER'):
        worker.evaluate(claimed)
    drain(worker)
    assert worker.get(auto['id'])['current']['outputs'][0]['value'] == '3601.5'
    assert worker.evidence(old['id'])['outputs'][0]['value'] == '2401'
    assert worker.evidence(old['id'])['plan']['parameters'][0]['value'] == '2'


def test_extraction_rename_compatible_but_changed_mapping_requires_repair(monitor):
    m, activated, initial = setup_monitor(monitor)
    worker, auto, _ = activate(m, cost_plan(activated))
    drain(worker)
    draft = m.preview({'source_id': activated['source']['id'], 'instructions': 'Current price', 'use_ai': False})
    rename = copy.deepcopy(initial[0])
    rename['name'] = 'Renamed price'
    m.revise(activated['monitor']['id'], {'draft_id': draft['draft_id'], 'fields': [rename]})
    assert drain(worker)[-1]['status'] == 'ok'
    draft = m.preview({'source_id': activated['source']['id'], 'instructions': 'Current price', 'use_ai': False})
    changed = copy.deepcopy(m.monitor(activated['monitor']['id'])['fields'][0])
    changed['rule']['selector'] = 'ul#metrics > li'
    m.revise(activated['monitor']['id'], {'draft_id': draft['draft_id'], 'fields': [changed]})
    result = drain(worker)[-1]
    assert result['status'] == 'blocked'
    assert 'mapping changed' in result['error']


def test_reporting_period_mismatch_requires_explicit_cross_period_choice(monitor):
    m, activated, _ = setup_monitor(monitor)
    plan = cost_plan(activated)
    holding = next(f for f in activated['monitor']['fields'] if f['name'] == 'Promoter holding')
    plan['inputs'].append(input_for(activated, holding, 'holding'))
    worker, auto, _ = activate(m, plan)
    drain(worker)
    fields = activated['monitor']['fields']
    with worker.db.tx() as c:
        for field in fields:
            c.execute(ms.monitor_field_states.update().where(ms.monitor_field_states.c.monitor_id == activated['monitor']['id'],
                ms.monitor_field_states.c.field_id == field['id']).values(period='2026-10-20 AM' if field['name'] == 'Current Price' else '2026-10-20 PM'))
    queue(worker, auto['id'])
    assert drain(worker)[-1]['status'] == 'blocked'
    preview = worker.preview({'plan': plan, 'use_ai': False})
    assert preview['status'] == 'needs_input'
    plan['allow_cross_period'] = True
    preview = worker.preview({'plan': plan, 'use_ai': False})
    assert preview['status'] == 'ready'
    worker.activate({'draft_id': preview['draft_id']}, auto['id'])
    assert drain(worker)[-1]['status'] == 'ok'


def test_cross_source_calculation_tracks_each_capture_and_blocks_missing_dependency(monitor):
    m, activated, _ = setup_monitor(monitor)
    second_url = 'https://second.fixture.example/company/'
    draft = m.preview({'name': 'Supplier B', 'root_url': second_url, 'instructions': 'Current price', 'use_ai': False})
    selected = [f for f in draft['candidates'] if f['name'] == 'Current Price']
    other = m.activate({'draft_id': draft['draft_id'], 'fields': selected})
    plan = cost_plan(activated)
    plan['inputs'].append(input_for(other, other['monitor']['fields'][0], 'other'))
    plan['outputs'] = [{'id': 'combined', 'name': 'Combined cost', 'expression': {'op': 'sum', 'args': [
        {'op': 'input', 'id': 'price'}, {'op': 'input', 'id': 'other'}]}}]
    plan['rules'] = []
    worker, auto, _ = activate(m, plan)
    result = drain(worker)[-1]
    assert result['status'] == 'ok' and result['outputs'][0]['value'] == '2401'
    assert len(set(i['capture_id'] for i in result['inputs'])) == 2
    assert len(worker.get(auto['id'])['source_ids']) == 2
    m.service.set_source(other['source']['id'], paused=True)
    assert drain(worker)[-1]['status'] == 'blocked'


def test_rules_initial_trigger_recovery_unknown_gap_and_acknowledgement(monitor):
    m, activated, _ = setup_monitor(monitor)
    worker, auto, _ = activate(m, cost_plan(activated, recovery=True))
    drain(worker)
    triggered = alerts(worker, auto['id'])[0]
    first_ack = worker.acknowledge(triggered['id'])['acknowledged_at']
    assert worker.acknowledge(triggered['id'])['acknowledged_at'] == first_ack
    m.process_error(activated['source'], 'unknown', URL, 'HTTP 503', 503)
    drain(worker)
    capture(m, activated, 'still-true', '1300')
    drain(worker)
    assert len(alerts(worker, auto['id'])) == 1
    capture(m, activated, 'below-budget', '900')
    drain(worker)
    assert {item['kind'] for item in alerts(worker, auto['id'])} == {'triggered', 'recovered'}
    assert next(item for item in alerts(worker, auto['id']) if item['id'] == triggered['id'])['status'] == 'resolved'
    capture(m, activated, 'above-again', '1300')
    drain(worker)
    assert len([item for item in alerts(worker, auto['id']) if item['kind'] == 'triggered']) == 2


def test_sustained_condition_resets_after_observed_failure(monitor, monkeypatch):
    m, activated, _ = setup_monitor(monitor)
    clock = [time.time()]
    monkeypatch.setattr(runtime.time, 'time', lambda: clock[0])
    worker, auto, _ = activate(m, cost_plan(activated, sustain=60))
    drain(worker)
    assert not alerts(worker, auto['id'])
    clock[0] += 30
    m.process_error(activated['source'], 'temporary-gap', URL, 'HTTP 503', 503)
    drain(worker)
    clock[0] += 40
    capture(m, activated, 'back', '1300')
    drain(worker)
    assert not alerts(worker, auto['id'])
    clock[0] += 61
    queue(worker, auto['id'])
    drain(worker)
    assert len(alerts(worker, auto['id'])) == 1


def test_sustained_condition_resets_after_unobserved_restart_gap(monitor, monkeypatch):
    m, activated, _ = setup_monitor(monitor)
    clock = [time.time()]
    monkeypatch.setattr(runtime.time, 'time', lambda: clock[0])
    worker, auto, _ = activate(m, cost_plan(activated, sustain=1200))
    drain(worker)
    # Services are stopped while the input crosses its 900-second freshness
    # deadline. On restart, capture succeeds before the automation worker runs.
    clock[0] += 1300
    capture(m, activated, 'first-after-restart', '1300')
    drain(worker)
    assert not alerts(worker, auto['id'])
    state = worker.db.one(select(a.automation_rule_states).where(a.automation_rule_states.c.revision_id == auto['revision_id']))
    assert state['true_since'] == clock[0]


def test_previous_comparable_value_survives_multiple_failed_checks(monitor):
    m, activated, _ = setup_monitor(monitor)
    plan = cost_plan(activated)
    plan['outputs'] = [{'id': 'growth', 'name': 'Price movement', 'expression': {'op': 'percent_change', 'args': [
        {'op': 'input', 'id': 'price'}, {'op': 'previous', 'id': 'price'}]}}]
    plan['rules'] = []
    worker, auto, _ = activate(m, plan)
    assert drain(worker)[-1]['status'] == 'blocked'  # A baseline has no earlier sample.
    for index in range(4):
        m.process_error(activated['source'], 'failure-' + str(index), URL, 'HTTP 503', 503)
        drain(worker)
    capture(m, activated, 'recovered-later', '2401')
    result = drain(worker)[-1]
    assert result['status'] == 'ok'
    assert result['outputs'][0]['value'] == '100'
    history = result['history']
    assert history and any(row['capture_id'] for values in history.values() for row in values if row['status'] == 'ok')


def test_history_operation_does_not_allow_invalid_arithmetic_activation(monitor):
    m, activated, _ = setup_monitor(monitor)
    plan = cost_plan(activated)
    plan['outputs'] = [
        {'id': 'invalid', 'name': 'Invalid division', 'expression': {'op': 'divide', 'args': [
            {'op': 'input', 'id': 'price'}, {'op': 'constant', 'value': '0'}]}},
        {'id': 'history', 'name': 'Earlier price', 'expression': {'op': 'previous', 'id': 'price'}}]
    plan['rules'] = []
    worker = Automations(m.service)
    preview = worker.preview({'plan': plan, 'use_ai': False})
    assert preview['status'] == 'needs_input'
    with pytest.raises(ValueError, match='questions'):
        worker.activate({'draft_id': preview['draft_id']})


@pytest.mark.parametrize('change', ['failed', 'stale', 'source_paused', 'monitor_paused', 'removed'])
def test_queued_notification_rechecks_dependencies_even_when_calculation_worker_is_behind(monitor, tmp_path, change):
    from parity.automation_notifications import ConnectionStore, Notifications
    m, activated, _ = setup_monitor(monitor)
    store = ConnectionStore(tmp_path / 'connections')
    connection = store.save({'name': 'Explicit operations destination', 'url': 'https://hooks.example.test/send', 'enabled': True})
    plan = cost_plan(activated)
    plan['rules'][0]['connections'] = [connection['id']]
    worker, auto, _ = activate(m, plan)
    drain(worker)
    pending = worker.db.one(select(a.automation_deliveries).where(a.automation_deliveries.c.automation_id == auto['id']))
    assert pending['status'] == 'queued'
    calls = []
    notifier = Notifications(m.service, store, lambda *args, **kwargs: calls.append(1))
    claim = notifier.claim()
    assert claim
    if change == 'failed':
        m.process_error(activated['source'], 'notify-failure', URL, 'HTTP 503', 503)
    elif change == 'stale':
        with worker.db.tx() as c:
            c.execute(ms.monitor_field_states.update().where(ms.monitor_field_states.c.monitor_id == activated['monitor']['id'])
                .values(last_verified_at=time.time() - 10000))
    elif change == 'source_paused':
        m.service.set_source(activated['source']['id'], paused=True)
    elif change == 'monitor_paused':
        m.set_paused(activated['monitor']['id'], True)
    else:
        m.service.remove_source(activated['source']['id'])
    # Deliberately do not run the calculation worker again before delivery.
    assert notifier.deliver(claim)['status'] == 'disabled'
    assert calls == []
    assert len(alerts(worker, auto['id'])) == 1  # The in-app record remains evidence.
