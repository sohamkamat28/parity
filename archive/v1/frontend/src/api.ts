export async function api<T=any>(path:string,options:RequestInit={}):Promise<T>{
  const token=sessionStorage.getItem('parity-token');
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(token?{'X-Parity-Token':token}:{}),...options.headers},credentials:'same-origin'});
  const data=await response.json().catch(()=>({detail:`HTTP ${response.status}`}));
  if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('parity-auth'));throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??data));}
  return data;
}
export const post=<T=any>(path:string,body:unknown={})=>api<T>(path,{method:'POST',body:JSON.stringify(body)});
export const patch=<T=any>(path:string,body:unknown)=>api<T>(path,{method:'PATCH',body:JSON.stringify(body)});
export function date(n?:number){return n?new Date(n*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Not yet verified';}
export function relative(n?:number){if(!n)return 'Never';const s=Math.max(0,Date.now()/1000-n);return s<60?'Just now':s<3600?`${Math.floor(s/60)}m ago`:s<86400?`${Math.floor(s/3600)}h ago`:`${Math.floor(s/86400)}d ago`;}
export function domain(url:string){try{return new URL(url).host;}catch{return url;}}
export function count(n?:number){return (n??0).toLocaleString();}
export function uid(){return crypto.randomUUID();}
