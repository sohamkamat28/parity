import copy
import pytest
from parity.automation_expr import CalculationError, evaluate_plan, parse_unit, validate_plan
from parity.automation_planner import compile_instructions


def ref(op,ident):return {'op':op,'id':ident}
def literal(value,unit=''):return {'op':'constant','value':str(value),'unit':unit}
def call(op,*args):return {'op':op,'args':list(args)}
def binding(ident='price',unit='INR/10g'):
    return {'id':ident,'name':ident,'monitor_id':'monitor','field_id':ident,'signature':'definition-1','unit':unit}
def plan(expression,unit='INR/10g'):
    return {'version':1,'name':'Example','inputs':[binding(unit=unit)],'parameters':[],'outputs':[{'id':'result','name':'Result','expression':expression}],'rules':[]}
def result(expression,value='100',unit='INR/10g'):
    return evaluate_plan(plan(expression,unit),{'price':{'value':value,'unit':unit}})['outputs'][0]


def test_material_quantities_respect_rate_denominators_and_scale():
    expression=call('multiply',ref('input','price'),literal('20','g'))
    assert result(expression)=={'id':'result','name':'Result','expression':expression,'value':'200','unit':'INR','type':'number'}
    assert result(expression,'1000','INR/kg')['value']=='20'
    assert result(call('add',literal('2','kg'),literal('500','g')))['value']=='2.5'
    assert result(call('multiply',literal('1','INR crore'),literal('2')))['value']=='20000000'


@pytest.mark.parametrize('op,expected',[('sum','-2'),('average','-1'),('min','-3'),('max','1'),('subtract','-4'),('ratio','-3'),('percent_change','-400')])
def test_decimal_arithmetic_and_negative_values(op,expected):
    assert result(call(op,literal('-3'),literal('1')))['value']==expected
    assert result(call('sum',literal('.1'),literal('.2')))['value']=='0.3'
    assert result(call('multiply',literal('0'),literal('-4')))['value']=='0'


def test_currency_identities_explicit_exchange_and_percentage_points():
    with pytest.raises(CalculationError,match='currency'):
        result(call('sum',literal('1','USD'),literal('1','INR')))
    assert result(call('multiply',literal('100','USD'),literal('83','INR/USD')))['value']=='8300'
    assert result(call('multiply',literal('100','INR'),literal('.012','USD/INR')))['unit']=='USD'
    with pytest.raises(CalculationError,match='Currency|currencies'):
        result(call('multiply',literal('100','USD'),literal('2','INR')))
    assert result(call('subtract',literal('20','%'),literal('15','%')))['unit']=='pp'
    assert result(call('multiply',literal('100','INR'),call('fraction',literal('20','%'))))['value']=='20'
    with pytest.raises(CalculationError,match='fraction'):
        result(call('multiply',literal('100','INR'),literal('20','%')))
    with pytest.raises(CalculationError,match='zero'):
        result(call('divide',literal('1'),literal('0')))


def test_convert_units_and_compound_conditions():
    converted={'op':'convert','unit':'g','args':[literal('2','kg')]}
    assert result(converted)['value']=='2000'
    expression=call('if',call('and',call('gt',literal('2'),literal('1')),call('not',call('eq',literal('0'),literal('1')))),literal('4','INR'),literal('2','INR'))
    assert result(expression)['value']=='4'
    p=plan(expression);p['rules']=[{'id':'rule','name':'Above budget','condition':call('gt',ref('output','result'),literal('3','INR'))}]
    assert evaluate_plan(p,{'price':{'value':'1'}})['conditions']=={'rule':True}
    with pytest.raises(CalculationError,match='condition'):
        result(call('if',literal('1'),literal('2'),literal('3')))


def test_validation_cycles_complexity_missing_identity_and_no_code():
    p=plan(ref('output','result'))
    with pytest.raises(CalculationError,match='cycle'):validate_plan(p)
    p=plan(literal('1'));p['outputs'].append({'id':'other','expression':ref('output','result')});p['outputs'][0]['expression']=ref('output','other')
    with pytest.raises(CalculationError,match='cycle'):validate_plan(p)
    p=plan(literal('1'));del p['inputs'][0]['signature']
    with pytest.raises(CalculationError,match='identities'):validate_plan(p)
    p=plan({'op':'eval','code':'__import__("os").system("touch no")'})
    with pytest.raises(CalculationError,match='Unsupported'):validate_plan(p)
    p=plan(ref('input','no'))
    with pytest.raises(CalculationError,match='unknown'):validate_plan(p)
    p=plan(literal('1'));p['inputs']=[binding(str(i),'') for i in range(51)]
    with pytest.raises(CalculationError,match='50'):validate_plan(p)
    expr=literal('1')
    for _ in range(22):expr=call('negate',expr)
    with pytest.raises(CalculationError,match='complexity'):validate_plan(plan(expr))
    p=plan(literal('NaN'))
    with pytest.raises(CalculationError,match='decimal'):validate_plan(p)
    p=plan(literal('1'));p['rules']=[{'id':'r','condition':call('gt',literal(2),literal(1)),'connections':['https://secret.example/key']}]
    with pytest.raises(CalculationError,match='connection'):validate_plan(p)


def test_output_dependencies_and_immutable_plan():
    p=plan(ref('output','later'));p['outputs'].append({'id':'later','name':'Later','expression':literal('2')})
    original=copy.deepcopy(p)
    evaluated=evaluate_plan(p,{'price':{'value':'1'}})
    assert [o['value'] for o in evaluated['outputs']]==['2','2'] and p==original
    assert validate_plan(p)['interval']==60


def test_history_uses_actual_comparable_observations_and_metadata():
    p=plan(call('percent_change',ref('input','price'),{'op':'previous','id':'price'}),'INR')
    value={'value':'12','unit':'INR','period':'Q1','at':30,'id':'c','revision_id':'r'}
    history=[{'value':'5','unit':'USD','at':1,'id':'other-currency'},{'value':'9','unit':'INR','period':'Q0','at':10,'id':'other-period'},
        {'value':'10','unit':'INR','period':'Q1','at':20,'id':'b','revision_id':'r'},value]
    calls=[]
    def load(ident,mode,seconds):calls.append((ident,mode,seconds));return history
    evaluation=evaluate_plan(p,{'price':value},load)
    assert evaluation['outputs'][0]['value']=='20' and calls==[('price','previous',None)]
    assert evaluation['history'][0]['observations'][0]['id']=='b'
    p['outputs'][0]['expression']={'op':'window_average','id':'price','seconds':86400}
    evaluated=evaluate_plan(p,{'price':value},load)
    assert evaluated['outputs'][0]['value']=='11' and evaluated['history'][0]['sample_count']==2
    with pytest.raises(CalculationError,match='30 days'):
        validate_plan(plan({'op':'window_average','id':'price','seconds':2592001}))
    with pytest.raises(CalculationError,match='history'):evaluate_plan(p,{'price':value})


def test_absent_fields_zero_and_period_session_mismatches():
    with pytest.raises(CalculationError,match='Missing'):result(ref('input','price'),None)
    assert result(ref('input','price'),'0')['value']=='0'
    p=plan(call('sum',ref('input','price'),ref('input','other')),'INR');p['inputs'].append(binding('other','INR'))
    values={'price':{'value':'2','unit':'INR','period':'Q1','session':'AM'},'other':{'value':'3','unit':'INR','period':'Q2','session':'AM'}}
    with pytest.raises(CalculationError,match='periods'):evaluate_plan(p,values)
    p['allow_cross_period']=True
    assert evaluate_plan(p,values)['outputs'][0]['value']=='5'
    p['allow_cross_period']=False;values['other'].update(period='Q1',session='PM')
    with pytest.raises(CalculationError,match='sessions'):evaluate_plan(p,values)


def test_table_aggregates_validate_row_keys_columns_and_cells():
    value={'headers':['Metal','PM'],'rows':[{'key':'gold','cells':[{'period':'PM','value':'20','unit':'INR'}]},{'key':'silver','cells':[{'period':'PM','value':'5','unit':'INR'}]}]}
    expression={'op':'table_sum','id':'price','column':'PM','rows':['gold','silver']}
    assert result(expression,value,'')['value']=='25'
    expression['rows']=['silver'];assert result(expression,value,'')['value']=='5'
    expression['rows']=['missing']
    with pytest.raises(CalculationError,match='missing'):result(expression,value,'')
    expression['rows']=['gold'];value['rows'][0]['cells'].append({'period':'PM','value':'99','unit':'INR'})
    with pytest.raises(CalculationError,match='ambiguous'):result(expression,value,'')
    assert result({'op':'list_count','id':'price'},[{'key':'b'},{'key':'a'}],'')['value']=='2'
    with pytest.raises(CalculationError,match='duplicated'):result({'op':'list_count','id':'price'},[{'key':'b'},{'key':'b'}],'')


def catalog():
    return [{'monitor_id':'m','field_id':'gold916','signature':'r916','name':'916 Gold','unit':'INR/10g','value':'100'},
            {'monitor_id':'m','field_id':'gold750','signature':'r750','name':'750 Gold','unit':'INR/10g','value':'80'},
            {'monitor_id':'m','field_id':'silver','signature':'silver','name':'Silver 999','unit':'INR/kg','value':'50'}]


def test_material_budget_template_validates_and_calculates_without_models():
    instructions='Calculate the material cost of 20 grams of 916 gold, 10 grams of 750 gold and 500 grams of silver. Compare with my ₹5 lakh budget, graph the total, and alert me when it exceeds the budget.'
    compiled=compile_instructions(instructions,catalog(),use_ai=False)
    assert compiled['status']=='ready'
    outputs={row['id']:row for row in compiled['preview']['outputs']}
    assert outputs['total']['value']=='305' and outputs['remaining']['value']=='499695'
    assert compiled['preview']['conditions']=={'over_budget':False}
    assert len(compiled['plan']['inputs'])==3 and len(compiled['plan']['parameters'])==4


def test_planner_requests_unambiguous_fields_denominators_and_budget():
    c=catalog();c[0]['unit']='INR'
    result=compile_instructions('Calculate the cost of 20 grams of 916 gold with my budget.',c,use_ai=False)
    assert result['status']=='needs_input' and result['questions'][0]['id']=='unit_1'
    result=compile_instructions('Calculate the cost of 20 grams of 916 gold with my budget.',c,answers={'unit_1':'INR/10g'},use_ai=False)
    assert result['status']=='needs_input' and result['questions'][0]['id']=='budget'
    result=compile_instructions('Calculate the cost of 20 grams of 916 gold with my budget.',c,answers={'unit_1':'INR/10g','budget':{'value':'1000','unit':'INR'}},use_ai=False)
    assert result['status']=='ready'
    c=catalog();c.append({**c[0],'field_id':'gold916pm','name':'916 Gold PM'})
    c[0]['name']='916 Gold AM'
    assert compile_instructions('Calculate the cost of 20 grams of 916 gold',c,use_ai=False)['status']=='needs_input'
    assert compile_instructions('Calculate the cost of 20 grams of 916 gold',c,answers={'field_1':'gold916pm'},use_ai=False)['status']=='ready'


def test_generic_totals_thresholds_history_and_visual_builder():
    c=[{'monitor_id':'m','field_id':'price','signature':'r','name':'Copper price','unit':'INR','value':'20'}]
    compiled=compile_instructions('Alert me when Copper price exceeds ₹10',c,use_ai=False)
    assert compiled['status']=='ready' and compiled['preview']['conditions']['threshold'] is True
    compiled=compile_instructions('Show percentage change of Copper price from baseline',c,use_ai=False)
    assert compiled['status']=='ready' and compiled['plan']['outputs'][0]['expression']['args'][1]['op']=='baseline'
    compiled=compile_instructions('Average Copper price over 7 days',c,use_ai=False)
    assert compiled['plan']['outputs'][0]['expression']['seconds']==604800
    assert compile_instructions('Arbitrary unsupported algorithm and notify somebody',c,use_ai=False)['status']=='needs_input'
    p=plan(literal(1),'');p['inputs']=[]
    assert compile_instructions('Use this builder',c,answers={'plan':p},use_ai=False)['status']=='ready'
    p['inputs']=[binding('invented','')]
    with pytest.raises(CalculationError,match='no longer available'):compile_instructions('Use this builder',c,answers={'plan':p},use_ai=False)


def test_validation_rejects_invalid_untaken_branches_and_unready_history():
    p=plan(call('if',call('gt',literal(2),literal(1)),literal('2','INR'),literal('3','USD')))
    with pytest.raises(CalculationError,match='currency'):validate_plan(p)
    p=plan({'op':'previous','id':'price'})
    p['rules']=[{'id':'bad','condition':literal(1)}]
    with pytest.raises(CalculationError,match='conditions'):validate_plan(p)
    p=plan(call('multiply',literal('2','INR'),literal('5','USD')))
    with pytest.raises(CalculationError,match='currencies'):validate_plan(p)


def test_untrusted_model_cannot_invent_human_inputs(monkeypatch):
    import json
    import httpx
    from parity import automation_planner as planner
    c=catalog()
    p={'version':1,'name':'Unsafe','inputs':[],'parameters':[{'id':'budget','name':'Invented budget','value':'100','unit':'INR'}],
       'outputs':[{'id':'cost','name':'Cost','expression':ref('parameter','budget')}],'rules':[]}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':json.dumps({'status':'ready','plan':p})}}]}
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return Response()
    monkeypatch.setenv('PARITY_LOCAL_CHAT_TOKEN','test-not-a-secret')
    monkeypatch.setattr(httpx,'Client',Client)
    assert planner._local_plan('Calculate a business budget in INR',c,{}) is None
    assert planner._local_plan('Calculate a budget of INR100',c,{})['status']=='ready'


def test_count_template_uses_stable_items_without_ai():
    c=[{'monitor_id':'m','field_id':'announcements','signature':'v','name':'Announcements','unit':'','type':'list','value':[{'key':'b'},{'key':'a'}]}]
    compiled=compile_instructions('Count Announcements',c,use_ai=False)
    assert compiled['status']=='ready' and compiled['preview']['outputs'][0]['value']=='2'


def test_definition_signature_allows_unchanged_mapping_revisions():
    p=plan({'op':'previous','id':'price'},'INR')
    current={'id':'new','value':'12','unit':'INR','at':30,'definition_signature':'same','revision_id':'new-revision'}
    before={'id':'old','value':'10','unit':'INR','at':10,'definition_signature':'same','revision_id':'old-revision'}
    assert evaluate_plan(p,{'price':current},lambda *args:[before,current])['outputs'][0]['value']=='10'
    before['definition_signature']='changed'
    with pytest.raises(CalculationError,match='previous'):evaluate_plan(p,{'price':current},lambda *args:[before,current])


def test_templates_do_not_drop_unhandled_budget_fees_or_compound_conditions():
    fields=[{'monitor_id':'m','field_id':'price','signature':'price','name':'Price','unit':'INR','value':'100'}]
    for text in ('Calculate sum of Price and compare it to my INR 200 budget',
                 'Calculate total Price multiplied by 3',
                 'Alert when Price exceeds INR 100 and is below INR 200',
                 'Calculate the cost of 20 grams of 916 gold plus a handling fee of INR 20'):
        assert compile_instructions(text,fields,use_ai=False)['status']=='needs_input'


def test_budget_utilization_and_ranked_comparison_are_server_calculated():
    compiled=compile_instructions('Calculate the cost of 20 grams of 916 gold with my INR 250 budget',catalog(),use_ai=False)
    assert compiled['status']=='ready'
    total=next(o for o in compiled['preview']['outputs'] if o['id']=='total')
    assert total['budget']=={'limit':'250','used':'200','remaining':'50','percent':'80','unit':'INR','name':'Material budget'}
    p=plan(call('subtract',ref('input','price'),ref('input','other')),'INR')
    p['inputs'].append(binding('other','INR'))
    output=evaluate_plan(p,{'price':{'value':'100','unit':'INR'},'other':{'value':'80','unit':'INR'}})['outputs'][0]
    assert [row['value'] for row in output['comparison']]==['80','100']
    assert [row['rank'] for row in output['comparison']]==[1,2]
