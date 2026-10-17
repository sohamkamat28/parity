import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio,json,os,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    report=json.loads(Path("docs/semantic_validation.json").read_text())
    params=StdioServerParameters(command=sys.executable,args=["-m","parity.mcp_server"],env=os.environ.copy())
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            listed=await session.list_tools()
            names=sorted(x.name for x in listed.tools)
            assert names==sorted(["search_docs","get_page","get_page_history","diff_versions","list_recent_changes"]),names
            calls=[
              ("search_docs",{"query":"When does honours registration close?"}),
              ("get_page",{"page_id":report["page_id"],"version":1}),
              ("get_page_history",{"page_id":report["page_id"]}),
              ("diff_versions",{"page_id":report["page_id"],"v1":1,"v2":2}),
              ("list_recent_changes",{"limit":10})]
            results=[]
            for name,args in calls:
                response=await session.call_tool(name,args)
                assert not response.isError,(name,response)
                results.append({"tool":name,"success":True})
    Path("docs/mcp_validation.json").write_text(json.dumps({"tools":names,"calls":results,"verified_at":time.time()},indent=2))
    print("MCP protocol: initialized, listed and successfully called all five tools.")

if __name__=="__main__":asyncio.run(main())
