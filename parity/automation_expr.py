"""Bounded calculation AST. Pure Decimal evaluation; no executable user code."""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import re


class CalculationError(ValueError):
    pass


def decimal(value):
    if isinstance(value, bool) or value is None:
        raise CalculationError('A numeric value is required; missing values are not zero.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise CalculationError('A finite decimal value is required.') from error
    if not result.is_finite() or abs(result.adjusted()) > 100:
        raise CalculationError('The number exceeds the supported decimal range.')
    return result


def number(value):
    value = decimal(value)
    text = format(value, 'f')
    return (text.rstrip('0').rstrip('.') if '.' in text else text) if value else '0'


@dataclass(frozen=True)
class Unit:
    dimensions: tuple = ()
    scale: Decimal = Decimal(1)
    label: str = ''

    def compatible(self, other):
        return self.dimensions == other.dimensions


# Canonical dimensions are kg, litre, second and metre. Currency identity is a dimension.
_ATOMS = {
    'kg': ('mass', '1'), 'g': ('mass', '.001'), 'mg': ('mass', '.000001'), 'tonne': ('mass', '1000'),
    'l': ('volume', '1'), 'ml': ('volume', '.001'),
    's': ('time', '1'), 'min': ('time', '60'), 'h': ('time', '3600'), 'day': ('time', '86400'),
    'm': ('length', '1'), 'cm': ('length', '.01'), 'mm': ('length', '.001'), 'km': ('length', '1000'),
    '%': ('percentage', '1'), 'pp': ('percentage', '1'),
    'item': ('count', '1'), 'count': ('count', '1'),
    'W': ('power', '1'), 'kW': ('power', '1000'), 'MW': ('power', '1000000'),
    'Wh': ('energy', '1'), 'kWh': ('energy', '1000'), 'MWh': ('energy', '1000000'),
    'B': ('data', '1'), 'KB': ('data', '1000'), 'MB': ('data', '1000000'), 'GB': ('data', '1000000000'),
}
_ALIASES = {'grams':'g', 'gram':'g', 'kilograms':'kg', 'kilogram':'kg', 'litres':'l', 'liters':'l', 'litre':'l', 'liter':'l',
            'seconds':'s', 'second':'s', 'minutes':'min', 'minute':'min', 'hours':'h', 'hour':'h', 'days':'day', 'items':'item',
            '₹':'INR', '$':'USD', '€':'EUR', '£':'GBP', 'L':'l', 'percent':'%', 'percentage points':'pp'}
_SCALES = {'thousand':Decimal(1000), 'lakh':Decimal(100000), 'crore':Decimal(10000000), 'million':Decimal(1000000), 'billion':Decimal(1000000000)}
_CURRENCY = {'INR','USD','EUR','GBP','JPY','CNY','AUD','CAD','CHF','SGD','AED','NZD','HKD','KRW','BRL','ZAR','RUB','BTC','ETH'}


def parse_unit(label=''):
    if not isinstance(label, str) or len(label) > 100:
        raise CalculationError('Use a supported unit with at most 100 characters.')
    label = label.strip()
    label = _ALIASES.get(label, label)
    if label in ('', '1', 'fraction', 'ratio'):
        return Unit()
    label = re.sub(r'\s+per\s+', '/', label, flags=re.I)
    dims, scale = {}, Decimal(1)
    pieces = re.split(r'([*/])', label)
    sign = 1
    for piece in pieces:
        if piece == '*':
            sign = 1
            continue
        if piece == '/':
            sign = -1
            continue
        piece = piece.strip()
        if piece == '1':
            continue
        scale_match = re.fullmatch(r'([A-Z]{3})\s+(thousand|lakh|crore|million|billion)', piece)
        if scale_match:
            atom, factor = scale_match.group(1), _SCALES[scale_match.group(2)]
        else:
            match = re.fullmatch(r'(\d+(?:\.\d+)?)?\s*([^\d\s]+)(?:\^(-?\d))?', piece)
            if not match:
                raise CalculationError('Unsupported unit: '+label)
            factor = decimal(match.group(1) or '1')
            atom = _ALIASES.get(match.group(2), match.group(2))
            if match.group(3):
                exponent = int(match.group(3)); sign *= exponent
        if factor <= 0:
            raise CalculationError('A unit denominator must be positive.')
        if atom in _CURRENCY:
            dimension, atom_scale = 'currency:'+atom, Decimal(1)
        elif atom in _ATOMS:
            dimension, atom_scale = _ATOMS[atom][0], Decimal(_ATOMS[atom][1])
        else:
            raise CalculationError('Unsupported unit: '+atom)
        dims[dimension] = dims.get(dimension, 0)+sign
        scale *= (factor*atom_scale) ** sign
    return Unit(tuple(sorted((key,value) for key,value in dims.items() if value)), scale, label)


def _unit_product(a, b, divide=False):
    dims = dict(a.dimensions)
    for key, power in b.dimensions:
        dims[key] = dims.get(key, 0)+(-power if divide else power)
    dims = {key:power for key,power in dims.items() if power}
    currencies = [(key,power) for key,power in dims.items() if key.startswith('currency:')]
    if len(currencies) > 2 or any(abs(power) > 1 for _,power in currencies):
        raise CalculationError('Currency multiplication is ambiguous. Supply an explicit exchange-rate input.')
    if len(currencies) == 2 and sorted(power for _,power in currencies) != [-1,1]:
        raise CalculationError('Different currencies require an explicit exchange-rate input.')
    aliases = {'mass':'kg','volume':'l','time':'s','length':'m','count':'item','percentage':'%', 'power':'W','energy':'Wh','data':'B'}
    def part(key, power):
        token = key.split(':',1)[1] if key.startswith('currency:') else aliases[key]
        return token if abs(power)==1 else token+'^'+str(abs(power))
    numerator = [part(k,p) for k,p in sorted(dims.items()) if p>0]
    denominator = [part(k,p) for k,p in sorted(dims.items()) if p<0]
    label = '*'.join(numerator) or ('1' if denominator else '')
    if denominator: label += '/'+'/'.join(denominator)
    return Unit(tuple(sorted(dims.items())), Decimal(1), label)


@dataclass
class Quantity:
    value: object
    unit: Unit = Unit()
    metadata: object = None

    def numeric(self):
        return decimal(self.value)


_NARY = {'sum','add','multiply','min','max','average','and','or'}
_BINARY = {'subtract','divide','ratio','percent_change','gt','gte','lt','lte','eq','ne'}
_UNARY = {'not','fraction','convert','negate','absolute'}
_HISTORY = {'previous','baseline','window_average','window_min','window_max'}
_TABLE = {'table_sum','table_average','table_min','table_max','table_count'}
_REFERENCES = {'input','parameter','output'}


def validate_plan(plan):
    if not isinstance(plan, dict): raise CalculationError('A calculation plan is required.')
    plan = deepcopy(plan)
    if plan.get('version',1) != 1: raise CalculationError('Unsupported calculation plan version.')
    plan['version'] = 1
    plan['name'] = str(plan.get('name') or 'Calculation').strip()[:200]
    groups = [('inputs',50),('parameters',100),('outputs',20),('rules',20)]
    ids = {}
    for key, limit in groups:
        items = plan.setdefault(key, [])
        if not isinstance(items,list) or len(items)>limit: raise CalculationError(f'{key} exceeds the {limit}-item limit.')
        ids[key] = set()
        for item in items:
            if not isinstance(item,dict): raise CalculationError('Each plan item must be an object.')
            ident = item.get('id')
            if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',ident) or ident in ids[key]:
                raise CalculationError('Plan identities must be nonempty and unique within their group.')
            ids[key].add(ident)
            item['name'] = str(item.get('name') or ident)[:200]
            if key == 'inputs' and any(not isinstance(item.get(k),str) or not item[k] for k in ('monitor_id','field_id','signature')):
                raise CalculationError('Input bindings require stable monitor, field and definition identities.')
            if key == 'parameters':
                item['value'] = number(item.get('value'))
                parse_unit(item.setdefault('unit',''))
            if key == 'inputs' and item.get('unit'): parse_unit(item['unit'])
    if not plan['outputs'] and not plan['rules']: raise CalculationError('Add a calculated output or condition.')
    nodes = 0
    refs = {}
    def visit(node, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes>1000 or depth>20: raise CalculationError('The calculation exceeds its expression complexity limit.')
        if not isinstance(node,dict) or not isinstance(node.get('op'),str): raise CalculationError('An expression operation is required.')
        op=node['op']
        if op in _REFERENCES:
            group={'input':'inputs','parameter':'parameters','output':'outputs'}[op]
            if node.get('id') not in ids[group]: raise CalculationError('An expression references an unknown '+op+'.')
            if set(node)-{'op','id'}: raise CalculationError('Unexpected reference properties.')
            return {node['id']} if op=='output' else set()
        if op=='constant':
            if set(node)-{'op','value','unit'}: raise CalculationError('Unexpected constant properties.')
            node['value']=number(node.get('value'));parse_unit(node.setdefault('unit',''));return set()
        if op in _HISTORY | _TABLE | {'list_count'}:
            if node.get('id') not in ids['inputs']: raise CalculationError('The history or aggregate input is unknown.')
            allowed={'op','id'}
            if op in _HISTORY:
                allowed.add('seconds')
                if op.startswith('window_'):
                    seconds=node.get('seconds',86400)
                    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 1<=seconds<=2592000:
                        raise CalculationError('History windows must be between one second and 30 days.')
                    node['seconds']=seconds
            if op in _TABLE:
                allowed |= {'column','rows'}
                if op!='table_count' and (not isinstance(node.get('column'),str) or not node['column']): raise CalculationError('Select a numeric table column.')
                if 'rows' in node and (not isinstance(node['rows'],list) or not node['rows'] or len(node['rows'])>1000 or any(not isinstance(x,str) for x in node['rows']) or len(set(node['rows']))!=len(node['rows'])):
                    raise CalculationError('Select unique stable table row keys.')
            if set(node)-allowed: raise CalculationError('Unexpected aggregate properties.')
            return set()
        if op not in _NARY | _BINARY | _UNARY | {'if'}: raise CalculationError('Unsupported expression operation: '+op)
        if set(node)-({'op','args','unit'} if op=='convert' else {'op','args'}): raise CalculationError('Unexpected expression properties.')
        args=node.get('args')
        if not isinstance(args,list) or not 1<=len(args)<=50: raise CalculationError('Expression arguments must be a bounded list.')
        if (op in _BINARY and len(args)!=2) or (op in _UNARY and len(args)!=1) or (op=='if' and len(args)!=3): raise CalculationError('Wrong number of expression arguments for '+op+'.')
        if op=='convert': parse_unit(node.get('unit'))
        found=set()
        for arg in args: found |= visit(arg,depth+1)
        return found
    for output in plan['outputs']:
        if output.get('display','number') not in ('number','budget','ranking'): raise CalculationError('Unsupported output display.')
        refs[output['id']]=visit(output.get('expression'))
    for rule in plan['rules']:
        visit(rule.get('condition'))
        for key, default, maximum in [('sustain_seconds',0,2592000),('cooldown_seconds',900,2592000)]:
            val=rule.setdefault(key,default)
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not 0<=val<=maximum: raise CalculationError('Invalid rule duration.')
        rule.setdefault('notify_recovery',False)
        if not isinstance(rule['notify_recovery'],bool): raise CalculationError('Recovery notification must be enabled explicitly.')
        connections=rule.setdefault('connections',[])
        if not isinstance(connections,list) or len(connections)>10 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',x) for x in connections): raise CalculationError('Use configured connection identities, not destinations or secrets.')
    seen,active=set(),set()
    def dependency(ident):
        if ident in active: raise CalculationError('Calculated outputs cannot contain a dependency cycle.')
        if ident in seen:return
        active.add(ident)
        for parent in refs[ident]:dependency(parent)
        active.remove(ident);seen.add(ident)
    for ident in refs: dependency(ident)
    interval=plan.setdefault('interval',60)
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not 10<=interval<=604800: raise CalculationError('Automation interval must be between 10 seconds and seven days.')
    plan.setdefault('allow_cross_period',False)
    if not isinstance(plan['allow_cross_period'],bool):raise CalculationError('Cross-period calculations require an explicit choice.')
    _validate_types(plan)
    return plan



def _validate_types(plan):
    """Reject invalid dimensions/condition types before runtime values are available."""
    bindings={item['id']:item for item in plan['inputs']}
    parameters={item['id']:item for item in plan['parameters']}
    output_defs={item['id']:item for item in plan['outputs']};cache={}
    def compatible(arguments):
        if any(kind!='number' for kind,_ in arguments):raise CalculationError('Arithmetic requires numeric expressions.')
        units=[unit for _,unit in arguments if unit is not None]
        if units and any(not unit.compatible(units[0]) for unit in units):raise CalculationError('Incompatible units or currency identities.')
        return units[0] if len(units)==len(arguments) else None
    def infer(node):
        op=node['op']
        if op=='output':
            ident=node['id']
            if ident not in cache:cache[ident]=infer(output_defs[ident]['expression'])
            return cache[ident]
        if op in ('input','parameter'):
            item=(bindings if op=='input' else parameters)[node['id']]
            return ('number',parse_unit(item.get('unit','')))
        if op=='constant':return ('number',parse_unit(node.get('unit','')))
        if op in _HISTORY:return infer({'op':'input','id':node['id']})
        if op in _TABLE:return ('number',parse_unit('') if op=='table_count' else None)
        if op=='list_count':return ('number',parse_unit(''))
        args=[infer(arg) for arg in node['args']]
        if op in ('and','or','not'):
            if any(kind!='boolean' for kind,_ in args):raise CalculationError('A condition must produce true or false.')
            return ('boolean',parse_unit(''))
        if op=='if':
            if args[0][0]!='boolean':raise CalculationError('A condition must produce true or false.')
            if args[1][0]!=args[2][0]:raise CalculationError('Both conditional branches must return the same value type.')
            return (args[1][0],compatible(args[1:]) if args[1][0]=='number' else parse_unit(''))
        if op in ('sum','add','subtract','min','max','average','ratio','percent_change','gt','gte','lt','lte','eq','ne'):
            unit=compatible(args)
            if op in ('gt','gte','lt','lte','eq','ne'):return ('boolean',parse_unit(''))
            if op in ('ratio','percent_change'):return ('number',parse_unit('' if op=='ratio' else '%'))
            if op=='subtract' and unit and unit.label=='%':unit=parse_unit('pp')
            return ('number',unit)
        if any(kind!='number' for kind,_ in args):raise CalculationError('Arithmetic requires numeric expressions.')
        if op in ('negate','absolute'):return args[0]
        if op=='fraction':
            if args[0][1] is not None and args[0][1].dimensions!=(('percentage',1),):raise CalculationError('Only percentages can be explicitly converted to fractions.')
            return ('number',parse_unit(''))
        if op=='convert':
            unit=parse_unit(node['unit'])
            if args[0][1] is not None and not unit.compatible(args[0][1]):raise CalculationError('The requested units are incompatible.')
            return ('number',unit)
        if op in ('multiply','divide'):
            if any(unit and any(key=='percentage' for key,_ in unit.dimensions) for _,unit in args):raise CalculationError('Convert percentages to fractions before multiplication or division.')
            if any(unit is None for _,unit in args):return ('number',None)
            unit=args[0][1]
            for _,other in args[1:]:unit=_unit_product(unit,other,op=='divide')
            return ('number',unit)
        raise CalculationError('Unknown expression type.')
    for item in plan['outputs']:infer(item['expression'])
    for item in plan['rules']:
        if infer(item['condition'])[0]!='boolean':raise CalculationError('Rule conditions must produce true or false.')


def evaluate_plan(plan, values, history=None):
    plan=validate_plan(plan)
    output_defs={item['id']:item for item in plan['outputs']};outputs={};metadata=[]
    parameters={item['id']:Quantity(decimal(item['value']),parse_unit(item['unit'])) for item in plan['parameters']}
    bindings={item['id']:item for item in plan['inputs']}
    periods={str(row.get('period')) for row in values.values() if row.get('period') not in ('',None)}
    sessions={str(row.get('session')) for row in values.values() if row.get('session') not in ('',None)}
    if not plan['allow_cross_period'] and (len(periods)>1 or len(sessions)>1):raise CalculationError('Input reporting periods or sessions do not align.')
    def input_value(ident):
        row=values.get(ident)
        if not isinstance(row,dict) or row.get('value') is None:raise CalculationError('Missing input: '+bindings[ident]['name'])
        if row.get('status','valid') not in ('valid','ok','current','unchanged','changed','verified'):raise CalculationError('Input is not valid: '+bindings[ident]['name'])
        val=row['value']
        return Quantity(val if isinstance(val,(dict,list)) else decimal(val),parse_unit(row.get('unit') or bindings[ident].get('unit','')))
    def compatible(items):
        if any(isinstance(item.value,bool) for item in items):raise CalculationError('A numeric value is required.')
        unit=items[0].unit
        if any(not unit.compatible(item.unit) for item in items): raise CalculationError('Incompatible units or currency identities.')
        return [item.numeric()*item.unit.scale/unit.scale for item in items],unit
    def aggregate(op,items):
        nums,unit=compatible(items)
        return Quantity(sum(nums) if op in ('sum','add') else min(nums) if op=='min' else max(nums) if op=='max' else sum(nums)/Decimal(len(nums)),unit)
    def boolean(item):
        if not isinstance(item.value,bool):raise CalculationError('A condition must produce true or false.')
        return item.value
    def expr(node):
        op=node['op']
        if op=='input':return input_value(node['id'])
        if op=='parameter':return parameters[node['id']]
        if op=='constant':return Quantity(decimal(node['value']),parse_unit(node['unit']))
        if op=='output':
            if node['id'] not in outputs:outputs[node['id']]=expr(output_defs[node['id']]['expression'])
            return outputs[node['id']]
        if op in _HISTORY:
            if history is None:raise CalculationError('No observation history is available.')
            rows=history(node['id'],op,node.get('seconds'))
            if not rows:raise CalculationError('Not enough comparable observation history.')
            current=input_value(node['id']);eligible=[]
            for row in rows:
                if row.get('value') is None or row.get('status','valid') not in ('valid','ok','changed','unchanged','verified'):continue
                latest=values[node['id']]
                definition_key='definition_signature' if row.get('definition_signature') is not None and latest.get('definition_signature') is not None else 'revision_id'
                if any(row.get(key)!=latest.get(key) for key in ('period',definition_key) if row.get(key) is not None and latest.get(key) is not None):continue
                unit=parse_unit(row.get('unit') or bindings[node['id']].get('unit',''))
                if unit.compatible(current.unit):eligible.append((row,Quantity(decimal(row['value']),unit)))
            if not eligible:raise CalculationError('Not enough comparable observation history.')
            eligible.sort(key=lambda item:(item[0].get('at',0),item[0].get('id','')))
            if op=='previous':
                latest=values[node['id']];before=[item for item in eligible if item[0].get('id',item[0].get('observation_id'))!=latest.get('observation_id',latest.get('id')) and (latest.get('at') is None or item[0].get('at',0)<latest['at'])]
                if not before:raise CalculationError('No previous comparable observation exists.')
                result=before[-1][1];used=[before[-1][0]]
            elif op=='baseline':result=eligible[0][1];used=[eligible[0][0]]
            else:result=aggregate({'window_average':'average','window_min':'min','window_max':'max'}[op],[item[1] for item in eligible]);used=[item[0] for item in eligible]
            metadata.append({'input_id':node['id'],'mode':op,'seconds':node.get('seconds'),'sample_count':len(used),'first_at':used[0].get('at'),'last_at':used[-1].get('at'),'observations':used})
            return result
        if op in _TABLE:
            source=input_value(node['id']).value
            if not isinstance(source,dict) or not isinstance(source.get('rows'),list):raise CalculationError('Select a structured table input.')
            rows=source['rows'];requested=node.get('rows')
            keys=[row.get('key') for row in rows]
            if len(set(keys))!=len(keys) or any(key is None for key in keys):raise CalculationError('Table row keys are ambiguous.')
            if requested:
                if any(key not in keys for key in requested):raise CalculationError('A selected table row is missing.')
                rows=[row for row in rows if row['key'] in requested]
            if op=='table_count':return Quantity(Decimal(len(rows)))
            selected=[]
            for row in rows:
                cells=[cell for cell in row.get('cells',[]) if cell.get('period',cell.get('column'))==node['column']]
                if len(cells)!=1 or cells[0].get('value') is None:raise CalculationError('A table cell is missing or ambiguous.')
                cell=cells[0];selected.append(Quantity(decimal(cell['value']),parse_unit(cell.get('unit',source.get('unit','')))))
            if not selected:raise CalculationError('No table rows match.')
            return aggregate({'table_sum':'sum','table_average':'average','table_min':'min','table_max':'max'}[op],selected)
        if op=='list_count':
            val=input_value(node['id']).value
            if isinstance(val,dict):val=val.get('items')
            if not isinstance(val,list):raise CalculationError('Select a repeating-list input.')
            keys=[item.get('key',item.get('url',item.get('id'))) for item in val if isinstance(item,dict)]
            if len(keys)!=len(val) or any(k is None for k in keys) or len(set(keys))!=len(keys):raise CalculationError('List item identities are missing or duplicated.')
            return Quantity(Decimal(len(val)))
        if op=='if':return expr(node['args'][1] if boolean(expr(node['args'][0])) else node['args'][2])
        args=[expr(arg) for arg in node['args']]
        if op in ('and','or'):return Quantity(all(boolean(a) for a in args) if op=='and' else any(boolean(a) for a in args))
        if op=='not':return Quantity(not boolean(args[0]))
        if op in ('sum','add','min','max','average'):return aggregate(op,args)
        if op=='convert':
            unit=parse_unit(node['unit'])
            if not args[0].unit.compatible(unit):raise CalculationError('The requested units are incompatible.')
            return Quantity(args[0].numeric()*args[0].unit.scale/unit.scale,unit)
        if op=='fraction':
            if args[0].unit.dimensions != (('percentage',1),):raise CalculationError('Only percentages can be explicitly converted to fractions.')
            return Quantity(args[0].numeric()/Decimal(100))
        if op in ('negate','absolute'):return Quantity(-args[0].numeric() if op=='negate' else abs(args[0].numeric()),args[0].unit)
        if op=='subtract':
            nums,unit=compatible(args)
            if unit.label=='%':unit=parse_unit('pp')
            return Quantity(nums[0]-nums[1],unit)
        if op in ('gt','gte','lt','lte','eq','ne'):
            nums,_=compatible(args);a,b=nums
            return Quantity({'gt':a>b,'gte':a>=b,'lt':a<b,'lte':a<=b,'eq':a==b,'ne':a!=b}[op])
        if op in ('ratio','percent_change'):
            nums,_=compatible(args)
            if not nums[1]:raise CalculationError('Division by zero is undefined.')
            return Quantity(nums[0]/nums[1] if op=='ratio' else (nums[0]-nums[1])/abs(nums[1])*Decimal(100),parse_unit('' if op=='ratio' else '%'))
        if op=='multiply':
            result=args[0]
            for other in args[1:]:
                if any(k=='percentage' for k,_ in result.unit.dimensions+other.unit.dimensions):raise CalculationError('Convert a percentage to a fraction before multiplying.')
                result=Quantity(result.numeric()*result.unit.scale*other.numeric()*other.unit.scale,_unit_product(result.unit,other.unit))
            return result
        if op=='divide':
            if not args[1].numeric():raise CalculationError('Division by zero is undefined.')
            if any(k=='percentage' for a in args for k,_ in a.unit.dimensions):raise CalculationError('Convert percentages to fractions before division.')
            return Quantity(args[0].numeric()*args[0].unit.scale/(args[1].numeric()*args[1].unit.scale),_unit_product(args[0].unit,args[1].unit,True))
        raise CalculationError('Unsupported calculation.')
    with localcontext() as context:
        context.prec=28
        result=[]
        for output in plan['outputs']:
            q=expr({'op':'output','id':output['id']})
            result.append({**output,'value':q.value if isinstance(q.value,bool) else number(q.numeric()),'unit':q.unit.label,'type':'boolean' if isinstance(q.value,bool) else 'number'})
        conditions={rule['id']:boolean(expr(rule['condition'])) for rule in plan['rules']}
        for output in result:
            if output['type']=='boolean':continue
            q=outputs[output['id']]
            budget=next((p for p in plan['parameters'] if 'budget' in (p['name']+' '+p['id']).lower() and parse_unit(p['unit']).compatible(q.unit)),None)
            if budget and output.get('display')=='budget':
                limit=decimal(budget['value'])*parse_unit(budget['unit']).scale/q.unit.scale
                expression=output['expression']
                remaining_output=expression.get('op')=='subtract' and expression.get('args',[{}])[0]=={'op':'parameter','id':budget['id']}
                used=limit-q.numeric() if remaining_output else q.numeric()
                output['budget']={'limit':number(limit),'used':number(used),'remaining':number(limit-used),'percent':number(used/limit*100) if limit else None,'unit':q.unit.label,'name':budget['name']}
            comparison=[]
            for binding in plan['inputs']:
                value=values.get(binding['id'],{}).get('value')
                if isinstance(value,(dict,list,bool)) or value is None:continue
                unit=parse_unit(values[binding['id']].get('unit') or binding.get('unit',''))
                if unit.compatible(q.unit):comparison.append({'input_id':binding['id'],'name':binding['name'],'value':number(decimal(value)*unit.scale/q.unit.scale),'unit':q.unit.label})
            if len(comparison)>1:
                comparison.sort(key=lambda r:(decimal(r['value']),r['name'],r['input_id']))
                output['comparison']=[dict(row,rank=index+1) for index,row in enumerate(comparison)]
    return {'outputs':result,'conditions':conditions,'history':metadata}
