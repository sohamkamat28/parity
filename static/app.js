let data={sources:[],pages:[],runs:[],changes:[]},activePage=null;
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=t=>t?new Date(t*1000).toLocaleString():'Not yet';
const badge=(s)=>'<span class="badge '+esc(s)+'">'+esc(s)+'</span>';
function notice(text,error=false){$('notice').hidden=false;$('notice').textContent=text;$('notice').className=error?'error':''}
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Parity-Token':sessionStorage.getItem('parity-token')||''},body:body===undefined?undefined:JSON.stringify(body)});
 const out=await r.json();if(!r.ok)throw Error(out.detail||r.statusText);return out
}
function show(view){document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!=='view-'+view);document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.view===view));$('breadcrumb').textContent=view.toUpperCase();$('title').textContent=({overview:'Your knowledge, in sync.',sources:'A clear view of your sources.',changes:'The record of what changed.',search:'Ask. Inspect. Verify.',history:'Document history.'})[view]}
function sourceCard(s){
 const docs=data.pages.filter(p=>p.source_id===s.id),run=data.runs.find(r=>r.source_id===s.id);
 return '<div class="source-card"><div class="card-top"><h3>'+esc(s.name)+'</h3>'+badge(!s.enabled?'disabled':s.paused?'manual':'scheduled')+'</div><span class="url">'+esc(s.root_url)+'</span><div class="source-meta"><span>'+docs.length+' documents</span><span>'+esc(run?.status||'Awaiting first crawl')+'</span></div><div class="card-actions"><button class="button primary" data-crawl="'+s.id+'">Run crawl</button><button class="button" data-schedule="'+s.id+'">'+(s.paused?'Enable polling':'Pause polling')+'</button><button class="button ghost" data-enable="'+s.id+'">'+(s.enabled?'Disable':'Enable')+'</button></div></div>'
}
function activity(e){return '<div class="activity">'+badge(e.kind)+'<strong>'+esc(e.title||e.page_id)+'</strong><small>'+date(e.at)+' · '+(e.detail?.new_vectors??0)+' new vectors / '+(e.detail?.reused_vectors??0)+' reused</small><button class="button ghost" data-history="'+e.page_id+'">Inspect history →</button></div>'}
async function refresh(){
 try{data=await api('/api/overview');$('runtime').textContent=data.database+' · '+data.embedding_mode+' retrieval';
 const values=[['Sources',data.sources.length,'Configured monitoring scopes'],['Active documents',data.pages.filter(p=>p.availability==='active').length,'Latest published snapshots'],['Published changes',data.changes.length,'Recent change feed'],['Vectors reused',data.runs.reduce((a,r)=>a+(r.metrics?.reused_vectors||0),0),'Across recent crawl runs']];
 $('stats').innerHTML=values.map(v=>'<div class="stat"><span class="tiny">'+v[0]+'</span><div class="value">'+v[1]+'</div><small>'+v[2]+'</small></div>').join('');
 const cards=data.sources.map(sourceCard).join('')||'<div class="empty">No sources yet. Load the college demo or add a website.</div>';
 $('source-cards').innerHTML=cards;$('all-sources').innerHTML=cards;
 $('recent').innerHTML=data.changes.slice(0,4).map(activity).join('')||'<div class="empty">Changes will appear after your first crawl.</div>';
 $('change-list').innerHTML=data.changes.map(activity).join('')||'<div class="empty">No published changes.</div>';
 $('runs').innerHTML=data.runs.slice(0,5).map(r=>'<div class="activity">'+badge(r.status)+'<strong>'+esc(data.sources.find(s=>s.id===r.source_id)?.name||'Source')+'</strong><small>'+date(r.started_at||r.created_at)+' · '+(r.metrics?.documents||0)+' documents · '+(r.metrics?.failed||0)+' errors</small><small>'+esc(r.error||'')+'</small></div>').join('')||'<div class="empty">Ready for the first run.</div>';
 $('pages').innerHTML=data.pages.map(p=>'<tr><td>'+esc(p.title||p.url)+'<small>'+esc(p.url)+'</small></td><td>'+badge(p.availability)+'</td><td>'+badge(p.health)+'</td><td>'+date(p.verified_at)+'</td><td><button class="button" data-history="'+p.id+'">History</button></td></tr>').join('');
 const selected=$('source-filter').value;$('source-filter').innerHTML='<option value="">All sources</option>'+data.sources.map(s=>'<option value="'+s.id+'">'+esc(s.name)+'</option>').join('');$('source-filter').value=selected;
 }catch(e){notice(e.message,true)}
}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>show(b.dataset.view));
$('connect').onclick=()=>{$('token').value=sessionStorage.getItem('parity-token')||'';$('access').showModal()};
$('save-token').onclick=()=>{sessionStorage.setItem('parity-token',$('token').value);notice('Token saved for this tab.')};
$('add-open').onclick=()=>$('add').showModal();$('add-close').onclick=()=>$('add').close();
$('demo-seed').onclick=async()=>{try{await api('/api/demo-source','POST',{});notice('College source registered. Select Run crawl to index its notices.');refresh()}catch(e){notice(e.message,true)}};
$('source-form').onsubmit=async e=>{e.preventDefault();try{
 const url=$('s-url').value;await api('/api/sources','POST',{name:$('s-name').value,root_url:url,settings:{allow:[$('s-path').value],selector:$('s-selector').value,seeds:[url],discovery_only:$('s-discovery').value.split(',').map(x=>x.trim()).filter(Boolean)}});
 $('add').close();notice('Source registered. Run its first crawl when ready.');refresh()
}catch(e){notice(e.message,true)}};
document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 try{
 if(b.dataset.crawl){b.disabled=true;const r=await api('/api/sources/'+b.dataset.crawl+'/crawl','POST',{});notice('Crawl queued: '+r.id.slice(0,8)+'. The worker will update the results.');refresh()}
 if(b.dataset.schedule){const s=data.sources.find(x=>x.id===b.dataset.schedule);await api('/api/sources/'+s.id,'PATCH',{paused:!s.paused});refresh()}
 if(b.dataset.enable){const s=data.sources.find(x=>x.id===b.dataset.enable);await api('/api/sources/'+s.id,'PATCH',{enabled:!s.enabled});refresh()}
 if(b.dataset.history)await history(b.dataset.history)
 if(b.dataset.version){const r=await api('/api/pages/'+activePage+'?version='+b.dataset.version);$('version-text').textContent=r.version.content}
 }catch(error){notice(error.message,true)}finally{b.disabled=false}
});
$('mode').onchange=()=>{$('date-wrap').hidden=$('mode').value!=='as_of';$('as-of').required=$('mode').value==='as_of'};
$('search-form').onsubmit=async e=>{e.preventDefault();$('results').innerHTML='<div class="empty">Retrieving evidence…</div>';
 try{
 const mode=$('mode').value;const r=await api('/api/search','POST',{query:$('query').value,source_ids:$('source-filter').value?[$('source-filter').value]:null,mode,as_of:mode==='as_of'?new Date($('as-of').value).getTime()/1000:null});
 $('results').innerHTML=r.results.map((x,i)=>'<div class="evidence"><header><div><span class="tiny">EVIDENCE '+(i+1)+' · VERSION '+x.number+'</span><h3>'+esc(x.title)+'</h3></div><button class="button ghost" data-history="'+x.page_id+'">History →</button></header>'+x.warnings.map(w=>'<div class="warning">'+esc(w)+'</div>').join('')+'<div class="body">'+esc(x.text)+'</div><div class="meta"><span>'+esc(x.locator)+'</span><span>Verified '+date(x.last_verified_at)+'</span><span>'+esc(x.score_type)+' '+x.score.toFixed(4)+'</span><a href="'+esc(x.url)+'" target="_blank" rel="noopener">Source ↗</a>'+(x.is_demo?'<span>Synthetic demo</span>':'')+'</div></div>').join('')||'<div class="empty">'+esc(r.message)+'</div>';
 }catch(e){$('results').innerHTML='<div class="empty">'+esc(e.message)+'</div>'}
};
async function history(id){activePage=id;show('history');const [h,p]=await Promise.all([api('/api/pages/'+id+'/versions'),api('/api/pages/'+id)]);
 const opts=h.versions.map(v=>'<option value="'+v.number+'">Version '+v.number+'</option>').join('');
 $('history-content').innerHTML='<div class="history-head"><span class="tiny">VERSIONED DOCUMENT</span><h2>'+esc(p.page.title)+'</h2><p>'+esc(p.page.url)+'</p>'+badge(p.page.availability)+'</div><div class="version-list">'+h.versions.map(v=>'<button class="version-btn" data-version="'+v.number+'"><strong>v'+v.number+'</strong><br><small>'+date(v.indexed_at)+'</small></button>').join('')+'</div><div class="panel"><div class="compare"><div><label>From</label><select id="v1">'+opts+'</select></div><div><label>To</label><select id="v2">'+opts+'</select></div><button class="button primary" id="compare">Compare versions</button></div><pre class="content" id="version-text">'+esc(p.version?.content||'Currently unavailable. Select a historical version to read its archived content.')+'</pre></div><div class="section-head"><h2>Availability timeline</h2></div><div class="panel">'+h.intervals.map(i=>'<div class="activity">'+date(i.start)+' → '+(i.end?date(i.end):'Open interval')+'</div>').join('')+'</div>';
 if(h.versions.length)$('v2').value=h.versions[h.versions.length-1].number;
 $('compare').onclick=async()=>{try{const d=await api('/api/pages/'+id+'/diff?v1='+$('v1').value+'&v2='+$('v2').value);$('version-text').innerHTML=d.diff.split('\n').map(l=>'<span class="'+(l.startsWith('+')?'diff-add':l.startsWith('-')?'diff-del':'')+'">'+esc(l)+'</span>').join('\n')||'No text differences.'}catch(e){notice(e.message,true)}}
}
$('history-back').onclick=()=>show('sources');
refresh();setInterval(refresh,4000);
