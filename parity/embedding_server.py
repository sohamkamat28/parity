"""One model process; bounded batches and query-first work queue."""
import itertools
import os
import queue
import secrets
import threading
from concurrent.futures import Future, TimeoutError
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
from .embedding import Embedder

tasks=queue.PriorityQueue(maxsize=128)
sequence=itertools.count()
state={'status':'loading','error':None}
stopping=threading.Event()

def work():
    os.environ['PARITY_EMBEDDER_LOCAL']='1'
    try:
        model=Embedder()
        state.update(status='ready',signature=model.signature)
    except Exception:
        state.update(status='error',error='MiniLM could not load. Run setup.bat and check the model cache.')
        return
    while not stopping.is_set():
        try:_,_,kind,payload,future=tasks.get(timeout=.5)
        except queue.Empty:continue
        if future.cancelled():continue
        try:
            result=({'vectors':model.encode_many(payload.texts),'signature':model.signature}
                    if kind=='embed' else {'parts':model.split(payload.text,payload.prefix)})
            if not future.cancelled():future.set_result(result)
        except Exception as error:
            if not future.cancelled():future.set_exception(error)

@asynccontextmanager
async def lifespan(app):
    stopping.clear();thread=threading.Thread(target=work,daemon=True);thread.start()
    yield
    stopping.set();thread.join(timeout=5)

app=FastAPI(lifespan=lifespan)

@app.middleware('http')
async def guard(request:Request,call_next):
    from fastapi.responses import JSONResponse
    if request.client and request.client.host not in ('127.0.0.1','testclient'):
        return JSONResponse({'detail':'Loopback only'},403)
    if request.url.path!='/health/ready':
        expected=os.getenv('PARITY_EMBEDDING_TOKEN','')
        if not expected or not secrets.compare_digest(expected,request.headers.get('x-parity-token','')):
            return JSONResponse({'detail':'Authentication required'},401)
    return await call_next(request)

@app.get('/health/ready')
def health():
    from fastapi.responses import JSONResponse
    return JSONResponse({**state,'queued':tasks.qsize()},status_code=200 if state['status']=='ready' else 503)

class Batch(BaseModel):
    texts:list[str]=Field(min_length=1,max_length=32)
    priority:str='index'
class Split(BaseModel):
    text:str=Field(max_length=500000)
    prefix:str=Field(max_length=10000)

def submit(kind,payload,priority):
    if state['status']!='ready':raise HTTPException(503,state['error'] or 'Embedding model is loading')
    future=Future()
    try:tasks.put_nowait((priority,next(sequence),kind,payload,future))
    except queue.Full:raise HTTPException(429,'Embedding queue is full; retry shortly')
    try:return future.result(timeout=115)
    except TimeoutError:
        future.cancel();raise HTTPException(504,'Embedding request timed out')
    except ValueError as error:raise HTTPException(400,str(error))

@app.post('/embeddings')
def embed(body:Batch):return submit('embed',body,0 if body.priority=='query' else 10)
@app.post('/split')
def split(body:Split):return submit('split',body,5)
