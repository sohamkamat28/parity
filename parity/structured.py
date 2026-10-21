"""Deterministic HTML field discovery and extraction. No model or network calls."""
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup, Tag
import soupsieve

TYPES = {'text', 'number', 'currency', 'percentage', 'date', 'table', 'list'}
MAX_FIELDS = 40


def clean(value):
    return re.sub(r'\s+', ' ', '' if value is None else str(value)).strip()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def soup_for(body):
    soup = BeautifulSoup(body, 'html.parser')
    for node in soup.select('script,style,noscript,template,iframe,object,svg,[hidden],[aria-hidden="true"]'):
        if node.name!='script' or node.get('type','').lower()!='application/ld+json':node.decompose()
    return soup


def css_path(node):
    if node.get('id'):
        return '#' + soupsieve.escape(node['id'])
    parts = []
    while isinstance(node, Tag) and node.name != '[document]':
        if node.get('id'):
            parts.insert(0, '#' + soupsieve.escape(node['id']))
            break
        siblings = list(node.parent.find_all(node.name, recursive=False)) if node.parent else [node]
        parts.insert(0, node.name + (f':nth-of-type({siblings.index(node)+1})' if len(siblings) > 1 else ''))
        node = node.parent
    return ' > '.join(parts)


def safe_url(base, href):
    url = urljoin(base, href or '')
    return url if urlsplit(url).scheme in ('http', 'https') else None


def unit_from(text, percentages=True):
    currency = 'INR' if re.search(r'₹|\b(?:Rs\.?|INR)\b', text, re.I) else ('USD' if '$' in text or re.search(r'\bUSD\b', text) else ('EUR' if '€' in text else ('GBP' if '£' in text else '')))
    scale = next((label for pattern, label in [(r'\b(?:crores?|cr)\.?\b', 'crore'), (r'\b(?:lakhs?|lac)\b', 'lakh'), (r'\bbillion\b', 'billion'), (r'\bmillion\b', 'million'), (r'\bthousand\b', 'thousand')] if re.search(pattern, text, re.I)), '')
    physical = re.search(r'\b(?:kg|mg|g|km|cm|mm|m|MW|kW|W|kWh|MWh|GB|MB|litres?|liters?|tonnes?)\b', text)
    return '%' if percentages and '%' in text else (' '.join(x for x in (currency, scale) if x) or (physical.group() if physical else ''))


def infer_type(raw):
    text = clean(raw)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text) or re.fullmatch(r'\d{1,2}\s+[A-Za-z]+\s+\d{4}', text):
        return 'date'
    if re.fullmatch(r'[-+()\d,.\s]+\s*%', text):
        return 'percentage'
    if re.search(r'₹|\$|€|£|\b(?:Rs\.?|INR|USD)\b', text, re.I) and re.search(r'\d', text):
        return 'currency'
    if re.fullmatch(r'[-+]?\(?[\d,.\s]+\)?(?:\s*(?:Cr\.?|crore|lakh|million|billion|kg|MW|kW|km))?', text, re.I) and re.search(r'\d', text):
        return 'number'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text) or re.fullmatch(r'\d{1,2}\s+[A-Za-z]+\s+\d{4}', text):
        return 'date'
    return 'text'


def normalize(raw, kind, unit='', date_format=None):
    raw = clean(raw)
    if not raw:
        raise ValueError('The selected field is empty.')
    if kind == 'text':
        return raw, unit
    if kind == 'date':
        formats = [date_format] if date_format else ['%Y-%m-%d', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y', '%d-%b-%Y']
        for fmt in formats:
            try:
                return datetime.strptime(raw, fmt).date().isoformat(), unit
            except (ValueError, TypeError):
                pass
        raise ValueError('The date format is unclear. Select an explicit date format.')
    detected = unit_from(raw)
    if kind == 'percentage':
        detected = '%'
    numeric = re.sub(r'\bRs\.?', '', raw, flags=re.I)
    numeric = re.sub(r'₹|\$|€|£|%|\b(?:INR|USD|EUR|GBP|crores?|cr|lakhs?|lac|million|billion|thousand)\b\.?', '', numeric, flags=re.I).strip()
    numeric = numeric.replace(',', '').replace('\u2212', '-')
    for suffix in (detected, unit):
        if suffix and suffix != '%':
            numeric = re.sub(r'\s*'+re.escape(suffix)+r'\s*$', '', numeric).strip()
    if numeric.startswith('(') and numeric.endswith(')'):
        numeric = '-' + numeric[1:-1]
    if not re.fullmatch(r'[-+]?\d+(?:\.\d+)?', numeric):
        raise ValueError('The field does not contain one unambiguous numeric value.')
    try:
        value = Decimal(numeric)
    except InvalidOperation as error:
        raise ValueError('The numeric value is invalid.') from error
    if not value.is_finite():
        raise ValueError('The numeric value must be finite.')
    result = format(value, 'f')
    result = result.rstrip('0').rstrip('.') if '.' in result else result
    return result if result not in ('-0', '') else '0', detected or unit


def table_data(table):
    rows = table.find_all('tr')
    if len(rows) > 1001:
        raise ValueError('This table exceeds the 1,000-row monitoring limit.')
    matrix = []
    for row in rows:
        cells = row.find_all(['th', 'td'], recursive=False)
        if cells:
            matrix.append(([clean(cell.get_text(' ', strip=True)) for cell in cells], any(cell.name == 'th' for cell in cells)))
    if not matrix:
        raise ValueError('The selected table contains no rows.')
    header_index = next((i for i, (_, has_th) in enumerate(matrix) if has_th), 0)
    headers = matrix[header_index][0]
    if len(set(headers)) != len(headers):
        raise ValueError('Table headers must be unique. Review the table mapping.')
    if len(headers) > 100:
        raise ValueError('This table exceeds the 100-column monitoring limit.')
    caption = table.find('caption')
    context = clean(caption.get_text(' ', strip=True)) if caption else ''
    heading = table.find_previous(['h1', 'h2', 'h3', 'h4'])
    if heading:
        context = clean(heading.get_text(' ', strip=True)) + ' ' + context
    parent_text = clean(table.parent.get_text(' ', strip=True))[:250] if table.parent else ''
    unit = unit_from(context + ' ' + parent_text, percentages=False)
    result, seen = [], {}
    for values, _ in matrix[header_index+1:]:
        if len(values) != len(headers):
            raise ValueError('Table columns changed or use merged cells. Review the table mapping.')
        label = values[0]
        if not label or label in seen:
            raise ValueError('Table row labels must be nonempty and unique. Review the table mapping.')
        seen[label] = seen.get(label, 0)+1
        key = label if seen[label] == 1 else f'{label} ({seen[label]})'
        cells = []
        for index, raw in enumerate(values[1:], 1):
            normalized, cell_unit = None, unit
            if raw not in ('', '-', '—', 'N/A', 'NA'):
                kind = infer_type(raw)
                try:
                    normalized, cell_unit = normalize(raw, kind, unit)
                except ValueError:
                    normalized = raw
            cells.append({'period': headers[index], 'raw_text': raw, 'value': normalized, 'unit': cell_unit})
        result.append({'key': key, 'label': label, 'values': {cell['period']: cell['raw_text'] for cell in cells}, 'cells': cells})
    return {'headers': headers, 'rows': result, 'unit': unit, 'context': context.strip()}


def json_entities(soup):
    """Read bounded schema.org objects without evaluating scripts or following URLs."""
    cached=soup.__dict__.get('_parity_json_entities')
    if cached is not None:return cached
    found=[];visited=0
    def walk(node,depth=0):
        nonlocal visited
        visited+=1
        if visited>1000 or depth>12:return
        if isinstance(node,list):
            for child in node[:200]:walk(child,depth+1)
        elif isinstance(node,dict):
            kind=node.get('@type',[]);kind=kind if isinstance(kind,list) else [kind]
            if any(str(t).split('/')[-1] in ('Product','Offer','AggregateOffer') for t in kind):
                identity=next((key+':'+str(node[key]) for key in ('@id','sku','productID','url','name') if isinstance(node.get(key),(str,int)) and str(node[key]).strip()),None)
                if identity:found.append((identity,node))
            for child in list(node.values())[:100]:
                if isinstance(child,(dict,list)):walk(child,depth+1)
    size=0
    for script in soup.select('script[type="application/ld+json"]')[:16]:
        raw=script.string or '';size+=len(raw)
        if size>262144:break
        try:walk(json.loads(raw))
        except (ValueError,RecursionError):continue
    soup.__dict__['_parity_json_entities']=found
    return found


def json_path(node,path):
    for part in path:
        if part=='__single__':
            if not isinstance(node,list) or len(node)!=1:raise LookupError('Structured data now contains multiple offers. Review this field.')
            node=node[0]
        elif isinstance(node,dict) and part in node:node=node[part]
        else:raise LookupError('The saved structured-data property is missing.')
    if not isinstance(node,(str,int,float)) or isinstance(node,bool):raise ValueError('The structured-data property is not a scalar value.')
    return node


def validate_rule(rule):
    if not isinstance(rule, dict) or rule.get('kind') not in ('scalar', 'label_value', 'table', 'table_cell', 'dated_table_cell', 'list', 'json_ld'):
        raise ValueError('Select a supported extraction rule.')
    if rule['kind']=='json_ld':
        if not isinstance(rule.get('entity'),str) or len(rule['entity'])>2000:raise ValueError('A stable structured-data entity is required.')
        for key in ('path','unit_path'):
            path=rule.get(key,[])
            if not isinstance(path,list) or (key=='path' and not path) or len(path)>8 or any(not isinstance(p,str) or not p or len(p)>100 for p in path):raise ValueError('Invalid structured-data property path.')
        return
    selector = rule.get('selector')
    if not isinstance(selector, str) or not selector or len(selector) > 1500:
        raise ValueError('A valid content selector is required.')
    try:
        soupsieve.compile(selector)
        for key in ('item_selector', 'value_selector','unit_selector'):
            if rule.get(key):
                if not isinstance(rule[key],str) or len(rule[key])>1500:raise ValueError('Invalid auxiliary selector.')
                soupsieve.compile(rule[key])
    except Exception as error:
        raise ValueError('The CSS selector is invalid.') from error
    attr = rule.get('attribute')
    if attr and attr not in ('href', 'title', 'datetime', 'content', 'value', 'aria-label') and not re.fullmatch(r'data-[a-z0-9_-]+', attr):
        raise ValueError('The selected attribute is unsupported.')
    if rule.get('unit_attribute') not in (None,'content','value','aria-label'):raise ValueError('Unsupported unit attribute.')
    if rule.get('period_mode', 'fixed') not in ('fixed', 'latest'):
        raise ValueError('Choose a fixed or latest reporting period.')
    if rule['kind']=='dated_table_cell':
        if not isinstance(rule.get('column'),str) or not rule['column'] or len(rule['column'])>120:raise ValueError('A stable labelled column is required.')
        if rule.get('row_date_format') not in ('%d/%m/%Y','%m/%d/%Y','%Y-%m-%d'):raise ValueError('An explicit row-date format is required.')
        if rule.get('session','') not in ('','AM','PM'):raise ValueError('Unsupported publication session.')


def extract_field(body, field, url):
    rule = field.get('rule', {})
    validate_rule(rule)
    kind = field.get('type', 'text')
    if kind not in TYPES:
        raise ValueError('Unsupported field type.')
    if (kind == 'table') != (rule['kind'] == 'table') or (kind == 'list') != (rule['kind'] == 'list'):
        raise ValueError('Table and repeating-list fields require their matching extraction rule.')
    soup = body if isinstance(body, BeautifulSoup) else soup_for(body)
    if rule['kind']=='dated_table_cell':
        tables=soup.select(rule['selector'])
        if len(tables)!=1:raise LookupError('The dated table is missing or ambiguous.')
        rows=[]
        for row in tables[0].find_all('tr')[:1000]:
            cells=row.find_all(['td','th'],recursive=False)
            if not cells or not re.fullmatch(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}',clean(cells[0].get_text(' ',strip=True))):continue
            try:date=datetime.strptime(clean(cells[0].get_text(' ',strip=True)),rule['row_date_format'])
            except ValueError:raise LookupError('The reporting-date format changed. Review this field.')
            selected=[cell for cell in cells[1:] if clean(cell.get('data-label') or cell.get('aria-label')).casefold()==rule['column'].casefold()]
            if len(selected)!=1:raise LookupError('The labelled dated-table column is missing or ambiguous.')
            rows.append((date,selected[0]))
        if not rows:raise LookupError('No dated reporting rows were found.')
        newest=max(date for date,node in rows)
        selected=[node for date,node in rows if date==newest]
        if len(selected)!=1:raise LookupError('The newest reporting date appears more than once.')
        raw=clean(selected[0].get_text(' ',strip=True));value,unit=normalize(raw,kind,rule.get('unit',''))
        period=newest.date().isoformat()+((' '+rule['session']) if rule.get('session') else '')
        return dict(value=value,raw_text=raw,unit=unit,period=period,locator=rule['selector']+' / date: '+period+' / column: '+rule['column'],fingerprint=fingerprint(dict(type=kind,value=value,unit=unit,period=period)))
    if rule['kind']=='json_ld':
        entities=[node for identity,node in json_entities(soup) if identity==rule['entity']]
        if len(entities)!=1:raise LookupError('The saved structured-data entity is missing or ambiguous.')
        raw=clean(json_path(entities[0],rule['path']))
        unit=clean(json_path(entities[0],rule['unit_path'])) if rule.get('unit_path') else rule.get('unit','')
        value,unit=normalize(raw,kind,unit,rule.get('date_format'))
        period=rule.get('period','')
        return dict(value=value,raw_text=raw,unit=unit,period=period,locator='JSON-LD / '+rule['entity']+' / '+'.'.join(rule['path']),
                    fingerprint=fingerprint(dict(type=kind,value=value,unit=unit,period=period)))
    matches = soup.select(rule['selector'])
    if rule['kind'] == 'label_value':
        label = clean(rule.get('label')).casefold()
        matches = [node for node in matches if clean(node.get_text(' ', strip=True)).casefold().startswith(label)]
    if not matches:
        raise LookupError(f'The {field.get("name", "selected")} field could not be found. Review its extraction rule.')
    if len(matches) != 1 and rule['kind'] != 'list':
        raise ValueError('The selector matches more than one field. Choose a more specific location.')
    node = matches[0]
    locator = rule['selector']
    period, unit = rule.get('period') or '', rule.get('unit') or ''
    if rule.get('unit_selector'):
        units=soup.select(rule['unit_selector'])
        if len(units)!=1:raise LookupError('The saved currency or unit location is missing or ambiguous.')
        unit=clean(units[0].get(rule['unit_attribute'],'')) if rule.get('unit_attribute') else clean(units[0].get_text(' ',strip=True))
        if not unit:raise ValueError('The currency or unit is empty.')
    if rule['kind'] in ('table', 'table_cell'):
        value = table_data(node)
        unit = unit or value['unit']
        if rule['kind'] == 'table':
            raw = clean(node.get_text(' ', strip=True))
        else:
            row = next((row for row in value['rows'] if row['key'] == rule.get('row')), None)
            if row is None:
                raise LookupError(f'The {rule.get("row", "selected")} row could not be found.')
            if rule.get('period_mode') == 'latest':
                if not row['cells']:
                    raise LookupError('This table has no reporting periods.')
                position = rule.get('latest_position', 'last')
                if position not in ('first', 'last'):
                    raise ValueError('Choose whether the newest reporting period is the first or last column.')
                period = row['cells'][0 if position == 'first' else -1]['period']
            cell = next((cell for cell in row['cells'] if cell['period'] == period), None)
            if cell is None:
                raise LookupError(f'The {period} reporting period could not be found.')
            raw = cell['raw_text']
            value, unit = normalize(raw, kind, unit, rule.get('date_format'))
            locator += ' / row: ' + row['label'] + ' / period: ' + period
    elif rule['kind'] == 'list':
        elements = node.select(rule.get('item_selector') or 'a[href]') if len(matches) == 1 else matches
        if len(elements) > 500:
            raise ValueError('This list exceeds the 500-item monitoring limit.')
        value, keys = [], set()
        for element in elements:
            anchor = element if element.name == 'a' else element.find('a', href=True)
            text = clean(element.get_text(' ', strip=True))
            link = safe_url(url, anchor.get('href')) if anchor else None
            if not text:
                continue
            key = str(element.get('data-id') or link or fingerprint(text))
            if key in keys:
                continue
            keys.add(key)
            date = element.find('time')
            value.append({'key': key, 'text': text, 'url': link, 'date': (date.get('datetime') or clean(date.get_text())) if date else None})
        value.sort(key=lambda item: item['key'])
        raw = '\n'.join(item['text'] for item in value)
    else:
        if rule.get('value_selector'):
            selected = node.select(rule['value_selector'])
            if len(selected) != 1:
                raise LookupError('The value inside the selected label could not be identified.')
            node = selected[0]
        raw = clean(node.get(rule['attribute'], '')) if rule.get('attribute') else clean(node.get_text(' ', strip=True))
        if rule['kind'] == 'label_value' and not rule.get('value_selector'):
            raw = re.sub(r'^' + re.escape(clean(rule.get('label'))) + r'\s*:?\s*', '', raw, flags=re.I)
        if rule.get('attribute') == 'href':
            raw = safe_url(url, raw) or ''
        value, unit = normalize(raw, kind, unit, rule.get('date_format'))
    canonical_value = value
    if isinstance(value, dict) and 'rows' in value:
        canonical_value = sorted([{'key': row['key'], 'cells': sorted([
            {key: cell[key] for key in ('period', 'value', 'unit')} for cell in row['cells']
        ], key=lambda cell: cell['period'])} for row in value['rows']], key=lambda row: row['key'])
    return {'value': value, 'raw_text': raw, 'unit': unit, 'period': period, 'locator': locator,
            'fingerprint': fingerprint({'type': kind, 'value': canonical_value, 'unit': unit, 'period': period})}


def discover(body, url):
    soup = soup_for(body)
    candidates, rules = [], set()
    def add(name, kind, rule):
        rule = {**rule, 'url': url}
        key = fingerprint(rule)
        if key in rules or len(candidates) >= 200:
            return
        rules.add(key)
        item = {'id': key[:24], 'name': clean(name)[:120] or 'Untitled field', 'type': kind, 'rule': rule, 'enabled': True}
        try:
            item.update(preview=extract_field(soup, item, url), valid=True, error=None)
        except (ValueError, LookupError) as error:
            item.update(preview=None, valid=False, error=str(error))
        candidates.append(item)
    for identity,entity in json_entities(soup):
        name=clean(entity.get('name') or 'Product')
        paths=[]
        if 'price' in entity:paths.append((['price'],['priceCurrency']))
        offers=entity.get('offers')
        if isinstance(offers,dict) and 'price' in offers:paths.append((['offers','price'],['offers','priceCurrency']))
        if isinstance(offers,list) and len(offers)==1 and isinstance(offers[0],dict) and 'price' in offers[0]:paths.append((['offers','__single__','price'],['offers','__single__','priceCurrency']))
        for path,unit_path in paths:
            try:json_path(entity,unit_path)
            except (ValueError,LookupError):unit_path=[]
            add('Current price — '+name,'currency' if unit_path else 'number',dict(kind='json_ld',selector='script[type="application/ld+json"]',entity=identity,path=path,unit_path=unit_path))
    for node in soup.select('[aria-label], [aria-labelledby], [itemprop], [data-label]')[:250]:
        if node.find_parent(['nav','footer','header']):continue
        label=clean(node.get('data-label') or node.get('aria-label'))
        if node.get('aria-labelledby'):
            label=clean(' '.join(ref.get_text(' ',strip=True) for ident in node['aria-labelledby'].split() if (ref:=soup.find(id=ident))))
        prop=node.get('itemprop','')
        if not label and prop:label='Current price' if prop=='price' else prop
        attribute='content' if node.has_attr('content') else 'data-value' if node.has_attr('data-value') else None
        raw=clean(node.get(attribute)) if attribute else clean(node.get_text(' ',strip=True))
        if label and infer_type(raw)!='text':
            # Responsive tables often label each cell rather than exposing usable
            # column headers. Bind numeric values to that label and the newest
            # explicitly parsed row date, instead of a moving nth-row selector.
            if node.name=='td' and node.parent and node.parent.name=='tr':
                cells=node.parent.find_all(['th','td'],recursive=False)
                date_text=clean(cells[0].get_text(' ',strip=True)) if cells else ''
                match=re.fullmatch(r'(\d{1,4})([-/])(\d{1,2})[-/](\d{1,4})',date_text)
                fmt=('%Y-%m-%d' if match and len(match[1])==4 and match[2]=='-' else '%d/%m/%Y' if match and int(match[1])>12 else '%m/%d/%Y' if match and int(match[3])>12 else None)
                table=node.find_parent('table')
                if fmt and table:
                    container=table.find_parent(attrs={'id':True})
                    context=clean(container.get('aria-label') or container.get('id')) if container else ''
                    session_match=re.search(r'(?:^|[-_\s])(am|pm)(?:$|[-_\s])',context,re.I)
                    session=session_match[1].upper() if session_match else ''
                    add(label+' — latest dated row'+((' '+session) if session else ''),infer_type(raw),dict(kind='dated_table_cell',selector=css_path(table),column=label,row_date_format=fmt,period_mode='latest',session=session))
                    continue
            rule=dict(kind='scalar',selector=css_path(node),**({'attribute':attribute} if attribute else {}))
            kind=infer_type(raw)
            if prop=='price':
                scope=node.find_parent(attrs={'itemscope':True})
                currencies=scope.select('[itemprop="priceCurrency"]') if scope else []
                if len(currencies)==1:
                    rule.update(selector=css_path(scope)+' [itemprop="price"]',unit_selector=css_path(scope)+' [itemprop="priceCurrency"]',unit_attribute='content' if currencies[0].has_attr('content') else None)
                    kind='currency'
            add(label,kind,rule)
    for table in soup.select('table')[:12]:
        property_rows = [row.find_all(['th', 'td'], recursive=False) for row in table.find_all('tr')]
        if property_rows and all(len(cells) == 2 and cells[0].name == 'th' and cells[1].name == 'td' for cells in property_rows):
            # Product/specification tables have labels, not reporting-period headers.
            for label, value in property_rows[:40]:
                name = clean(label.get_text(' ', strip=True))
                add(name, infer_type(value.get_text(' ', strip=True)), {'kind': 'label_value', 'selector': css_path(table)+' tr',
                    'label': name, 'value_selector': ':scope > td'})
            continue
        heading = table.find_previous(['h1', 'h2', 'h3', 'h4'])
        title = clean(heading.get_text(' ', strip=True)) if heading else 'Table'
        selector = css_path(table)
        add(title, 'table', {'kind': 'table', 'selector': selector})
        try:
            data = table_data(table)
            for row in data['rows'][:25]:
                if row['cells']:
                    cell = row['cells'][-1]
                    add(f'{row["label"]} — {cell["period"]}', infer_type(cell['raw_text']), {'kind': 'table_cell', 'selector': selector, 'row': row['key'], 'period': cell['period'], 'period_mode': 'fixed', 'unit': cell['unit']})
        except ValueError:
            pass
    for label in soup.select('dt')[:60]:
        value = label.find_next_sibling('dd')
        if value:
            add(label.get_text(' ', strip=True), infer_type(value.get_text(' ', strip=True)), {'kind': 'scalar', 'selector': css_path(value)})
    for container in soup.select('li, [data-field], .metric, .stat')[:250]:
        label = container.select_one('.name, .label, .key, [data-label]')
        value = container.select_one('.value, .number, [data-value]')
        if label and value and len(clean(label.get_text())) < 120:
            relative = value.name + ''.join('.'+soupsieve.escape(cls) for cls in value.get('class', []))
            add(label.get_text(' ', strip=True), infer_type(value.get_text(' ', strip=True)), {'kind': 'label_value', 'selector': css_path(container), 'label': clean(label.get_text(' ', strip=True)), 'value_selector': relative})
    for node in soup.select('[data-monitor], time[datetime]')[:30]:
        attribute = 'datetime' if node.name == 'time' else None
        raw = node.get(attribute) if attribute else node.get_text(' ', strip=True)
        add(node.get('data-monitor') or 'Date', infer_type(raw), {'kind': 'scalar', 'selector': css_path(node), **({'attribute': attribute} if attribute else {})})
    # Ordinary product/metric markup rarely uses our fixture's .name/.value classes.
    # Generate rules from actual DOM locations, then validate them just like manual rules.
    for node in soup.select('span,strong,b,div,p,output,[itemprop="price"]')[:2500]:
        if node.get('itemprop')=='price' and any(c['rule'].get('unit_selector') and soup.select_one(c['rule']['selector']) is node for c in candidates):continue
        if node.find_parent(['nav', 'footer', 'header', 'table', 'del', 's']):
            continue
        attribute = 'content' if node.get('itemprop') == 'price' and node.has_attr('content') else None
        raw = clean(node.get(attribute)) if attribute else clean(node.get_text(' ', strip=True))
        if not raw or len(raw) > 160:
            continue
        # Prefer the innermost element representing a value, not its wrappers.
        if not attribute and any(clean(child.get_text(' ', strip=True)) == raw for child in node.find_all(recursive=False)):
            continue
        selector = css_path(node)
        if any(c['rule']['selector'] in (selector, css_path(node.parent)) and c['rule']['kind'] in ('scalar', 'label_value') for c in candidates):
            continue
        # A single text node such as "Current price: $12.50" is also a field.
        pair = re.fullmatch(r'([^:]{2,70}):\s*(.+)', raw)
        if pair and infer_type(pair[2]) != 'text':
            add(pair[1], infer_type(pair[2]), {'kind': 'label_value', 'selector': selector, 'label': pair[1]})
            continue
        kind = infer_type(raw)
        if kind == 'text':
            continue
        previous = node.find_previous_sibling()
        label = clean(previous.get_text(' ', strip=True)) if previous else ''
        if not label or len(label) > 70 or infer_type(label) != 'text':
            label = ''
        semantics = ' '.join([node.get('itemprop', ''), node.get('id', ''), *node.get('class', []), node.get('data-testid', '')]).lower()
        if label and ('price' in semantics or (kind == 'currency' and previous.name in ('h1', 'h2', 'h3'))) and 'price' not in label.lower():
            label = 'Current price — '+label
        if not label and ('price' in semantics or kind == 'currency'):
            label = 'Current price'
        if not label:
            label = clean(node.get('aria-label') or node.get('data-label'))
        if not label:
            continue
        rule = {'kind': 'scalar', 'selector': selector}
        if attribute:
            rule['attribute'] = attribute
        elif previous and clean(node.parent.get_text(' ', strip=True)).startswith(label):
            # Bind the pair to its label so a shifted layout fails validation.
            rule = {'kind': 'label_value', 'selector': css_path(node.parent), 'label': label,
                    'value_selector': ':scope > '+selector.split(' > ')[-1]}
        add(label, kind, rule)
    for node in soup.select('h1,h2,h3,p')[:60]:
        raw = clean(node.get_text(' ', strip=True))
        if raw and len(raw) <= 1200:
            add(raw[:70], 'text', {'kind': 'scalar', 'selector': css_path(node)})
    for node in soup.select('ul,ol')[:25]:
        if node.find('a', href=True):
            heading = node.find_previous(['h1', 'h2', 'h3', 'h4'])
            name = clean(heading.get_text(' ', strip=True)) if heading else 'Linked updates'
            add(name, 'list', {'kind': 'list', 'selector': css_path(node), 'item_selector': ':scope > li'})
    return candidates


def suggest(candidates, instructions):
    words = set(re.findall(r'[a-z0-9]+', instructions.casefold())) - {'track', 'monitor', 'show', 'me', 'please', 'the', 'and', 'of', 'a', 'in', 'with', 'latest', 'displayed', 'new', 'current'}
    synonyms = {'price': {'price', 'cost', 'quote'}, 'prices': {'price', 'cost', 'quote'}, 'cost': {'price', 'cost'}, 'revenue': {'revenue', 'sales', 'income'}, 'announcements': {'announcements', 'announcement', 'updates', 'news', 'notices'}, 'holding': {'holding', 'shareholding', 'promoter'}, 'capitalization': {'capitalization', 'cap'}}
    words |= set().union(*(synonyms.get(word, set()) for word in list(words))) if words else set()
    ranked = sorted(candidates, key=lambda item: (item['type']=='text', -len(words & set(re.findall(r'[a-z0-9]+', item['name'].casefold())))))
    selected = [item for item in ranked if item['valid'] and words & set(re.findall(r'[a-z0-9]+', item['name'].casefold()))]
    # Do not also select a heading/paragraph that merely repeats a typed field's label.
    typed_words = set().union(*(set(re.findall(r'[a-z0-9]+', item['name'].casefold())) for item in selected if item['type'] != 'text'))
    selected = [item for item in selected if item['type'] != 'text' or not (words & set(re.findall(r'[a-z0-9]+', item['name'].casefold()))) <= typed_words]
    if re.search(r'\bcurrent price\b', instructions, re.I) and any('current price' in item['name'].lower() for item in selected) and 'tax' not in instructions.lower():
        selected = [item for item in selected if 'price' not in item['name'].lower() or 'current price' in item['name'].lower()]
    return selected[:12]
