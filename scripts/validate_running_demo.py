import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Run this against run.py. It creates a new demo source only when absent."""
import json,time,os
from pathlib import Path
import httpx
base="http://127.0.0.1:8000"
client=httpx.Client(trust_env=False,timeout=120,headers={"X-Parity-Token":os.environ["PARITY_ADMIN_TOKEN"]})
portal=httpx.Client(base_url="http://127.0.0.1:8080",trust_env=False,headers={"X-Demo-Token":os.environ["DEMO_ADMIN_TOKEN"]})
def mutate(name):
    r=portal.post("/admin/"+name);r.raise_for_status()
def crawl(source):
    r=client.post(base+"/api/sources/"+source+"/crawl",json={});r.raise_for_status();run=r.json()
    for _ in range(120):
        result=client.get(base+"/api/crawl-runs/"+run["id"]).json()
        if result["status"] in ("succeeded","failed","partial"):return result
        time.sleep(1)
    raise TimeoutError("Crawl did not finish")
def search(query):
    r=client.post(base+"/api/search",json={"query":query});r.raise_for_status();return r.json()
mutate("reset")
r=client.post(base+"/api/demo-source",json={});r.raise_for_status();source=r.json()["id"]
baseline=crawl(source)
assert baseline["status"]=="succeeded",baseline
before=search("When is the last date to enrol for honours?")
assert before["embedding_mode"]=="minilm"
assert any("20 August" in x["text"] for x in before["results"]),before
mutate("modify-honours");changed=crawl(source)
assert changed["metrics"]["modified"]==1,changed
after=search("When is the last date to enrol for honours?")
assert any("28 August" in x["text"] for x in after["results"]),after
page_id=next(x["page_id"] for x in after["results"] if "28 August" in x["text"])
diff=client.get(base+f"/api/pages/{page_id}/diff?v1=1&v2=2").json()
assert "NOC" in diff["diff"] and "28 August" in diff["diff"]
mutate("noise-only");noise=crawl(source)
assert noise["metrics"]["new_vectors"]==0,noise
mutate("add-notice");added=crawl(source)
assert added["metrics"]["created"]==2,added
mutate("modify-pdf");pdf=crawl(source)
assert pdf["metrics"]["modified"]==1,pdf
report={"profile":"SQLite + actual MiniLM","source_id":source,"page_id":page_id,
        "baseline":baseline["metrics"],"changed":changed["metrics"],"noise":noise["metrics"],
        "added":added["metrics"],"pdf":pdf["metrics"],
        "semantic_query":"When is the last date to enrol for honours?",
        "before":[{"text":x["text"],"version":x["number"]} for x in before["results"]],
        "after":[{"text":x["text"],"version":x["number"]} for x in after["results"]],
        "diff":diff,"verified_at":time.time()}
Path("docs/semantic_validation.json").write_text(json.dumps(report,indent=2))
print(json.dumps({"semantic_lifecycle":"passed","changed_vectors":changed["metrics"]["new_vectors"],"reused_vectors":changed["metrics"]["reused_vectors"],"page_id":page_id}))
