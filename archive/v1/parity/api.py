import os, time, secrets, threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from .service import Service
from .chat import ChatService
from .operations import DemoService, overview, list_changes, run_observations
from . import config

service=Service();chat=ChatService(service);demo=DemoService(service)
stop=threading.Event()
runtime_state={'embedding':{'status':'loading','mode':config.EMBEDDER,'error':None},'worker':{'status':'starting','error':None}}
session_cookie=secrets.token_urlsafe(32)
bootstrap_used=False
auth_lock=threading.Lock()

def worker():
    while not stop.is_set():
        try:
            if service.embedder is None:
                runtime_state['embedding'].update(status='loading',error=None)
                service.model()
            runtime_state['embedding'].update(status='ready',mode=service.model().mode,error=None)
            runtime_state['worker'].update(status='ready',error=None)
            service.worker_once()
        except Exception as error:
            runtime_state['worker'].update(status='error',error=str(error)[:300])
            if service.embedder is None:runtime_state['embedding'].update(status='error',error='Model could not load. Run setup.bat or check the model cache.')
            stop.wait(10)
        stop.wait(1)

@asynccontextmanager
async def lifespan(app):
    stop.clear();thread=threading.Thread(target=worker,daemon=True);thread.start()
    yield
    stop.set();thread.join(timeout=5)

app=FastAPI(title='Parity',version='1.0.0-demo',lifespan=lifespan)

@app.middleware('http')
async def local_guard(request:Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):return JSONResponse({'detail':'Host rejected'},status_code=403)
    if request.method in ('POST','PATCH','DELETE','PUT'):
        origin=request.headers.get('origin')
        if origin and origin not in (f'http://127.0.0.1:{config.API_PORT}',f'http://localhost:{config.API_PORT}'):
            return JSONResponse({'detail':'Origin rejected'},status_code=403)
        if request.url.path!='/api/session':
            expected=os.getenv('PARITY_ADMIN_TOKEN','');header=request.headers.get('x-parity-token','');cookie=request.cookies.get('parity-session','')
            valid=(bool(expected) and secrets.compare_digest(header,expected)) or secrets.compare_digest(cookie,session_cookie)
            if not valid:return JSONResponse({'detail':'Connect using the local token or the launcher connection link.'},status_code=401)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
    return response

@app.exception_handler(ValueError)
async def value_error(request,error):return JSONResponse({'detail':str(error)},status_code=getattr(error,'status_code',400))

class SessionIn(BaseModel):token:str=Field(min_length=1,max_length=500)
class SourceIn(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    root_url:str
    settings:dict=Field(default_factory=dict)
class SourceUpdate(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=100)
    settings:dict|None=None
    enabled:bool|None=None
    paused:bool|None=None
class SearchIn(BaseModel):
    query:str=Field(min_length=1,max_length=2000)
    source_ids:list[str]|None=None
    limit:int=Field(default=5,ge=1,le=20)
    mode:str='current'
    as_of:float|None=None
    include_unavailable:bool=False
class ChatIn(BaseModel):
    message:str=Field(min_length=1,max_length=4000)
    conversation_id:str|None=None
    source_ids:list[str]|None=None
    mode:str='current'
    as_of:float|None=None
class DemoIn(BaseModel):name:str|None=Field(default=None,max_length=100)
class ActionIn(BaseModel):
    crawl:bool=True
    target:str|None=None
    status:int|None=None

@app.post('/api/session')
def connect(body:SessionIn):
    global bootstrap_used
    admin=os.getenv('PARITY_ADMIN_TOKEN','');bootstrap=os.getenv('PARITY_BOOTSTRAP_TOKEN','')
    with auth_lock:
        admin_ok=bool(admin) and secrets.compare_digest(body.token,admin)
        bootstrap_ok=bool(bootstrap) and not bootstrap_used and secrets.compare_digest(body.token,bootstrap)
        if not (admin_ok or bootstrap_ok):raise HTTPException(401,'The local connection token is invalid or expired. Use the token printed by the current launcher.')
        if bootstrap_ok:bootstrap_used=True
    response=JSONResponse({'status':'connected'})
    response.set_cookie('parity-session',session_cookie,httponly=True,samesite='strict',max_age=86400)
    return response

@app.get('/health/live')
def live():return {'status':'alive'}
@app.get('/health/ready')
def ready():
    good=runtime_state['embedding']['status']=='ready'
    return JSONResponse({'status':'ready' if good else runtime_state['embedding']['status'],'database':service.db.engine.dialect.name,'embedding_mode':config.EMBEDDER},status_code=200 if good else 503)
@app.get('/api/runtime')
def runtime():
    from .browser import browser_status
    return {'database':{'status':'ready','engine':service.db.engine.dialect.name},**runtime_state,'browser':browser_status(),'chat':chat.status()}
@app.get('/api/overview')
def get_overview():return overview(service)
@app.get('/api/sources')
def sources():return service.overview()['sources']
@app.post('/api/sources')
def add_source(body:SourceIn):return service.add_source(body.name,body.root_url,body.settings)
@app.post('/api/sources/test')
def test_source(body:SourceIn):return service.test_source(body.name,body.root_url,body.settings)
@app.patch('/api/sources/{source_id}')
def update_source(source_id:str,body:SourceUpdate):return service.update_source(source_id,**body.model_dump())
@app.post('/api/demo-source')
def old_demo():return service.seed_demo()
@app.post('/api/sources/{source_id}/crawl')
def crawl(source_id:str):return service.enqueue(source_id)
@app.get('/api/crawl-runs/{run_id}')
def run_status(run_id:str):
    from .db import runs
    result=service.db.one(select(runs).where(runs.c.id==run_id))
    if not result:raise HTTPException(404,'Crawl run not found')
    return result
@app.get('/api/crawl-runs/{run_id}/observations')
def observations(run_id:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):return run_observations(service,run_id,offset,limit)
@app.post('/api/search')
def search(body:SearchIn):return service.search(**body.model_dump())
@app.get('/api/pages/{page_id}')
def page(page_id:str,version:int|None=None):return service.get_page(page_id,version)
@app.get('/api/pages/{page_id}/versions')
def history(page_id:str):return service.history(page_id)
@app.get('/api/pages/{page_id}/diff')
def diff(page_id:str,v1:int,v2:int):return service.diff(page_id,v1,v2)
@app.get('/api/changes')
def changes(source_id:str|None=None,kind:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=500)):return list_changes(service,source_id,kind,offset,limit)
@app.post('/api/chat')
def ask(body:ChatIn):return chat.ask(**body.model_dump())
@app.post('/api/chat/test')
def chat_test():return chat.test_connection()
@app.get('/api/chat/conversations')
def conversations():return chat.conversations()
@app.get('/api/chat/conversations/{conversation_id}')
def conversation(conversation_id:str):return chat.conversation(conversation_id)
@app.get('/api/demo/sessions')
def demo_list():return demo.sessions()
@app.post('/api/demo/sessions')
def demo_create(body:DemoIn):return demo.create(body.name)
@app.get('/api/demo/sessions/{session_id}')
def demo_get(session_id:str):return demo.get(session_id)
@app.post('/api/demo/sessions/{session_id}/actions/{action}')
def demo_action(session_id:str,action:str,body:ActionIn):return demo.action(session_id,action,body.crawl,body.model_dump(exclude_none=True))
@app.post('/api/integrations/mcp/test')
async def mcp_test():
    from .integrations import test_mcp
    return await test_mcp(service)

bundle=config.ROOT/'frontend'/'dist'
if (bundle/'assets').is_dir():app.mount('/assets',StaticFiles(directory=bundle/'assets'),name='assets')
app.mount('/static',StaticFiles(directory=config.ROOT/'static'),name='legacy-static')
@app.get('/')
def home():return FileResponse(bundle/'index.html' if (bundle/'index.html').is_file() else config.ROOT/'static'/'index.html')
