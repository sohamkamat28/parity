import {Children} from 'react';
import type {ReactNode} from 'react';
import {ArrowDown,ArrowUp,Minus} from 'lucide-react';
import type {MonitorField} from './types';

/** Balance up to five metrics per connected strip without empty placeholder cells. */
export function MetricStrip({children,className=''}:{children:ReactNode;className?:string}){
 const items=Children.toArray(children);
 if(!items.length)return null;
 const columns=Math.ceil(items.length/Math.ceil(items.length/5));
 const strips=[];
 for(let i=0;i<items.length;i+=columns)strips.push(items.slice(i,i+columns));
 return <div className={`metric-strips ${className}`}>{strips.map((strip,index)=><div className="metric-strip" key={index}>{strip}</div>)}</div>;
}

export function MetricValue({text,unit,className}:{text:string;unit?:string;className:string}){
 return <span className={className}><span className="metric-number">{text}</span>{unit&&!text.includes(unit)&&<> <span className="metric-unit">{unit}</span></>}</span>;
}

/** Only the server's comparable observation pair may supply a change badge. */
export function MetricChange({field}:{field:MonitorField}){
 if(field.status!=='ok'||!field.comparison)return null;
 const {delta,percent}=field.comparison;
 const amount=Number(delta);
 if(!Number.isFinite(amount))return null;
 const percentagePoints=field.type==='percentage';
 const text=percentagePoints?`${delta} pp`:percent!==null?`${percent}%`:`${delta}${field.unit?' '+field.unit:''}`;
 const Icon=amount>0?ArrowUp:amount<0?ArrowDown:Minus;
 return <span className="metric-comparison"><span className="metric-change" title={percentagePoints?'Percentage-point difference from the previous comparable value':undefined}><Icon size={12} aria-hidden="true"/>{text}</span><span>vs previous value</span></span>;
}
