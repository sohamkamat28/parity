"""Headless HTTP fixtures for automated regression tests, never launched by Parity."""
import json,time,os,html,secrets,threading
from hashlib import sha256
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,Response,RedirectResponse
from parity import config
app=FastAPI(title='Regression fixture service')
LOCK=threading.Lock()
BASE={"deadline":"20 August 2026 at 5:00 PM","noc":False,"scholarship":True,"added":False,"pdf":1,"noise":0,"faults":{},"revision":0,"live":1}
STATE=json.loads(json.dumps(BASE))
def prefix():return ''
def read_state():return json.loads(json.dumps(STATE))
def mutate(action,payload=None):
    global STATE
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
        STATE=state
        return {"changed":changed,"state":state}

def check_admin(request):
    token=os.environ.get('PARITY_FIXTURE_TOKEN','')
    if not token or not secrets.compare_digest(request.headers.get('x-fixture-token',''),token):raise HTTPException(401,'Fixture token required')
def shell(title,content,noise=0):
    return '<!doctype html><html><head><meta charset="utf-8"><title>'+html.escape(title)+'</title></head><body><main>'+content+'</main><footer><span class="render-timestamp">'+str(noise)+'</span></footer></body></html>'
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
    content='<div class="eyebrow">STUDENT RESOURCES / CIRCULARS</div><h1>Announcements & circulars</h1><p>Official-style notices for a controlled Parity test.</p><div class="panel">'
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
    urls=[os.environ['PARITY_FIXTURE_ORIGIN']+prefix()+"/en/circulars/"+x for x in paths]
    if s["added"]:urls+=[os.environ['PARITY_FIXTURE_ORIGIN']+prefix()+"/en/files/reassessment-notice.pdf"]
    raw=('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
         "".join("<url><loc>"+u+"</loc></url>" for u in urls)+"</urlset>").encode()
    return Response(raw,media_type="application/xml")

@app.get('/en/metrics')
def structured_fixture(request:Request):
    state=read_state();fault=state['faults'].get('metrics',0)
    if fault:return Response('Injected test fault',status_code=fault,headers={'Retry-After':'0'})
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
    if fault:return Response("Injected test fault",status_code=fault,headers={"Retry-After":"0"})
    if slug=="honours-registration":
        title="B.Tech Honours Degree Registration 2026–27"
        sections=[("Eligibility","Students need a minimum CGPA of 7.50 through Semester IV with no active backlog."),
                  ("Registration Deadline","Registration closes on "+s["deadline"]+"."),
                  ("Registration Fees","Non-refundable test fee: Rs. 2,500."),
                  ("Contact","Contact the test academic office for support.")]
        if s["noc"]:sections.append(("Departmental Approval","A signed NOC from the Head of Department is mandatory before submission."))
    elif slug=="exam-timetable":
        title="Semester V Examination Timetable"
        sections=[("Schedule","Semester V examinations begin on 10 September 2026 at 10:00 AM."),
                  ("Documents","Bring the test hall ticket and student identity card."),
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
    else:raise HTTPException(404,"Synthetic notice unavailable")
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
        text="SYNTHETIC TEST NOTICE\nSupplementary Reassessment\n\n"
        text+="Application deadline: "+("4 October 2026" if s["pdf"]==1 else "7 October 2026")+".\n"
        text+="Synthetic fee: Rs. 500.\nNo real payment or application is accepted."
        page.insert_text((60,70),text,fontsize=13)
        doc.set_metadata({"title":"Supplementary Reassessment PDF"})
        doc.save(target);doc.close()
    raw=target.read_bytes();etag='"'+sha256(raw).hexdigest()+'"'
    return Response(status_code=304,headers={"ETag":etag}) if request.headers.get("if-none-match")==etag else Response(raw,media_type="application/pdf",headers={"ETag":etag})

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
    body+='<script src="'+''+'/en/live/notice.js"></script>'
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
    return {'title':'Innovation Lab Applications','sections':[['Application Deadline','Innovation lab applications close on '+deadline+'.'],['Eligibility','Open to students who completed the safety induction workshop.']],'link':''+'/en/live/second'}
