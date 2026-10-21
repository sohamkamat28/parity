import {useEffect,useRef,useState} from 'react';
import {Calculator,ChevronRight,History,Pause,Play,Plus,RefreshCw,Settings2,ShieldCheck,TriangleAlert} from 'lucide-react';
import type {Shared} from './App';
import type {Automation,Capture,DashboardData,Monitor,MonitorField,Observation,PageResult,Source} from './types';
import {api,date,patch,post,relative} from './api';
import {Badge,Empty,ErrorBox,External,Modal,SectionTitle,Skeleton,Spinner,Status} from './ui';
import {MonitorWizard} from './MonitorWizard';
import {AutomationCards,AutomationAlerts,AutomationDeliveries,AutomationComposer,CalculationEvidence,useAutomations} from './Automations';

function checkError(message:string){return /nodename nor servname|Name or service not known|getaddrinfo failed/.test(message)?'Website DNS lookup failed. Check the URL and this device’s network connection.':message;}
export function displayValue(value:any,unit?:string):string {
 if(value===null||value===undefined||value==='')return 'Not available';
 if(typeof value==='object')return Array.isArray(value)?`${value.length} items`:JSON.stringify(value);
 const text=String(value);return unit&&!text.includes(unit)?`${text} ${unit}`:text;
}
export function MonitoredValue({field,compact=false}:{field:MonitorField;compact?:boolean}){
 const value=field.value??field.preview?.value;
 if(value===null||value===undefined)return <p className="muted">No verified value yet.</p>;
 if(field.type==='table'&&typeof value==='object'){
  const rows=value.rows??[];const headers=value.headers??[];
  const columns=headers.slice(1).map((h:any)=>typeof h==='string'?h:String(h.label??h.name??h));
  return <div className="monitor-table-scroll" tabIndex={0} aria-label={`${field.name} table`}><table className="monitor-table"><thead><tr><th scope="col">Item</th>{columns.map((h:string,i:number)=><th scope="col" key={i}>{h}</th>)}</tr></thead><tbody>{rows.slice(0,compact?5:100).map((r:any,i:number)=><tr key={r.key??i}><th scope="row">{r.label??r.key??i+1}</th>{columns.map((h:string,j:number)=>{const cell=r.cells?.find((c:any)=>c.period===h)??r.cells?.[j];const raw=r.values?.[h]??cell?.raw_text??cell?.value;const changed=field.change?.cells?.some((c:any)=>c.row===r.key&&c.period===h);return <td key={j} className={changed?'cell-changed':''}>{displayValue(raw,cell?.unit)}</td>;})}</tr>)}</tbody></table>{compact&&rows.length>5&&<p className="table-note">Showing 5 of {rows.length} rows. Open evidence to inspect all rows.</p>}</div>;
 }
 if(field.type==='list'&&Array.isArray(value))return <ul className="monitor-items">{value.slice(0,compact?5:100).map((item:any,i:number)=><li key={item.key??i}><div>{item.url?<External url={item.url}>{item.text??item.title??item.url}</External>:<span>{item.text??item.title??String(item)}</span>}{<small>{item.date?`Published ${item.date}`:item.first_observed_at?`First observed ${date(item.first_observed_at)}`:'Publication date unavailable'}</small>}</div></li>)}{compact&&value.length>5&&<li className="muted">{value.length-5} more entries in evidence</li>}{!value.length&&<li className="muted">No entries are currently listed.</li>}</ul>;
 return <div className={`observed-value ${field.type==='text'?'text-value':''}`}>{displayValue(value,field.unit??field.preview?.unit)}</div>;
}
function fieldState(field:MonitorField){
 if(field.status==='ok')return {label:'Verified',tone:'green'};
 if(field.status==='pending'||!field.status)return {label:'Waiting for check',tone:'neutral'};
 if(field.status==='stale')return {label:'Overdue',tone:'amber'};
 if(['missing','invalid'].includes(field.status))return {label:'Needs repair',tone:'amber'};
 return {label:'Check failed',tone:'amber'};
}
function FieldOverview({field:f,openCapture,onHistory}:{field:MonitorField;openCapture:Shared['openCapture'];onHistory:()=>void}){
 const [expanded,setExpanded]=useState(false);
 const state=fieldState(f),value=f.value??f.preview?.value;
 const structured=f.type==='table'||f.type==='list';
 const summary=f.type==='table'?`${value?.rows?.length??0} rows · ${Math.max(0,(value?.headers?.length??1)-1)} columns`:f.type==='list'?`${Array.isArray(value)?value.length:0} items`:'';
 return <article className={`monitor-widget overview-field ${f.status!=='ok'?'field-unverified':''}`} aria-label={`${f.name} tracked field`}>
  <details className="field-details" open={expanded} onToggle={e=>setExpanded(e.currentTarget.open)}>
   <summary>
    <h3 title={f.name}>{f.name.replace(' — latest dated row',' ·')}</h3>
    <span className="field-glance">{structured&&value!=null?<span className="structured-count">{summary}</span>:<MonitoredValue field={f}/>}</span>
    <span className="overview-period">{f.period||'—'}</span>
    <span className="field-row-action">{f.status!=='ok'&&<Badge tone={state.tone}>{state.label}</Badge>}<span>Details<ChevronRight size={13}/></span></span>
   </summary>
   {expanded&&<div className="field-detail-body">
    <Badge tone={state.tone}>{state.label}</Badge>
    {structured&&<MonitoredValue field={f} compact/>}{f.type==='text'&&<p className="field-full-text">{displayValue(value,f.unit)}</p>}
    {f.comparison&&<p className="value-comparison">{Number(f.comparison.delta)>0?'+':''}{displayValue(f.comparison.delta,f.type==='percentage'?'percentage points':f.unit)}{f.comparison.percent!==null&&` (${Number(f.comparison.percent)>0?'+':''}${f.comparison.percent}%)`}<span> vs previous comparable value</span></p>}
    {f.previous_value!==undefined&&!structured&&<p className="reporting-period">Previous comparable value: <strong>{displayValue(f.previous_value,f.unit)}</strong></p>}
    {f.period&&<p className="reporting-period">Reporting period: <strong>{f.period}</strong></p>}
    {f.error&&<p className="field-warning">{checkError(f.error)}</p>}
    <dl className="field-times"><div><dt>Last checked</dt><dd>{date(f.last_checked_at)}</dd></div><div><dt>Last verified</dt><dd>{date(f.last_verified_at)}</dd></div><div><dt>Last changed</dt><dd>{f.last_changed_at?date(f.last_changed_at):'No change recorded'}</dd></div></dl>
    <div className="widget-footer"><button disabled={!f.capture_id} onClick={()=>f.capture_id&&openCapture(f.capture_id,f)}><ShieldCheck size={14}/>View evidence</button><button disabled={!f.monitor_id} onClick={onHistory}><History size={14}/>View history<ChevronRight size={13}/></button></div>
   </div>}
  </details>
 </article>;
}
function nextCheck(at:number){
 const seconds=at-Date.now()/1000;if(seconds<=0)return 'Due now';
 return seconds<60?'In less than a minute':seconds<3600?`In ${Math.ceil(seconds/60)} min`:`In ${Math.ceil(seconds/3600)} hr`;
}
function frequency(seconds:number){
 for(const [unit,size] of [['day',86400],['hour',3600],['minute',60],['second',1]] as const)if(seconds>=size&&seconds%size===0){const count=seconds/size;return `Every ${count} ${unit}${count===1?'':'s'}`;}
 return `Every ${seconds} seconds`;
}
const EMPTY_DASHBOARD:DashboardData={sources:[],monitors:[],widgets:[],totals:{},attention:[]};
export function Dashboard(shared:Shared){
 const {revision,notify,refresh,navigate,openCapture}=shared;
 const [result,setResult]=useState<DashboardData>(EMPTY_DASHBOARD),[source,setSource]=useState(sessionStorage.getItem('parity-dashboard-source')??''),[loading,setLoading]=useState(true),[error,setError]=useState(''),[busy,setBusy]=useState(''),[wizard,setWizard]=useState<{source?:Source;monitor?:Monitor}|null>(null),[history,setHistory]=useState<MonitorField|null>(null),[cursor,setCursor]=useState(''),[previous,setPrevious]=useState<string[]>([]),[composer,setComposer]=useState<Automation|true|null>(null),[calculation,setCalculation]=useState<string|null>(null);
 const automations=useAutomations(source,revision);
 useEffect(()=>{const removed=(event:Event)=>{if((event as CustomEvent).detail.source_id===source){setSource('');setCursor('');setPrevious([]);}};window.addEventListener('parity-source-removed',removed);return()=>window.removeEventListener('parity-source-removed',removed);},[source]);
 const current=useRef(result),generations=useRef(new Map<string,number>()),sequence=useRef(0);current.current=result;
 useEffect(()=>{
  let cancelled=false;
  const update=(event:Event)=>{
   const row=(event as CustomEvent).detail;
   if(source&&row.source_id&&row.source_id!==source)return;
   const ids=current.current.monitors.filter(m=>row.monitor_id?m.id===row.monitor_id:m.source_id===row.source_id).map(m=>m.id);
   if(!ids.length)return;
   const serial=++sequence.current;ids.forEach(id=>generations.current.set(id,serial));
   const params=new URLSearchParams({});if(source)params.set('source_id',source);ids.forEach(id=>params.append('monitor_ids',id));
   api<DashboardData>(`/api/dashboard/widgets?${params}`).then(next=>{
    if(cancelled)return;
    const applicable=new Set(ids.filter(id=>generations.current.get(id)===serial));
    setError('');setResult(old=>{const monitors=old.monitors.map(m=>applicable.has(m.id)?next.monitors.find(n=>n.id===m.id)??m:m);return {...old,monitors,widgets:monitors.flatMap(m=>m.fields),attention:[...old.attention.filter(a=>!applicable.has(a.monitor_id)),...next.attention.filter(a=>applicable.has(a.monitor_id))],totals:serial===sequence.current?next.totals:old.totals};});
   }).catch(e=>{if(!cancelled)setError(e.message);});
  };
  window.addEventListener('parity-monitor-update',update);return()=>{cancelled=true;window.removeEventListener('parity-monitor-update',update);};
 },[source]);
 useEffect(()=>{sessionStorage.setItem('parity-dashboard-source',source);let stale=false;const params=new URLSearchParams({});if(source)params.set('source_id',source);if(cursor)params.set('cursor',cursor);api<DashboardData>(`/api/dashboard?${params}`).then(r=>{if(!stale){setResult({...EMPTY_DASHBOARD,...r});setError('');}}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[source,revision,cursor]);
 const widgets=(result.widgets?.length?result.widgets:result.monitors.flatMap(m=>m.fields.map(f=>({...f,monitor_id:m.id,source_id:m.source_id,source_name:m.source_name})))).filter(f=>f.enabled!==false);
 const groups=Array.from(new Set(result.monitors.map(m=>m.source_id))).map(id=>{
  const monitors=result.monitors.filter(m=>m.source_id===id),source=result.sources.find(s=>s.id===id)??shared.data.sources.find(s=>s.id===id);
  return {id,source,name:source?.name??monitors[0].source_name??monitors[0].name,monitors,fields:widgets.filter(f=>f.source_id===id),attention:result.attention.filter(a=>monitors.some(m=>m.id===a.monitor_id))};
 }).sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 const check=async(id:string)=>{setBusy(id);try{await post(`/api/sources/${id}/crawl`);notify('Check queued. Values will update when extraction completes.');await refresh();}catch(e){notify((e as Error).message,true);}finally{setBusy('');}};
 const repair=(id:string)=>{const monitor=result.monitors.find(m=>m.id===id);if(monitor)setWizard({monitor,source:result.sources.find(s=>s.id===monitor.source_id)??shared.data.sources.find(s=>s.id===monitor.source_id)});};
 return <div className="screen dashboard-screen"><SectionTitle title="Dashboard" action={<div className="automation-launch"><button className="button" onClick={()=>setComposer(true)}>Create calculation or automation</button><button className="button primary" onClick={()=>setWizard({})}><Plus size={16}/>Start monitoring</button></div>}/>
 <div className="dashboard-toolbar"><label className="inline-field">Source<select aria-label="Dashboard source" value={source} onChange={e=>{setSource(e.target.value);setCursor('');setPrevious([]);}}><option value="">All sources</option>{(shared.data.sources.length?shared.data.sources:result.sources).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><p className="dashboard-counts" aria-label="Monitoring totals">{groups.length} {groups.length===1?'source':'sources'}<span>·</span>{result.totals.fields??widgets.length} tracked fields{Number(result.totals.attention)>0&&<strong>{result.totals.attention} need attention</strong>}</p></div>
 {automations.error&&<ErrorBox>Calculations could not refresh: {automations.error} <button onClick={automations.reload}>Retry</button></ErrorBox>}
 <AutomationDeliveries deliveries={automations.deliveries.filter(d=>!source||automations.items.some(a=>a.id===d.automation_id))}/>
 <AutomationAlerts alerts={automations.alerts.filter(a=>!source||automations.items.some(i=>i.id===a.automation_id))} onEvidence={setCalculation} onChange={automations.reload} notify={notify}/>
 {error&&<ErrorBox>{error} <button onClick={refresh}>Retry</button></ErrorBox>}
 {loading?<Skeleton/>:!result.monitors.length?<div className="panel"><Empty title={source?'No monitors for this source':'Choose the information you want to follow'} action={<button className="button primary" onClick={()=>setWizard({source:result.sources.find(s=>s.id===source)})}><Plus size={16}/>Create a monitor</button>}>Add a website, describe what matters, and review the extracted values before enabling scheduled checks.</Empty></div>:<>
 {(result.next_cursor||previous.length>0)&&<p className="dashboard-page-note">Showing fields on this page. Use Previous or Next below to see more monitored fields.</p>}
 <div className="source-overviews">{groups.map(group=>{
  const {id,source:website,monitors,fields,attention}=group;
  const calculations=automations.items.filter(a=>a.source_ids.length===1&&a.source_ids[0]===id);
  const paused=monitors.every(m=>m.paused),partPaused=!paused&&monitors.some(m=>m.paused);
  const checked=Math.max(...monitors.map(m=>m.last_checked_at??0)),next=Math.min(...monitors.filter(m=>!m.paused&&m.next_check_at).map(m=>m.next_check_at!));
  const issues=Array.from(new Set(attention.map(a=>checkError(a.error||a.status.replaceAll('_',' ')))));
  let domain='';try{domain=new URL(website?.root_url??'').hostname;}catch{/* A source without a valid URL still keeps its saved field overview. */}
  return <section className="source-overview panel" aria-label={`${group.name} source overview`} key={id}>
   <header className="source-overview-heading"><div className="source-overview-title"><h2>{group.name}</h2>{domain&&<span>{domain}</span>}</div><Badge tone={paused?'neutral':attention.length?'amber':'green'}>{paused?'Paused':attention.length?'Needs attention':partPaused?'Partly paused':'Monitoring'}</Badge><div className="source-overview-actions"><button className="button small" disabled={!!busy} onClick={()=>check(id)}>{busy===id?<Spinner/>:<RefreshCw size={13}/>}Check now</button><button className="text-button" onClick={()=>{sessionStorage.setItem('parity-source',id);navigate('sources');window.dispatchEvent(new CustomEvent('parity-source',{detail:id}));}}>Manage source<ChevronRight size={13}/></button></div></header>
   <div className="source-overview-meta"><strong>{fields.length} {(result.next_cursor||previous.length>0)?'fields shown':fields.length===1?'tracked field':'tracked fields'}</strong>{website?.config.interval&&<span>{frequency(Number(website.config.interval))}</span>}<span>Last checked <time title={date(checked)}>{checked?relative(checked):'Not yet'}</time></span><span>Next check <time title={Number.isFinite(next)?date(next):undefined}>{paused?'Paused':Number.isFinite(next)?nextCheck(next):'Scheduled'}</time></span></div>
   {attention.length>0&&<details className="source-attention"><summary><TriangleAlert size={14}/><h3>Needs attention</h3><span>{attention.length} {attention.length===1?'field':'fields'} · {issues.length===1?issues[0]:'Some fields could not be verified. Open for details.'}</span><ChevronRight size={14}/></summary><div>{issues.map(issue=>{const affected=attention.filter(a=>checkError(a.error||a.status.replaceAll('_',' '))===issue);return <div className="attention-row" key={issue}><div><strong>{affected.map(a=>a.name).join(', ')}</strong><p>{issue}</p><p>Previous valid values are retained when a check fails.</p></div><div className="monitor-actions">{Array.from(new Set(affected.filter(a=>a.action==='Repair extraction').map(a=>a.monitor_id))).map(mid=><button className="button small" key={mid} onClick={()=>repair(mid)}>Repair extraction</button>)}</div></div>;})}</div></details>}
   <div className={`source-overview-body ${calculations.length?'with-calculations':''}`}>
    <section className="source-field-section" aria-label={`${group.name} tracked information`}>
     <div className="source-section-heading"><h3>Tracked information</h3></div>
     <div className="source-field-columns" aria-hidden="true"><span>Field</span><span>Value</span><span>Period</span><span/></div>
     <div className="source-fields">{fields.map(f=><FieldOverview key={`${f.monitor_id}:${f.id}`} field={f} openCapture={openCapture} onHistory={()=>setHistory(f)}/>)}</div>
    </section>
    {calculations.length>0&&<section className="source-calculations" aria-label={`${group.name} calculations`}><div className="source-section-heading"><h3>Calculations</h3><Calculator size={14}/></div><AutomationCards items={calculations} shared={shared} onEvidence={setCalculation} onEdit={setComposer}/></section>}
   </div>
   <details className="source-monitor-settings"><summary>Monitoring controls</summary><div>{monitors.map(m=><div className="source-monitor-control" key={m.id}><strong>{m.name}</strong><span>{m.paused?'Paused':'Scheduled checks enabled'}</span><button className="button small" onClick={async()=>{try{await patch(`/api/monitors/${m.id}`,{paused:!m.paused});await refresh();}catch(e){notify((e as Error).message,true);}}}>{m.paused?<Play size={13}/>:<Pause size={13}/>} {m.paused?'Resume monitoring':'Pause monitoring'}</button><button className="button small" onClick={()=>repair(m.id)}><Settings2 size={13}/>Edit tracked fields</button></div>)}</div></details>
  </section>;
 })}</div>
 {(result.next_cursor||previous.length>0)&&<div className="pagination"><span>{result.total??result.totals.monitors} monitors</span><div><button className="button small" disabled={!previous.length} onClick={()=>{setCursor(previous.at(-1)!);setPrevious(p=>p.slice(0,-1));}}>Previous monitors</button><button className="button small" disabled={!result.next_cursor} onClick={()=>{setPrevious(p=>[...p,cursor]);setCursor(result.next_cursor!);}}>Next monitors</button></div></div>}</>}{automations.items.some(a=>a.source_ids.length!==1||!groups.some(g=>g.id===a.source_ids[0]))&&<section className="automation-section"><div className="automation-section-header"><h2>Calculations & automations</h2></div><AutomationCards items={automations.items.filter(a=>a.source_ids.length!==1||!groups.some(g=>g.id===a.source_ids[0]))} shared={shared} onEvidence={setCalculation} onEdit={setComposer}/></section>}{(automations.total>50||automations.hasPrevious)&&<div className="pagination"><span>{automations.total} calculations and automations</span><div><button className="button small" disabled={!automations.hasPrevious} onClick={()=>automations.previous()}>Previous calculations</button><button className="button small" disabled={!automations.nextCursor} onClick={()=>automations.next()}>Next calculations</button></div></div>}{composer&&<AutomationComposer automation={composer===true?undefined:composer} onClose={()=>setComposer(null)} onSaved={async()=>{setComposer(null);automations.reload();notify('Automation saved. Calculation and alert evaluation is queued.');await refresh();}}/>}{calculation&&<CalculationEvidence id={calculation} onClose={()=>setCalculation(null)} openCapture={openCapture}/ >}{wizard&&<MonitorWizard source={wizard.source} monitor={wizard.monitor} onClose={()=>setWizard(null)} onSaved={async()=>{setWizard(null);notify('Monitoring saved. The first check is queued.');await refresh();}}/>}{history&&<FieldHistory field={history} onClose={()=>setHistory(null)} openCapture={openCapture}/>}</div>;
}

export function FieldHistory({field,onClose,openCapture}:{field:MonitorField;onClose:()=>void;openCapture:Shared['openCapture']}){
 const [rows,setRows]=useState<PageResult<Observation>>({items:[],next_cursor:null,total:0}),[cursor,setCursor]=useState(''),[previous,setPrevious]=useState<string[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
 useEffect(()=>{let stale=false;setLoading(true);const q=new URLSearchParams({field_id:field.id,limit:'30'});if(field.page_url)q.set('page_url',field.page_url);if(cursor)q.set('cursor',cursor);api<PageResult<Observation>>(`/api/monitors/${field.monitor_id}/history?${q}`).then(r=>{if(!stale){setRows(r);setError('');}}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[field.id,field.monitor_id,field.page_url,cursor]);
 return <Modal title={`${field.name} — observed history`} onClose={onClose} wide><div className="modal-body"><p className="muted">Observed by Parity at successful checks. Measurements between checks are not available.</p>{error&&<ErrorBox>{error}</ErrorBox>}{loading?<Skeleton/>:<>{rows.items.length?<div className="field-history-list">{rows.items.map(o=><button key={o.id} className="field-history-row" disabled={!o.capture_id} onClick={()=>o.capture_id&&openCapture(o.capture_id,{...field,...o})}><div><strong>{date(o.at)}</strong><small>{o.period?`Reporting period: ${o.period}`:o.kind?.replaceAll('_',' ')??'Observation'}</small></div><div><span>{field.type==='table'||field.type==='list'?o.raw_text?.slice(0,120)||displayValue(o.value):displayValue(o.value,o.unit)}</span>{o.error&&<small className="inline-error">{o.error}</small>}</div><Status value={o.status}/><ChevronRight size={16}/></button>)}</div>:<Empty title="No observations yet">The first completed check will establish a baseline.</Empty>}</>}<div className="pagination"><span>{rows.total} observations</span><div><button className="button small" disabled={!previous.length||loading} onClick={()=>{setCursor(previous.at(-1)!);setPrevious(p=>p.slice(0,-1));}}>Previous</button><button className="button small" disabled={!rows.next_cursor||loading} onClick={()=>{setPrevious(p=>[...p,cursor]);setCursor(rows.next_cursor!);}}>Next</button></div></div></div></Modal>;
}
export function CaptureEvidence({id,field,onClose}:{id:string;field?:MonitorField;onClose:()=>void}){
 const [related,setRelated]=useState<string|null>(null),[capture,setCapture]=useState<Capture|null>(null),[error,setError]=useState('');useEffect(()=>setRelated(null),[id]);const selectedField=related?{...field,...field?.supporting_captures?.find(c=>c.capture_id===related)} as MonitorField:field;useEffect(()=>{let stale=false;setError('');setCapture(null);api<Capture>(`/api/captures/${related??id}`).then(c=>{if(!stale)setCapture(c);}).catch(e=>{if(!stale)setError(e.message);});return()=>{stale=true;};},[id,related]);
 return <Modal title="Stored source evidence" onClose={onClose} wide className="evidence-backdrop"><div className="modal-body">{error?<ErrorBox>{error}</ErrorBox>:!capture?<Skeleton/>:<><div className="capture-heading"><External url={capture.url}>{capture.url}</External><Badge tone="green"><ShieldCheck size={12}/>Stored capture</Badge></div><p className="muted micro">Observed {date(capture.observed_at)} · HTTP {capture.status} · {capture.content_type}</p>{field&&<section className="capture-field"><h3>{field.name}</h3><MonitoredValue field={selectedField??field}/>{Boolean(field.supporting_captures?.length)&&<div className="monitor-actions"><button className="button small" onClick={()=>setRelated(null)}>Current cited capture</button>{field.supporting_captures?.map(c=><button className="button small" key={c.capture_id} onClick={()=>setRelated(c.capture_id)}>Previous operand · {date(c.at)}</button>)}</div>}{field.period&&<p className="reporting-period">Reporting period: {field.period}</p>}<p className="muted micro">Location: {typeof selectedField?.locator==='string'?selectedField.locator:JSON.stringify(selectedField?.locator)}</p></section>}<details className="capture-source" open><summary>Captured page text</summary><pre className="document-content">{capture.text}</pre></details><p className="micro muted">This capture is immutable. Its fingerprint is <code>{capture.sha256}</code>.</p></>}</div></Modal>;
}
