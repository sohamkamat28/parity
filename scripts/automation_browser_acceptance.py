"""Browser → API → isolated PostgreSQL → durable automation worker acceptance.

Creates and drops a unique parity_bench_* database. Models and paid APIs remain
stopped. The user's running installation, sources, private connections and data
are never used. Reports only synthetic fixture values and screenshots.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parity import config
from benchmark_v2 import fresh_database
from browser_acceptance import eventually, port
from run import OwnedProcesses


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-models',action='store_true')
    args=parser.parse_args()
    app_port, portal_port = port(), port()
    base, portal = f'http://127.0.0.1:{app_port}', f'http://127.0.0.1:{portal_port}'
    output_directory = ROOT / 'outputs/runtime' / ('automation-browser-' + uuid.uuid4().hex)
    output_directory.mkdir(parents=True)
    target = ROOT / 'docs/verification' / ('automation-browser-models.json' if args.with_models else 'automation-browser.json')
    report = {'models': 'enabled' if args.with_models else 'stopped', 'checks': [], 'screenshots': [], 'console_errors': [], 'status': 'running'}

    def passed(name):
        report['checks'].append(name)
        print('PASS: ' + name, flush=True)

    def screenshot(page, name):
        path = output_directory / (name + '.png')
        page.screenshot(path=str(path), full_page=True)
        report['screenshots'].append(str(path.relative_to(ROOT)))

    with fresh_database(os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL) as url:
        env = {**os.environ, 'DATABASE_URL': url, 'PARITY_DATA_DIR': str(output_directory / 'data'),
               'PARITY_PORT': str(app_port), 'PARITY_FIXTURE_ORIGIN': portal,
               'PARITY_LOCAL_CHAT_PORT': str(port()), 'PARITY_EMBEDDING_PORT': str(port()),
               'PARITY_ADMIN_TOKEN': secrets.token_urlsafe(32), 'PARITY_FIXTURE_TOKEN': secrets.token_urlsafe(32),
               'PARITY_CHAT_PROVIDER': 'local', 'PARITY_OFFLINE': '1', 'PARITY_EXTERNAL_WORKERS': '1',
               'PARITY_LOCAL_CHAT_TOKEN': '', 'PARITY_EMBEDDING_URL': 'http://127.0.0.1:1',
               'PARITY_EMBEDDING_TOKEN': secrets.token_urlsafe(32)}
        owned = OwnedProcesses(output_directory)
        try:
            if args.with_models:
                env['PARITY_LOCAL_CHAT_TOKEN']=secrets.token_urlsafe(32)
                env['PARITY_EMBEDDING_URL']='http://127.0.0.1:'+env['PARITY_EMBEDDING_PORT']
                executable=next((config.CACHE/'local-chat/runtime').rglob('llama-server.exe' if os.name=='nt' else 'llama-server'))
                model=config.CACHE/'local-chat'/(config.LOCAL_CHAT_MODEL+'.gguf')
                owned.start('local-chat',[str(executable),'--model',str(model),'--host','127.0.0.1','--port',env['PARITY_LOCAL_CHAT_PORT'],'--ctx-size','4096','--threads','4','--parallel','1','--n-gpu-layers','0','--alias',config.LOCAL_CHAT_MODEL,'--api-key',env['PARITY_LOCAL_CHAT_TOKEN']],ROOT,env)
                owned.start('embedding',[sys.executable,'-m','uvicorn','parity.embedding_server:app','--host','127.0.0.1','--port',env['PARITY_EMBEDDING_PORT'],'--no-access-log'],ROOT,env)
            owned.start('fixture', [sys.executable, '-m', 'uvicorn', 'tests.support.fixture_site:app',
                                   '--host', '127.0.0.1', '--port', str(portal_port), '--no-access-log'], ROOT, env)
            for role in ['scheduler', 'capture', 'automation', 'notification', 'api']:
                owned.start(role + '-worker' if role != 'api' else 'api',
                            [sys.executable, '-m', 'tests.support.runtime', role], ROOT, env)
            with httpx.Client(base_url=base, headers={'X-Parity-Token': env['PARITY_ADMIN_TOKEN']},
                              trust_env=False, timeout=120) as client:
                def ready():
                    owned.check()
                    try:
                        return client.get('/health/ready').status_code == 200 and httpx.get(portal + '/health/ready', trust_env=False).status_code == 200
                    except httpx.HTTPError:
                        return False
                eventually(ready, 90)
                sources = []
                for label in ['A', 'B']:
                    draft = client.post('/api/monitors/auto-preview', json={
                        'root_url': portal + '/en/metrics', 'name': 'Supplier ' + label,
                        'instructions': 'Track Current Price',
                        'settings': {'scope_mode': 'page', 'max_pages': 1, 'max_depth': 0, 'interval': 10, 'delay': 0}})
                    draft.raise_for_status()
                    draft = draft.json()
                    assert len(draft['fields']) == 1
                    draft['fields'][0]['name'] = 'Supplier ' + label + ' price'
                    result = client.post('/api/monitors', json={'draft_id': draft['draft_id'], 'fields': draft['fields']})
                    result.raise_for_status()
                    sources.append(result.json()['source'])
                passed('Two independently monitored synthetic supplier sources with stopped AI and embedding services')

                def automation_named(name):
                    return next((a for a in client.get('/api/automations').json()['items'] if a['name'] == name), None)

                def current_value(name, output):
                    row = automation_named(name)
                    return next((str(o['value']) for o in ((row or {}).get('current') or {}).get('outputs', []) if o['name'] == output), None)

                def fault(action, payload=None):
                    response = httpx.post(portal + '/admin/' + action, headers={'X-Fixture-Token': env['PARITY_FIXTURE_TOKEN']}, json=payload or {}, trust_env=False)
                    response.raise_for_status()

                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
                    page.goto(base)
                    page.request.post(base + '/api/session', data={'token': env['PARITY_ADMIN_TOKEN']})
                    page.reload()
                    page.get_by_role('button', name='Create calculation or automation', exact=True).click()
                    dialog = page.get_by_role('dialog')
                    dialog.get_by_label('What should Parity calculate or watch?', exact=True).fill('Alert when Supplier A price exceeds INR 1000')
                    dialog.get_by_role('button', name='Interpret instructions', exact=True).click()
                    expect(dialog.get_by_text('Validated', exact=True)).to_be_visible(timeout=20000)
                    dialog.get_by_role('button', name='Start automation', exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=20000)
                    alert_card = page.locator('.calculation-card').filter(has=page.get_by_role('heading', name='Supplier A price', exact=True))
                    expect(alert_card.locator('.calculation-value')).to_have_text('1200.5 INR', timeout=30000)
                    eventually(lambda: bool(client.get('/api/automation-alerts').json()['items']))
                    expect(page.locator('.automation-alert')).to_have_count(1, timeout=20000)
                    page.get_by_role('button', name='Acknowledge', exact=True).click()
                    expect(page.get_by_role('button', name='Acknowledged', exact=True)).to_be_disabled(timeout=15000)
                    passed('Natural-language threshold compiles, evaluates without models, creates a durable alert and acknowledges it through the browser')

                    alert_card.get_by_role('button', name='How this was calculated', exact=True).click()
                    evidence = page.get_by_role('dialog')
                    expect(evidence.get_by_role('heading', name='How this was calculated', exact=True)).to_be_visible()
                    expect(evidence.get_by_role('table')).to_be_visible()
                    evidence.get_by_role('button', name='Open immutable capture', exact=True).click()
                    expect(page.get_by_role('dialog').last.get_by_role('heading', name='Stored source evidence', exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.get_by_role('dialog').get_by_role('heading', name='How this was calculated', exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    passed('Calculation evidence lists exact inputs and opens immutable captures; Escape closes only the foremost evidence dialog')

                    page.get_by_role('button', name='Create calculation or automation', exact=True).click()
                    dialog = page.get_by_role('dialog')
                    dialog.get_by_label('What should Parity calculate or watch?', exact=True).fill('Compare supplier prices and include my handling fee')
                    dialog.get_by_role('button', name='Interpret instructions', exact=True).click()
                    expect(dialog.get_by_role('heading', name='A few details are needed', exact=True)).to_be_visible(timeout=20000)
                    assert len(client.get('/api/automations').json()['items']) == 1
                    dialog.get_by_role('button', name='Choose fields and build visually', exact=False).click()
                    dialog.get_by_label('Calculation name', exact=True).fill('Supplier comparison')
                    for name in ['Supplier A price', 'Supplier B price']:
                        dialog.locator('.automation-field-picker').get_by_role('checkbox', name=name, exact=False).check()
                    dialog.get_by_role('button', name='Add supplied input', exact=True).click()
                    parameter = dialog.locator('.automation-parameter-row')
                    parameter.get_by_label('Name', exact=True).fill('Handling fee')
                    parameter.get_by_label('Value', exact=True).fill('10')
                    parameter.get_by_label('Unit', exact=True).fill('INR')
                    dialog.get_by_role('button', name='Add calculated output', exact=True).click()
                    output = dialog.locator('.automation-output-editor').first
                    output.get_by_label('Output name', exact=True).fill('Supplier price gap')
                    output.get_by_label('Calculation operation', exact=True).select_option('subtract')
                    for index, name in enumerate(['Supplier A price', 'Supplier B price']):
                        argument = output.locator('.expression-argument').nth(index)
                        argument.get_by_label('Nested calculation operation', exact=True).select_option('input')
                        argument.get_by_label('Tracked field', exact=True).select_option(label=name + ' · Supplier ' + name.split()[1])
                    dialog.get_by_role('button', name='Add calculated output', exact=True).click()
                    output = dialog.locator('.automation-output-editor').nth(1)
                    output.get_by_label('Output name', exact=True).fill('Delivered gap')
                    output.get_by_label('Calculation operation', exact=True).select_option('add')
                    argument = output.locator('.expression-argument').nth(0)
                    argument.get_by_label('Nested calculation operation', exact=True).select_option('output')
                    argument.get_by_label('Calculation', exact=True).select_option(label='Supplier price gap')
                    argument = output.locator('.expression-argument').nth(1)
                    argument.get_by_label('Nested calculation operation', exact=True).select_option('parameter')
                    argument.get_by_label('Supplied input', exact=True).select_option(label='Handling fee')
                    dialog.get_by_role('button', name='Validate formula', exact=True).click()
                    expect(dialog.get_by_text('Validated', exact=True)).to_be_visible(timeout=15000)
                    dialog.get_by_role('button', name='Start automation', exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=20000)
                    eventually(lambda: current_value('Supplier comparison', 'Delivered gap') == '10')
                    expect(page.get_by_role('heading', name='Calculations & automations', exact=True)).to_be_visible(timeout=20000)
                    gap_card = page.locator('.calculation-card').filter(has=page.get_by_role('heading', name='Supplier price gap', exact=True))
                    delivered = page.locator('.calculation-card').filter(has=page.get_by_role('heading', name='Delivered gap', exact=True))
                    expect(gap_card.locator('.calculation-value')).to_have_text('0 INR')
                    expect(delivered.locator('.calculation-value')).to_have_text('10 INR')
                    passed('Ambiguous instructions request clarification without activation; visual field picker, supplied inputs and output dependencies create a cross-source calculation including zero')

                    delivered.get_by_text('Supplier comparison · controls', exact=True).click()
                    delivered.get_by_role('button', name='Edit calculation', exact=True).click()
                    dialog = page.get_by_role('dialog')
                    dialog.get_by_role('button', name='Choose fields and build visually', exact=False).click()
                    # Await interpretation before making edits; compilation must not overwrite user input.
                    expect(dialog.locator('.automation-parameter-row').get_by_label('Value', exact=True)).to_have_value('10')
                    dialog.locator('.automation-parameter-row').get_by_label('Value', exact=True).fill('20')
                    dialog.get_by_role('button', name='Validate formula', exact=True).click()
                    expect(dialog.get_by_text('Validated', exact=True)).to_be_visible(timeout=15000)
                    dialog.get_by_role('button', name='Save new revision', exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=20000)
                    expect(delivered.locator('.calculation-value')).to_have_text('20 INR', timeout=25000)
                    passed('Editing a supplied parameter creates a validated immutable formula revision and reevaluates its result')

                    expect(gap_card.locator('.chart-point').first).to_be_visible(timeout=20000)
                    gap_card.locator('.chart-point').first.focus()
                    page.keyboard.press('Enter')
                    expect(page.get_by_role('dialog').get_by_role('heading', name='How this was calculated', exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    gap_card.get_by_text('Trend and observation data', exact=True).click()
                    gap_card.get_by_text('Observation data', exact=True).click()
                    expect(gap_card.get_by_role('table')).to_be_visible()
                    evidence_ids = [a['current']['id'] for a in client.get('/api/automations').json()['items'] if a.get('current')]
                    screenshot(page, 'desktop-calculations')
                    passed('Calculated zero graphs, real timestamps, keyboard graph evidence and accessible observation tables')

                    fault('fault', {'target': 'metrics', 'status': 403})
                    eventually(lambda: automation_named('Supplier comparison')['current']['status'] != 'ok', 45)
                    expect(delivered.get_by_text('Needs attention', exact=True)).to_be_visible(timeout=20000)
                    expect(delivered.locator('.calculation-value')).to_have_text('20 INR')
                    expect(gap_card.get_by_role('table')).to_be_visible()
                    fault('clear-faults')
                    eventually(lambda: automation_named('Supplier comparison')['current']['status'] == 'ok', 45)
                    expect(delivered.get_by_text('Verified', exact=True)).to_be_visible(timeout=20000)
                    assert all(client.get('/api/calculations/' + identity).status_code == 200 for identity in evidence_ids)
                    passed('Source failure blocks fresh calculation, retains marked stale result and open observation table; recovery and prior immutable evidence remain valid')

                    page.route('**/api/events*', lambda route: route.abort())
                    page.reload()
                    fault('modify-honours')
                    expect(alert_card.locator('.calculation-value')).to_have_text('1250 INR', timeout=45000)
                    passed('Polling fallback updates calculated results when SSE is unavailable')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.get_by_role('button', name='Open navigation', exact=True).click()
                    page.keyboard.press('Tab')
                    assert page.locator('.sidebar').evaluate('(element)=>element.contains(document.activeElement)')
                    page.locator('.sidebar').get_by_role('button', name='Close navigation', exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.get_by_role('button', name='Create calculation or automation', exact=True).click()
                    expect(page.get_by_role('dialog').get_by_label('What should Parity calculate or watch?', exact=True)).to_be_focused()
                    page.keyboard.press('Escape')
                    screenshot(page, 'narrow-calculations')
                    passed('390px layout without horizontal overflow, keyboard navigation, composer focus and reduced motion')
                    if args.with_models:
                        eventually(lambda:client.get('/api/runtime').json()['embedding']['status']=='ready',90)
                        eventually(lambda:client.post('/api/chat/test').status_code==200,120)
                        result=client.post('/api/chat',json={'message':'What is the Delivered gap calculated by Supplier comparison?'}).json()
                        assert result['status']=='answered' and any(c.get('evaluation_id') for c in result['citations']),result
                        citation=next(c for c in result['citations'] if c.get('evaluation_id'))
                        assert client.get('/api/calculations/'+citation['evaluation_id']).status_code==200
                        assert citation['supporting_captures']
                        passed('Native free Qwen chat answers from server-calculated values and resolves calculation and source-capture citations')
                    assert not report['console_errors'], report['console_errors']
                    browser.close()
            report['status'] = 'passed'
        except Exception as error:
            report['status'] = 'failed'
            report['error'] = type(error).__name__ + ': ' + str(error)[:2500]
            raise
        finally:
            owned.close()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + '\n')
    print('Automation browser acceptance report: ' + str(target.relative_to(ROOT)), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
