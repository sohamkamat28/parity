import {useEffect,useRef,useState} from 'react';
import {Bell,ChevronRight,History,Pause,Play,Plus,RefreshCw,Search,Settings2,ShieldCheck,TriangleAlert,X} from 'lucide-react';
import type {Shared} from './App';
import type {Automation,Capture,DashboardData,Monitor,MonitorField,Observation,PageResult,Source} from './types';
import {api,date,patch,post,relative} from './api';
import {Badge,Empty,ErrorBox,External,IconButton,Modal,SectionTitle,Skeleton,Spinner,Status} from './ui';
import {MonitorWizard} from './MonitorWizard';
import {AutomationCards,AutomationAlerts,AutomationDeliveries,AutomationComposer,CalculationEvidence,useAutomations} from './Automations';
import {MetricChange,MetricStrip,MetricValue} from './DashboardMetrics';
import './dashboard.css';

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
function FieldOverview({field:f,onOpen}:{field:MonitorField;onOpen:()=>void}){
 const state=fieldState(f),value=f.value??f.preview?.value;
 const structured=f.type==='table'||f.type==='list';
 const summary=f.type==='table'?`${value?.rows?.length??0} rows · ${Math.max(0,(value?.headers?.length??1)-1)} columns`:f.type==='list'?`${Array.isArray(value)?value.length:0} items`:'';
 return <article className={`monitor-widget overview-field ${f.status!=='ok'?'field-unverified':''}`} aria-label={`${f.name} tracked field`}>
  <button className="field-tile" aria-label={`View details for ${f.name}`} onClick={onOpen}>
   <h3 title={f.name}>{f.name.replace(' — latest dated row',' ·')}</h3>
   {structured&&value!=null?<span className="structured-count">{summary}</span>:value!=null&&f.type!=='text'?<MetricValue text={displayValue(value)} unit={f.unit??f.preview?.unit} className="observed-value"/>:<MonitoredValue field={f}/>}
   <MetricChange field={f}/>
   {f.period&&<span className="metric-period">{f.period}</span>}
   {f.status!=='ok'&&<span className="tile-warning">{state.label}</span>}
  </button>
 </article>;
}
function FieldDetails({field:f,onClose,openCapture,onHistory}:{field:MonitorField;onClose:()=>void;openCapture:Shared['openCapture'];onHistory:()=>void}){
 const state=fieldState(f);
 return <Modal title={f.name.replace(' — latest dated row',' ·')} onClose={onClose} wide><div className="modal-body field-detail-body">
  <Badge tone={state.tone}>{state.label}</Badge><MonitoredValue field={f} compact/>
  {f.comparison&&<p className="value-comparison">{Number(f.comparison.delta)>0?'+':''}{displayValue(f.comparison.delta,f.type==='percentage'?'percentage points':f.unit)}{f.comparison.percent!==null&&` (${Number(f.comparison.percent)>0?'+':''}${f.comparison.percent}%)`}<span> vs previous comparable value</span></p>}
  {f.previous_value!==undefined&&!['table','list'].includes(f.type)&&<p className="reporting-period">Previous comparable value: <strong>{displayValue(f.previous_value,f.unit)}</strong></p>}
  {f.period&&<p className="reporting-period">Reporting period: <strong>{f.period}</strong></p>}
  {f.error&&<p className="field-warning">{checkError(f.error)}</p>}
  <dl className="field-times"><div><dt>Last checked</dt><dd>{date(f.last_checked_at)}</dd></div><div><dt>Last verified</dt><dd>{date(f.last_verified_at)}</dd></div><div><dt>Last changed</dt><dd>{f.last_changed_at?date(f.last_changed_at):'No change recorded'}</dd></div></dl>
  <div className="widget-footer"><button disabled={!f.capture_id} onClick={()=>f.capture_id&&openCapture(f.capture_id,f)}><ShieldCheck size={14}/>View evidence</button><button disabled={!f.monitor_id} onClick={onHistory}><History size={14}/>View history<ChevronRight size={13}/></button></div>
 </div></Modal>;
}
function nextCheck(at:number,now=Date.now()/1000){
 if(!Number.isFinite(at))return 'Not scheduled';
 const seconds=at-now;if(seconds<=0)return 'Due now';
 return seconds<60?'In less than a minute':seconds<3600?`In ${Math.ceil(seconds/60)} min`:`In ${Math.ceil(seconds/3600)} hr`;
}
function frequency(seconds:number){
 for(const [unit,size] of [['day',86400],['hour',3600],['minute',60],['second',1]] as const)if(seconds>=size&&seconds%size===0){const count=seconds/size;return `Every ${count} ${unit}${count===1?'':'s'}`;}
 return `Every ${seconds} seconds`;
}
function SourceCheckStatus({monitors,interval}:{monitors:Monitor[];interval:number}){
 const [now,setNow]=useState(()=>Date.now()/1000);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),15000);return()=>clearInterval(timer);},[]);
 const lastChecked=Math.max(0,...monitors.map(m=>m.last_checked_at??0));
 const paused=monitors.every(m=>m.paused);
 const next=Math.min(...monitors.filter(m=>!m.paused&&m.next_check_at).map(m=>m.next_check_at!));
 return <dl className="source-check-status" aria-label="Check schedule">
  <div><dt className="sr-only">Check frequency</dt><dd>{frequency(interval)}</dd></div>
  <div><dt>Last checked</dt><dd>{lastChecked?<time dateTime={new Date(lastChecked*1000).toISOString()} title={date(lastChecked)}>{relative(lastChecked)}</time>:'Not yet checked'}</dd></div>
  <div><dt>Next check</dt><dd>{paused?'Paused':Number.isFinite(next)?<time dateTime={new Date(next*1000).toISOString()} title={date(next)}>{nextCheck(next,now)}</time>:'Not scheduled'}</dd></div>
 </dl>;
}
const EMPTY_DASHBOARD:DashboardData={sources:[],monitors:[],widgets:[],totals:{},attention:[]};
export function Dashboard(shared:Shared){
 const {revision,notify,refresh,navigate,openCapture}=shared;
 const [result,setResult]=useState<DashboardData>(EMPTY_DASHBOARD),[search,setSearch]=useState(''),[query,setQuery]=useState(''),[loading,setLoading]=useState(true),[error,setError]=useState(''),[busy,setBusy]=useState(''),[wizard,setWizard]=useState<{source?:Source;monitor?:Monitor}|null>(null),[history,setHistory]=useState<MonitorField|null>(null),[cursor,setCursor]=useState(''),[previous,setPrevious]=useState<string[]>([]),[composer,setComposer]=useState<Automation|true|null>(null),[calculation,setCalculation]=useState<string|null>(null),[selectedField,setSelectedField]=useState<MonitorField|null>(null),[selectedSource,setSelectedSource]=useState<string|null>(null),[notices,setNotices]=useState(false);
 const automations=useAutomations('',revision,query);
 useEffect(()=>{const timer=setTimeout(()=>{setQuery(search.trim());setCursor('');setPrevious([]);},200);return()=>clearTimeout(timer);},[search]);
 const current=useRef(result),generations=useRef(new Map<string,number>()),sequence=useRef(0);current.current=result;
 useEffect(()=>{
  let cancelled=false;
  const update=(event:Event)=>{
   const row=(event as CustomEvent).detail;
   const ids=current.current.monitors.filter(m=>row.monitor_id?m.id===row.monitor_id:m.source_id===row.source_id).map(m=>m.id);
   if(!ids.length)return;
   const serial=++sequence.current;ids.forEach(id=>generations.current.set(id,serial));
   const params=new URLSearchParams({});if(query)params.set('q',query);ids.forEach(id=>params.append('monitor_ids',id));
   api<DashboardData>(`/api/dashboard/widgets?${params}`).then(next=>{
    if(cancelled)return;
    const applicable=new Set(ids.filter(id=>generations.current.get(id)===serial));
    setError('');setResult(old=>{const monitors=old.monitors.map(m=>applicable.has(m.id)?next.monitors.find(n=>n.id===m.id)??m:m);return {...old,monitors,widgets:monitors.flatMap(m=>m.fields),attention:[...old.attention.filter(a=>!applicable.has(a.monitor_id)),...next.attention.filter(a=>applicable.has(a.monitor_id))],totals:serial===sequence.current?next.totals:old.totals};});
   }).catch(e=>{if(!cancelled)setError(e.message);});
  };
  window.addEventListener('parity-monitor-update',update);return()=>{cancelled=true;window.removeEventListener('parity-monitor-update',update);};
 },[query]);
 useEffect(()=>{let stale=false;const params=new URLSearchParams({});if(query)params.set('q',query);if(cursor)params.set('cursor',cursor);api<DashboardData>(`/api/dashboard?${params}`).then(r=>{if(!stale){setResult({...EMPTY_DASHBOARD,...r});setError('');}}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[query,revision,cursor]);
 const widgets=(result.widgets?.length?result.widgets:result.monitors.flatMap(m=>m.fields.map(f=>({...f,monitor_id:m.id,source_id:m.source_id,source_name:m.source_name})))).filter(f=>f.enabled!==false);
 const groups=Array.from(new Set(result.monitors.map(m=>m.source_id))).map(id=>{
  const monitors=result.monitors.filter(m=>m.source_id===id),source=result.sources.find(s=>s.id===id)??shared.data.sources.find(s=>s.id===id);
  return {id,source,name:source?.name??monitors[0].source_name??monitors[0].name,monitors,fields:widgets.filter(f=>f.source_id===id),attention:result.attention.filter(a=>monitors.some(m=>m.id===a.monitor_id))};
 }).sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 const check=async(id:string)=>{setBusy(id);try{await post(`/api/sources/${id}/crawl`);notify('Check queued. Values will update when extraction completes.');await refresh();}catch(e){notify((e as Error).message,true);}finally{setBusy('');}};
 const repair=(id:string)=>{const monitor=result.monitors.find(m=>m.id===id);if(monitor)setWizard({monitor,source:result.sources.find(s=>s.id===monitor.source_id)??shared.data.sources.find(s=>s.id===monitor.source_id)});};
 const unread=automations.alerts.filter(a=>!a.acknowledged_at).length,deliveryFailures=automations.deliveries.filter(d=>['failed','disabled'].includes(d.status)).length;
 const sourceDetails=groups.find(group=>group.id===selectedSource);
 const fieldDetails=selectedField&&(widgets.find(f=>f.id===selectedField.id&&f.monitor_id===selectedField.monitor_id)??selectedField);
 const crossSource=automations.items.filter(a=>a.source_ids.length!==1||!groups.some(g=>g.id===a.source_ids[0]));
 const manageSource=(id:string)=>{sessionStorage.setItem('parity-source',id);navigate('sources');window.dispatchEvent(new CustomEvent('parity-source',{detail:id}));};
 return <div className="screen dashboard-screen">
  <SectionTitle title="Dashboard" action={<div className="automation-launch"><button className="button" aria-label="Create calculation or automation" onClick={()=>setComposer(true)}>Create calculation</button>{(unread>0||deliveryFailures>0)&&<button className="dashboard-notification" aria-label="Notifications" title="Alerts and delivery issues" onClick={()=>setNotices(true)}><Bell size={18}/><span>{unread+deliveryFailures}</span></button>}<IconButton className="add-source-button" label="Start monitoring" onClick={()=>setWizard({})}><Plus size={22}/></IconButton></div>}/>
  <div className="dashboard-search"><Search size={18}/><input aria-label="Search dashboard" placeholder="Search sources, fields or calculations" maxLength={200} value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<IconButton label="Clear dashboard search" onClick={()=>setSearch('')}><X size={16}/></IconButton>}</div>
  {automations.error&&<ErrorBox>Calculations could not refresh: {automations.error} <button onClick={automations.reload}>Retry</button></ErrorBox>}
  {error&&<ErrorBox>{error} <button onClick={refresh}>Retry</button></ErrorBox>}
  {loading?<Skeleton/>:!result.monitors.length&&!crossSource.length?<div className="panel"><Empty title={query?'No matching sources':'Add your first source'} action={query?<button className="button" onClick={()=>setSearch('')}>Clear search</button>:<button className="button primary" onClick={()=>setWizard({})}><Plus size={16}/>Start monitoring</button>}>{query?'Try another source, field or calculation name.':'Add a website and describe what you want to track.'}</Empty></div>:<>
   <div className="source-overviews">{groups.map(group=>{
    const {id,source:website,monitors,fields,attention}=group,calculations=automations.items.filter(a=>a.source_ids.length===1&&a.source_ids[0]===id);
    const paused=monitors.every(m=>m.paused);
    return <section className="source-overview panel" aria-label={`${group.name} source overview`} key={id}>
     <header className="source-overview-heading"><div className="source-overview-title"><button className="source-name-button" title="Source details and monitoring controls" onClick={()=>setSelectedSource(id)}><h2>{group.name}</h2></button>{website?.root_url&&<External url={website.root_url}>{website.root_url.replace(/^https?:\/\//,'').replace(/\/$/,'')}</External>}</div>{paused&&<Badge>Paused</Badge>}{attention.length>0&&<button className="source-attention-link" onClick={()=>setSelectedSource(id)}><TriangleAlert size={14}/><span>Needs attention</span></button>}<div className="source-check-actions"><SourceCheckStatus monitors={monitors} interval={Number(website?.config.interval??900)}/><IconButton className="source-refresh" label="Check now" disabled={busy===id||paused} onClick={()=>void check(id)}>{busy===id?<Spinner/>:<RefreshCw size={18}/>}</IconButton></div></header>
     <div className={`source-overview-body ${calculations.length?'with-calculations':''}`}>
      <section className="source-field-section" aria-label={`${group.name} tracked information`}><h3 className="source-calculation-title">Tracked information</h3><MetricStrip className="source-fields">{fields.map(f=><FieldOverview key={`${f.monitor_id}:${f.id}`} field={f} onOpen={()=>setSelectedField(f)}/>)}</MetricStrip></section>
      {calculations.length>0&&<section className="source-calculations" aria-label={`${group.name} calculations`}><h3 className="source-calculation-title">Calculations</h3><AutomationCards items={calculations} shared={shared} onEvidence={setCalculation} onEdit={setComposer}/></section>}
     </div>
    </section>;
   })}</div>
   {(result.next_cursor||previous.length>0)&&<div className="pagination"><span>{result.total??result.totals.monitors} monitors</span><div><button className="button small" disabled={!previous.length} onClick={()=>{setCursor(previous.at(-1)!);setPrevious(p=>p.slice(0,-1));}}>Previous monitors</button><button className="button small" disabled={!result.next_cursor} onClick={()=>{setPrevious(p=>[...p,cursor]);setCursor(result.next_cursor!);}}>Next monitors</button></div></div>}
  </>}
  {crossSource.length>0&&<section className="automation-section"><div className="automation-section-header"><h2>Calculations & automations</h2></div><AutomationCards items={crossSource} shared={shared} onEvidence={setCalculation} onEdit={setComposer}/></section>}
  {(automations.total>50||automations.hasPrevious)&&<div className="pagination"><span>{automations.total} calculations and automations</span><div><button className="button small" disabled={!automations.hasPrevious} onClick={()=>automations.previous()}>Previous calculations</button><button className="button small" disabled={!automations.nextCursor} onClick={()=>automations.next()}>Next calculations</button></div></div>}
  {(automations.alerts.length>0||automations.deliveries.length>0)&&<button className="dashboard-notices-link text-button" onClick={()=>setNotices(true)}><Bell size={13}/>Alerts & deliveries</button>}
  {sourceDetails&&<Modal title={sourceDetails.name} onClose={()=>setSelectedSource(null)}><div className="modal-body source-dashboard-details">{sourceDetails.source?.root_url&&<External url={sourceDetails.source.root_url}>{sourceDetails.source.root_url}</External>}<dl className="field-times"><div><dt>Schedule</dt><dd>{frequency(Number(sourceDetails.source?.config.interval??900))}</dd></div><div><dt>Last checked</dt><dd>{date(Math.max(...sourceDetails.monitors.map(m=>m.last_checked_at??0)))}</dd></div><div><dt>Next check</dt><dd>{sourceDetails.monitors.every(m=>m.paused)?'Paused':nextCheck(Math.min(...sourceDetails.monitors.filter(m=>!m.paused&&m.next_check_at).map(m=>m.next_check_at!)))}</dd></div></dl>{sourceDetails.attention.length>0&&<div className="source-attention"><h3>Needs attention</h3>{Array.from(new Set(sourceDetails.attention.map(a=>a.error||a.status))).map(message=><p key={message}>{checkError(message)}</p>)}</div>}<div className="source-monitor-settings">{sourceDetails.monitors.map(m=><div className="source-monitor-control" key={m.id}><strong>{m.name}</strong><div className="monitor-actions"><button className="button small" onClick={async()=>{try{await patch(`/api/monitors/${m.id}`,{paused:!m.paused});await refresh();}catch(e){notify((e as Error).message,true);}}}>{m.paused?<Play size={13}/>:<Pause size={13}/>} {m.paused?'Resume monitoring':'Pause monitoring'}</button><button className="button small" onClick={()=>{setSelectedSource(null);repair(m.id);}}><Settings2 size={13}/>Edit tracked fields</button></div></div>)}</div><button className="button" onClick={()=>manageSource(sourceDetails.id)}>Manage source<ChevronRight size={14}/></button></div></Modal>}
  {fieldDetails&&<FieldDetails field={fieldDetails} onClose={()=>setSelectedField(null)} openCapture={openCapture} onHistory={()=>setHistory(fieldDetails)}/>}
  {notices&&<Modal title="Notifications" onClose={()=>setNotices(false)} wide><div className="modal-body"><AutomationAlerts alerts={automations.alerts} onEvidence={setCalculation} onChange={automations.reload} notify={notify}/><AutomationDeliveries deliveries={automations.deliveries}/>{!automations.alerts.length&&!automations.deliveries.length&&<Empty title="No notifications">Alerts and delivery updates appear here.</Empty>}</div></Modal>}
  {composer&&<AutomationComposer automation={composer===true?undefined:composer} onClose={()=>setComposer(null)} onSaved={async()=>{setComposer(null);setSearch('');automations.reload();notify('Automation saved. Calculation and alert evaluation is queued.');await refresh();}}/>}
  {calculation&&<CalculationEvidence id={calculation} onClose={()=>setCalculation(null)} openCapture={openCapture}/>}
  {wizard&&<MonitorWizard source={wizard.source} monitor={wizard.monitor} onClose={()=>setWizard(null)} onSaved={async()=>{setWizard(null);setSearch('');notify('Monitoring saved. The first check is queued.');await refresh();}}/>}
  {history&&<FieldHistory field={history} onClose={()=>setHistory(null)} openCapture={openCapture}/>}
 </div>;
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
