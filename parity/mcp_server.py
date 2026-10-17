import sys,os
from mcp.server.fastmcp import FastMCP
from .service import Service
from .db import events
from sqlalchemy import select

mcp=FastMCP("Parity — versioned website evidence")
bridge=os.getenv('PARITY_MCP_API_URL','').rstrip('/')
if bridge:
    from urllib.parse import urlsplit
    p=urlsplit(bridge)
    if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost') or p.path:
        raise ValueError('MCP API bridge must use a loopback HTTP origin')
service=None if bridge else Service()

def request(method,path,body=None):
    import httpx
    with httpx.Client(trust_env=False,timeout=60) as client:
        response=client.request(method,bridge+path,json=body,headers={'X-Parity-Token':os.getenv('PARITY_ADMIN_TOKEN','')})
        response.raise_for_status();return response.json()

@mcp.tool()
def search_docs(query:str,source_ids:list[str]|None=None,limit:int=5,mode:str="current",as_of:float|None=None)->dict:
    """Retrieve current or indexed-time historical evidence, including citations and freshness."""
    if bridge:return request('POST','/api/search',{'query':query,'source_ids':source_ids,'limit':limit,'mode':mode,'as_of':as_of})
    return service.search(query,source_ids,limit,mode,as_of)

@mcp.tool()
def get_page(page_id:str,version:int|None=None)->dict:
    """Read a published page or an explicit historical version."""
    result=request('GET','/api/pages/'+page_id+(('?version='+str(version)) if version else '')) if bridge else service.get_page(page_id,version)
    if result.get("version") and len(result["version"]["content"])>20000:
        result["version"]["content"]=result["version"]["content"][:20000]
        result["truncated"]=True
    return result

@mcp.tool()
def get_page_history(page_id:str)->dict:
    """List version and availability history for one page."""
    result=request('GET','/api/pages/'+page_id+'/versions') if bridge else service.history(page_id)
    for key in result:result[key]=result[key][-100:]
    return result

@mcp.tool()
def diff_versions(page_id:str,v1:int,v2:int)->dict:
    """Return the exact text difference between two versions of the same page."""
    result=request('GET',f'/api/pages/{page_id}/diff?v1={v1}&v2={v2}') if bridge else service.diff(page_id,v1,v2)
    if len(result["diff"])>20000:
        result["diff"]=result["diff"][:20000];result["truncated"]=True
    return result

@mcp.tool()
def list_recent_changes(limit:int=20)->list[dict]:
    """List recent published changes; limit 1 to 100."""
    if not 1<=limit<=100:raise ValueError("Limit must be 1–100")
    if bridge:return request('GET','/api/changes?limit='+str(limit))
    return service.db.all(select(events).order_by(events.c.at.desc()).limit(limit))

if __name__=="__main__":
    mcp.run(transport="stdio")
