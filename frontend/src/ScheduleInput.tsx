import {useState} from 'react';
const UNITS=[{label:'seconds',seconds:1},{label:'minutes',seconds:60},{label:'hours',seconds:3600},{label:'days',seconds:86400}];
export function ScheduleInput({seconds,onChange,disabled=false}:{seconds:number;onChange:(seconds:number)=>void;disabled?:boolean}){
 const [unit,setUnit]=useState(()=>[86400,3600,60].find(n=>seconds%n===0)??1);
 const valid=Number.isFinite(seconds)&&seconds>=10&&seconds<=604800;
 return <fieldset className="schedule-input"><legend>Check every</legend><div><input aria-label="Check frequency" type="number" min={10/unit} max={604800/unit} step="any" value={Number.isFinite(seconds)?+(seconds/unit).toFixed(6):''} disabled={disabled} aria-invalid={!valid} onChange={e=>onChange(e.target.value===''?NaN:Number(e.target.value)*unit)}/><select aria-label="Check frequency unit" value={unit} disabled={disabled} onChange={e=>{const next=Number(e.target.value);onChange(seconds/unit*next);setUnit(next);}}>{UNITS.map(u=><option key={u.seconds} value={u.seconds}>{u.label}</option>)}</select></div><small>{valid?'An immediate baseline runs first. Scheduled checks run while Parity is running.':'Enter a frequency between 10 seconds and 7 days.'}</small></fieldset>;
}
