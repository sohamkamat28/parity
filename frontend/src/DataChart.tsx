import {useEffect,useRef,useState} from 'react';
import type {Shared} from './App';
import type {MonitorField,Observation} from './types';
import {api,date} from './api';

type Point=Observation&{number:number|null;revision_id:string;break_before:boolean};
export type Series={monitor_id:string;field_id:string;points:Point[];total:number;sampled:boolean};
const key=(m:string,f:string)=>`${m}:${f}`;
export function useDashboardSeries(fields:MonitorField[],days:number,revision:number){
 const [series,setSeries]=useState<Record<string,Series>>({}),[error,setError]=useState('');
 const latest=useRef(fields),scope=useRef('');latest.current=fields;
 const identities=fields.map(f=>key(f.monitor_id!,f.id)).sort().join('|');
 useEffect(()=>{
  const controller=new AbortController(),generations=new Map<string,number>();let serial=0;
  const nextScope=`${identities}@${days}`;if(scope.current!==nextScope){setSeries({});scope.current=nextScope;}setError('');
  const load=async(chosen:MonitorField[])=>{
   if(!chosen.length)return;const request=++serial;
   chosen.forEach(f=>generations.set(key(f.monitor_id!,f.id),request));
   const end=Date.now()/1000;
   try{
    const batches=[];
    for(let i=0;i<chosen.length;i+=50){const params=new URLSearchParams({start:String(end-days*86400),end:String(end)});chosen.slice(i,i+50).forEach(f=>params.append('fields',JSON.stringify({monitor_id:f.monitor_id,field_id:f.id})));batches.push(api<{items:Series[]}>(`/api/dashboard/series?${params}`,{signal:controller.signal}));}
    const results=await Promise.all(batches);if(controller.signal.aborted)return;
    setError('');setSeries(old=>{const next={...old};for(const result of results)for(const item of result.items){const id=key(item.monitor_id,item.field_id);if(generations.get(id)===request)next[id]=item;}return next;});
   }catch(e){if(!controller.signal.aborted)setError((e as Error).message);}
  };
  void load(latest.current);
  const update=(event:Event)=>{const row=(event as CustomEvent).detail;void load(latest.current.filter(f=>row.monitor_id?f.monitor_id===row.monitor_id:f.source_id===row.source_id));};
  window.addEventListener('parity-monitor-update',update);
  return()=>{controller.abort();window.removeEventListener('parity-monitor-update',update);};
 },[identities,days,revision]);
 return {series,error};
}
export function DataChart({field,series,openCapture,compact=false}:{field:MonitorField;series?:Series;openCapture:Shared['openCapture'];compact?:boolean}){
 const [active,setActive]=useState<Point|null>(null),[width,setWidth]=useState(510);const chart=useRef<HTMLDivElement>(null);
 useEffect(()=>{if(!chart.current)return;const observer=new ResizeObserver(entries=>setWidth(Math.max(280,Math.round(entries[0].contentRect.width))));observer.observe(chart.current);return()=>observer.disconnect();},[series?.points.length]);
 const points=series?.points??[],valid=points.filter(p=>p.number!==null);
 const show=(p:Point)=>p.capture_id&&openCapture(p.capture_id,{...field,value:p.value,unit:p.unit,period:p.period});
 if(!series)return <div className={`chart-empty ${compact?'compact-chart-empty':''}`} role="status">Loading observations…</div>;
 if(!valid.length)return <div className={`chart-empty ${compact?'compact-chart-empty':''}`}>No numeric observations collected in this range.</div>;
 const values=valid.map(p=>p.number!),low=Math.min(...values),high=Math.max(...values),pad=high===low?Math.max(Math.abs(high)*.05,1):(high-low)*.12;
 const min=low-pad,max=high+pad,start=points[0].at,end=points.at(-1)!.at;
 const left=compact?10:54,right=compact?10:26,height=compact?40:184;
 const x=(p:Point)=>end===start?(width+left-right)/2:left+(p.at-start)/(end-start)*(width-left-right),y=(n:number)=>compact?32-(n-min)/(max-min)*24:146-(n-min)/(max-min)*116;
 let path='',last:Point|null=null;
 for(const p of points){if(p.number===null){last=null;continue;}path+=`${!last||p.break_before?'M':'L'}${x(p)},${y(p.number)} `;last=p;}
 const format=(n:number)=>n.toLocaleString(undefined,{maximumFractionDigits:4,notation:Math.abs(n)>=1e7?'compact':'standard'});
 return <div className={`data-chart ${compact?'compact-chart':''}`} ref={chart}><svg viewBox={`0 0 ${width} ${height}`} aria-label={`${field.name}: ${valid.length} plotted observations`}>
  {!compact&&[low,(low+high)/2,high].filter((n,i,a)=>a.indexOf(n)===i).map(n=><g key={n}><line x1="54" x2={width-26} y1={y(n)} y2={y(n)} className="chart-grid"/><text x="47" y={y(n)+4} textAnchor="end" className="chart-label">{format(n)}</text></g>)}
  {min<0&&max>0&&<line x1={left} x2={width-right} y1={y(0)} y2={y(0)} className="chart-zero"/>}
  <path d={path} className="chart-line"/>
  {valid.map(p=><g key={p.id} role="button" tabIndex={0} aria-label={`${date(p.at)}: ${p.value} ${p.unit??''}${p.period?`, ${p.period}`:''}. Open evidence.`} onClick={()=>show(p)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(p);}}} onMouseEnter={()=>setActive(p)} onMouseLeave={()=>setActive(null)} onFocus={()=>setActive(p)} onBlur={()=>setActive(null)} className={`chart-point ${valid.length===1?'single-point':''}`}>
   <title>{date(p.at)} · {p.value} {p.unit} {p.period}</title><circle cx={x(p)} cy={y(p.number!)} r="9" className="chart-hit"/><circle cx={x(p)} cy={y(p.number!)} r="3.5" className="chart-dot"/>
  </g>)}
  {!compact&&<><text x="54" y="176" className="chart-label">{new Date(start*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'})}</text><text x={width-26} y="176" textAnchor="end" className="chart-label">{end===start?'Baseline':new Date(end*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'})}</text></>}
 </svg><p className="chart-caption" aria-live="polite">{active?`${date(active.at)} · ${active.value} ${active.unit??''}${active.period?' · '+active.period:''}`:valid.length===1?(compact?'Baseline · one observation':'Baseline collected. The next successful check adds a point.'):`${series.total.toLocaleString()} observations${series.sampled?' · sampled to retain endpoints and extrema':''}${compact?'':' · select a point for evidence'}`}</p>
 {!compact&&<details className="chart-data"><summary>Observation data</summary><div className="monitor-table-scroll" tabIndex={0}><table className="monitor-table"><caption>{field.name} — plotted observations. Gaps and different periods or rule revisions are not connected.</caption><thead><tr><th scope="col">Observed</th><th scope="col">Value</th><th scope="col">Period</th><th scope="col">Evidence</th></tr></thead><tbody>{points.map(p=><tr key={p.id}><th scope="row">{date(p.at)}</th><td>{p.number===null?p.error||p.status:`${p.value} ${p.unit??''}`}</td><td>{p.period||'—'}</td><td><button className="text-button" disabled={!p.capture_id} onClick={()=>show(p)}>Open capture</button></td></tr>)}</tbody></table></div></details>}</div>;
}
