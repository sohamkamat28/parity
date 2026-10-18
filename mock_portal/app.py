import json, sqlite3, time, os, html, secrets, threading, re
from contextvars import ContextVar
from pathlib import Path
from hashlib import sha256
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from parity import config

app=FastAPI(title="KJSCE demonstration portal")
STATE=config.DATA/"portal.sqlite"
LOCK=threading.Lock()
SESSION=ContextVar('portal_session',default='default')
BASE={"deadline":"20 August 2026 at 5:00 PM","noc":False,"scholarship":True,"added":False,
      "pdf":1,"noise":0,"faults":{},"revision":0,"live":1}

def prefix():
    return '' if SESSION.get()=='default' else '/demo/'+SESSION.get()

@app.middleware('http')
async def session_scope(request,call_next):
    match=re.match(r'^/demo/([a-f0-9]{32})(/.*)$',request.scope['path'])
    token=SESSION.set(match.group(1) if match else 'default')
    if match:
        request.scope['path']=match.group(2)
        request.scope['raw_path']=match.group(2).encode()
    try:return await call_next(request)
    finally:SESSION.reset(token)
def read_state():
    with sqlite3.connect(STATE) as c:
        c.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, value TEXT)")
        row=c.execute("SELECT value FROM sessions WHERE id=?",(SESSION.get(),)).fetchone()
        if row:return json.loads(row[0])
        if SESSION.get()=='default' and c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='state'").fetchone():
            old=c.execute("SELECT value FROM state WHERE id=1").fetchone()
            if old:
                c.execute("INSERT INTO sessions VALUES(?,?)",(SESSION.get(),old[0]))
                return {**BASE,**json.loads(old[0])}
        c.execute("INSERT OR IGNORE INTO sessions VALUES(?,?)",(SESSION.get(),json.dumps(BASE)))
        return dict(BASE)

def mutate(action,payload=None):
    with LOCK:
        state=read_state()
        before=json.dumps(state,sort_keys=True)
        if action=="reset":state=json.loads(json.dumps(BASE))
        elif action=="modify-honours":state.update(deadline="28 August 2026 at 5:00 PM",noc=True)
        elif action=="noise-only":state["noise"]+=1
        elif action=="delete-scholarship":state["scholarship"]=False
        elif action=="restore-scholarship":state["scholarship"]=True
        elif action=="add-notice":state["added"]=True
        elif action=="modify-pdf":state["pdf"]=2
        elif action=="modify-live":state["live"]=2
        elif action=="clear-faults":state["faults"]={}
        elif action=="fault":
            target=(payload or {}).get("target");status=(payload or {}).get("status")
            if target not in ("honours-registration","exam-timetable","scholarship-notice","metrics"):
                raise ValueError("Unknown fixture")
            if status not in (0,403,404,429,503):raise ValueError("Unsupported fault status")
            state["faults"][target]=status
        else:raise ValueError("Unknown action")
        changed=before!=json.dumps(state,sort_keys=True)
        if changed:
            state["revision"]+=1;state["changed_at"]=time.time()
        with sqlite3.connect(STATE) as c:
            c.execute("UPDATE sessions SET value=? WHERE id=?",(json.dumps(state),SESSION.get()))
        return {"changed":changed,"state":state}

def check_admin(request):
    expected=os.environ.get("DEMO_ADMIN_TOKEN","")
    if not expected or not secrets.compare_digest(request.headers.get("x-demo-token",""),expected):
        raise HTTPException(401,"Enter the demo token printed by run.py")
    incoming=request.headers.get("origin")
    if incoming and incoming!=config.DEMO_ORIGIN:raise HTTPException(403,"Origin rejected")

def shell(title,content,noise=0):
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>"""+html.escape(title)+""" · KJSCE Demo</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f2ee;color:#262524;font:16px system-ui,Arial}a{color:#921f32}header{background:#fff;border-top:6px solid #9b2335;padding:26px max(5vw,20px);display:flex;gap:18px;align-items:center}.crest{background:#982439;color:#fff;width:60px;height:66px;display:grid;place-items:center;border-radius:3px 3px 25px 25px;font:bold 28px Georgia}.name{font:bold 24px Georgia}.sub{font-size:12px;letter-spacing:2px;color:#777;margin-top:5px}nav{padding:15px max(5vw,20px);background:#8e2133;display:flex;gap:30px;flex-wrap:wrap}nav a{color:white;text-decoration:none;font-size:14px}.banner{background:#f2dfb8;padding:11px 5vw;font-size:12px;color:#624819}main{max-width:1050px;margin:35px auto;padding:0 25px}article,.panel{background:white;padding:32px;border:1px solid #e4dfd8;border-radius:5px;box-shadow:0 8px 30px #27231c06}h1{font:34px Georgia;margin:0 0 20px}h2{font-size:17px;color:#8e2133;margin-top:28px}p{line-height:1.7}.eyebrow{color:#986b31;font-size:12px;letter-spacing:2px;margin-bottom:13px}.notice{display:flex;gap:22px;padding:24px 0;border-bottom:1px solid #eee}.date{min-width:65px;color:#8e2133;font-size:23px;font-family:Georgia}.notice a{font-weight:600;text-decoration:none}.notice small{display:block;color:#777;margin-top:7px}.pill{display:inline-block;padding:5px 9px;background:#f3e7e9;color:#8e2133;font-size:11px;border-radius:20px}footer{padding:30px 5vw;color:#8a8179;font-size:12px}button{border:0;background:#932638;color:white;padding:13px 17px;border-radius:4px;cursor:pointer;margin:5px}input,select{padding:12px;border:1px solid #ccc;border-radius:4px;width:100%;margin:6px 0 15px}pre{white-space:pre-wrap;font-size:12px}button:hover{background:#681b28}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}
</style></head><body><header><div class="crest">S</div><div><div class="name">K. J. Somaiya School of Engineering</div><div class="sub">ACADEMIC NOTICEBOARD · DEMONSTRATION</div></div></header>
<nav><a href="/en/">Home</a><a href="/en/circulars/">Circulars & notices</a><a href="/en/circulars/exam-timetable">Examinations</a><a href="/en/circulars/honours-registration">Academics</a></nav>
<div class="banner">Unofficial demonstration — synthetic notices, not university guidance. No real applications or payments.</div><main>"""+content+"""</main><footer>Demonstration campus portal <span class="render-timestamp"> · Render revision """+str(noise)+"""</span><div id="cookie-banner">Local demonstration; no tracking cookies.</div></footer></body></html>"""

def response(request,title,body,state):
    raw=shell(title,body,state["noise"]).replace('href="/en/', 'href="'+prefix()+'/en/').encode()
    etag='"'+sha256(raw).hexdigest()+'"'
    if request.headers.get("if-none-match")==etag:return Response(status_code=304,headers={"ETag":etag})
    return HTMLResponse(raw,headers={"ETag":etag,"Cache-Control":"no-cache"})

@app.get("/health/ready")
def health():return {"status":"ready","synthetic":True}

@app.get("/robots.txt")
def robots():return Response("User-agent: *\nAllow: /en/\nDisallow: /admin/\n",media_type="text/plain")

@app.get("/")
def root():return RedirectResponse("/en/circulars/")

@app.get("/en/")
@app.get("/en/circulars/")
def directory(request:Request):
    s=read_state()
    entries=[("honours-registration","B.Tech Honours Degree Registration 2026–27","Academic office"),
             ("exam-timetable","Semester V Examination Timetable","Examination cell")]
    if s["scholarship"]:entries.append(("scholarship-notice","Merit Scholarship Renewal","Student services"))
    if s["added"]:entries.append(("reassessment-supplementary","Supplementary Reassessment Notice","Examination cell"))
    content='<div class="eyebrow">STUDENT RESOURCES / CIRCULARS</div><h1>Announcements & circulars</h1><p>Official-style notices for a controlled Parity demonstration.</p><div class="panel">'
    for i,(slug,title,team) in enumerate(entries):
        content+=f'<div class="notice"><div class="date">0{i+1}<small style="font:12px system-ui;display:block">AUG 2026</small></div><div><span class="pill">{team}</span><p><a href="/en/circulars/{slug}">{title}</a><small>Synthetic fixture · Read notice →</small></p></div></div>'
    if s["added"]:content+='<p><a href="/en/files/reassessment-notice.pdf">Download reassessment PDF</a></p>'
    return response(request,"Circulars",content+"</div>",s)

@app.get("/en/sitemap.xml")
def sitemap(request:Request):
    s=read_state()
    paths=["honours-registration","exam-timetable"]
    if s["scholarship"]:paths+=["scholarship-notice"]
    if s["added"]:paths+=["reassessment-supplementary"]
    urls=[config.DEMO_ORIGIN+prefix()+"/en/circulars/"+x for x in paths]
    if s["added"]:urls+=[config.DEMO_ORIGIN+prefix()+"/en/files/reassessment-notice.pdf"]
    raw=('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
         "".join("<url><loc>"+u+"</loc></url>" for u in urls)+"</urlset>").encode()
    return Response(raw,media_type="application/xml")

@app.get('/en/metrics')
def structured_fixture(request:Request):
    state=read_state();fault=state['faults'].get('metrics',0)
    if fault:return Response('Injected demonstration fault',status_code=fault,headers={'Retry-After':'0'})
    revised=state['noc']
    price='1,250' if revised else '1,200.50'
    revenue='1,400' if revised else '1,200'
    news='<li><a href="/en/circulars/honours-registration">Registration notice</a></li>'
    if state['added']:news+='<li><a href="/en/circulars/reassessment-supplementary">New reassessment notice</a></li>'
    body=f'''<article><h1>Structured monitoring test page</h1><p>Synthetic values for testing; these are not real company results.</p>
    <ul id="metrics"><li><span class="name">Current Price</span> <span class="value">Rs. {price}</span></li>
    <li><span class="name">Promoter holding</span> <span class="value">0%</span></li></ul>
    <h2>Quarterly results</h2><table id="quarterly"><caption>Figures in Rs. Crores</caption>
    <tr><th>Metric</th><th>Mar 2026</th><th>Jun 2026</th></tr>
    <tr><td>Revenue</td><td>1,000</td><td>{revenue}</td></tr></table>
    <h2>Announcements</h2><ul id="news">{news}</ul></article>'''
    return response(request,'Structured monitoring test page',body,state)

@app.get('/en/automatic-price')
def automatic_price_fixture():
    return HTMLResponse('''<!doctype html><html><head><title>Automatic extraction test</title></head>
    <body><main><h1>Synthetic product</h1><div id="quote">Loading…</div></main>
    <script>document.getElementById('quote').innerHTML='<p>Current price: $42.50</p>';</script></body></html>''')

@app.get("/en/circulars/{slug}")
def notice(slug:str,request:Request):
    s=read_state()
    fault=s["faults"].get(slug,0)
    if fault:return Response("Injected demonstration fault",status_code=fault,headers={"Retry-After":"0"})
    if slug=="honours-registration":
        title="B.Tech Honours Degree Registration 2026–27"
        sections=[("Eligibility","Students need a minimum CGPA of 7.50 through Semester IV with no active backlog."),
                  ("Registration Deadline","Registration closes on "+s["deadline"]+"."),
                  ("Registration Fees","Non-refundable demonstration fee: Rs. 2,500."),
                  ("Contact","Contact the demonstration academic office for support.")]
        if s["noc"]:sections.append(("Departmental Approval","A signed NOC from the Head of Department is mandatory before submission."))
    elif slug=="exam-timetable":
        title="Semester V Examination Timetable"
        sections=[("Schedule","Semester V examinations begin on 10 September 2026 at 10:00 AM."),
                  ("Documents","Bring the demonstration hall ticket and student identity card."),
                  ("Reporting","Report 30 minutes before the examination.")]
    elif slug=="scholarship-notice" and s["scholarship"]:
        title="Merit Scholarship Renewal"
        sections=[("Eligibility","Applicants must maintain a minimum CGPA of 8.00."),
                  ("Documents","Submit the previous semester marksheet and renewal application."),
                  ("Deadline","The renewal deadline is 30 August 2026 at 4:00 PM.")]
    elif slug=="reassessment-supplementary" and s["added"]:
        title="Supplementary Reassessment Notice"
        sections=[("Process","Read the linked synthetic PDF for the reassessment window and fee."),
                  ("Attachment",'<a href="/en/files/reassessment-notice.pdf">Reassessment notice PDF</a>')]
    else:raise HTTPException(404,"Demonstration notice unavailable")
    body='<div class="eyebrow">ACADEMIC CIRCULAR / SYNTHETIC FIXTURE</div><article><h1>'+html.escape(title)+'</h1>'
    for heading,text in sections:
        body+="<h2>"+html.escape(heading)+"</h2><p>"+(text if heading=="Attachment" else html.escape(text))+"</p>"
    return response(request,title,body+"</article>",s)

@app.get("/en/files/reassessment-notice.pdf")
def pdf(request:Request):
    s=read_state()
    if not s["added"]:raise HTTPException(404)
    target=config.DATA/("notice-v"+str(s["pdf"])+".pdf")
    if not target.exists():
        import fitz
        doc=fitz.open();page=doc.new_page()
        text="SYNTHETIC DEMONSTRATION NOTICE\nSupplementary Reassessment\n\n"
        text+="Application deadline: "+("4 October 2026" if s["pdf"]==1 else "7 October 2026")+".\n"
        text+="Demonstration fee: Rs. 500.\nNo real payment or application is accepted."
        page.insert_text((60,70),text,fontsize=13)
        doc.set_metadata({"title":"Supplementary Reassessment PDF"})
        doc.save(target);doc.close()
    raw=target.read_bytes();etag='"'+sha256(raw).hexdigest()+'"'
    return Response(status_code=304,headers={"ETag":etag}) if request.headers.get("if-none-match")==etag else Response(raw,media_type="application/pdf",headers={"ETag":etag})

@app.get("/admin/",response_class=HTMLResponse)
def admin():
    content='''<div class="eyebrow">DEMONSTRATION CONTROL ROOM</div><h1>Change the source. Watch Parity follow.</h1>
<div class="grid"><div class="panel"><label for="token">Demo token (printed in your terminal)</label><input id="token" type="password" autocomplete="off">
<div id="buttons"></div></div><div class="panel"><h2>Live fixture state</h2><pre id="state">Enter the token and select an action.</pre></div></div>
<script>
const actions=[['reset','Reset to baseline'],['modify-honours','Extend deadline + add NOC'],['noise-only','Change footer only'],['delete-scholarship','Remove scholarship'],['restore-scholarship','Restore scholarship'],['add-notice','Publish HTML + PDF'],['modify-pdf','Revise PDF'],['clear-faults','Clear faults']];
for(const [action,label] of actions){const b=document.createElement('button');b.textContent=label;b.onclick=()=>act(action);document.getElementById('buttons').append(b)}
async function act(action){const r=await fetch('/admin/'+action,{method:'POST',headers:{'X-Demo-Token':document.getElementById('token').value}});document.getElementById('state').textContent=JSON.stringify(await r.json(),null,2)}
</script>'''
    return shell("Demo controls",content)

@app.get("/admin/state")
def state(request:Request):
    check_admin(request);return read_state()

@app.post("/admin/{action}")
async def control(action:str,request:Request):
    check_admin(request)
    try:
        payload=await request.json() if request.headers.get("content-type","").startswith("application/json") else None
        return mutate(action,payload)
    except ValueError as e:raise HTTPException(400,str(e))

@app.get('/en/live/notice')
@app.get('/en/live/second')
def live_notice(request:Request):
    which='second' if request.scope['path'].endswith('/second') else 'notice'
    body='<div class="eyebrow">BROWSER-RENDERED FIXTURE</div><article id="live-notice" data-which="'+which+'"><h1>Loading live notice</h1><p>Content is delivered by JavaScript.</p></article>'
    body+='<script src="'+prefix()+'/en/live/notice.js"></script>'
    # The shell is deliberately invariant when the backing JSON is edited.
    return response(request,'Live academic notice',body,{'noise':0})

@app.get('/en/live/notice.js')
def live_script():
    code="""const article=document.querySelector('#live-notice');
fetch('./data.json?notice='+article.dataset.which).then(r=>{if(!r.ok)throw new Error('Live data unavailable');return r.json()}).then(d=>{
article.replaceChildren(); const h=document.createElement('h1');h.textContent=d.title;article.append(h);
for(const s of d.sections){const head=document.createElement('h2');head.textContent=s[0];const p=document.createElement('p');p.textContent=s[1];article.append(head,p)}
if(d.link){const a=document.createElement('a');a.href=d.link;a.textContent='Read laboratory access requirements';article.append(a)}
article.dataset.ready='true';
}).catch(e=>{article.textContent=e.message;article.dataset.error='true'});"""
    return Response(code,media_type='application/javascript',headers={'Cache-Control':'no-cache'})

@app.get('/en/live/data.json')
def live_data(notice:str='notice'):
    s=read_state()
    if notice=='second':return {'title':'Laboratory Access Requirements','sections':[['Access','Bring the safety induction certificate and student identity card.']],'link':None}
    deadline='18 November 2026' if s.get('live',1)==1 else '25 November 2026'
    return {'title':'Innovation Lab Applications','sections':[['Application Deadline','Innovation lab applications close on '+deadline+'.'],['Eligibility','Open to students who completed the safety induction workshop.']],'link':prefix()+'/en/live/second'}
