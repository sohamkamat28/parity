import asyncio, os, sys, time
from sqlalchemy import select, func
from . import config
from .db import versions, pages

async def test_mcp(service):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    candidate=service.db.one(select(pages.c.id,func.max(versions.c.number).label('number')).join(versions,versions.c.page_id==pages.c.id)
        .group_by(pages.c.id).order_by(func.max(versions.c.number).desc()).limit(1))
    if not candidate:raise ValueError('Index at least one document before running the MCP test.')
    calls=[('search_docs',{'query':'honours registration deadline'}),('get_page',{'page_id':candidate['id'],'version':1}),
           ('get_page_history',{'page_id':candidate['id']}),('diff_versions',{'page_id':candidate['id'],'v1':1,'v2':candidate['number']}),('list_recent_changes',{'limit':5})]
    started=time.perf_counter();results=[]
    env={**os.environ,'PARITY_DATA_DIR':str(config.DATA),'DATABASE_URL':str(service.db.engine.url),'PYTHONPATH':str(config.ROOT),
         'PARITY_OFFLINE':'1','PARITY_MCP_API_URL':f'http://127.0.0.1:{config.API_PORT}'}
    params=StdioServerParameters(command=sys.executable,args=['-m','parity.mcp_server'],cwd=str(config.ROOT),env=env)
    try:
        async with asyncio.timeout(180):
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as client:
                    await client.initialize();listed=await client.list_tools()
                    if {tool.name for tool in listed.tools}!={name for name,_ in calls}:raise ValueError('MCP tool list mismatch')
                    for name,args in calls:
                        tick=time.perf_counter();response=await client.call_tool(name,args)
                        results.append({'name':name,'success':not response.isError,'elapsed_ms':round((time.perf_counter()-tick)*1000)})
        return {'status':'passed' if all(r['success'] for r in results) else 'failed','tools':results,'elapsed_ms':round((time.perf_counter()-started)*1000)}
    except Exception as error:
        return {'status':'failed','tools':results,'error':type(error).__name__+': local MCP process did not complete the protocol test.','elapsed_ms':round((time.perf_counter()-started)*1000)}
