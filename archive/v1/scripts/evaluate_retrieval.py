import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json,time,statistics,os
from pathlib import Path
from parity.service import Service
s=Service()
dataset=json.loads(Path("tests/retrieval_queries.json").read_text())
results=[];reciprocal=[];hits=[];negatives=[]
s.model()
for query,path,heading in dataset:
    start=time.perf_counter();out=s.search(query);elapsed=time.perf_counter()-start
    rank=next((i+1 for i,r in enumerate(out["results"]) if path and path in r["url"] and
               (heading is None or heading==r["heading"])),None)
    if path:
        hits.append(int(rank is not None));reciprocal.append(1/rank if rank else 0)
    else:negatives.append(int(not out["results"]))
    results.append({"query":query,"expected_path":path,"expected_heading":heading,"rank":rank,
        "returned":len(out["results"]),"latency_ms":round(elapsed*1000,2)})
report={"model":s.model().signature,"database":s.db.engine.dialect.name,
        "evaluation_scope":"Development/calibration queries on a controlled synthetic corpus; threshold and stopwords were adjusted using this set. Not held-out or general-web accuracy.",
        "answer_queries":len(hits),"no_answer_queries":len(negatives),
        "recall_at_5":sum(hits)/len(hits),"mrr":sum(reciprocal)/len(reciprocal),
        "no_answer_accuracy":sum(negatives)/len(negatives),
        "median_latency_ms":statistics.median(r["latency_ms"] for r in results),
        "queries":results}
Path("docs/retrieval_evaluation.json").write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!="queries"}))
