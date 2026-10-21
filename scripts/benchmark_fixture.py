import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json, tempfile, threading, time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from parity import config
from parity.service import Service
from parity.db import DB
from parity.fetch import Fetcher
from parity.embedding import Embedder

class Site(BaseHTTPRequestHandler):
    revision=1
    def do_GET(self):
        if self.path=="/docs/":
            body='<main><h1>Operations manual</h1><p>'+''.join(f'<a href="/docs/{i}">Section {i}</a> ' for i in range(50))+'</p></main>'
        elif self.path.startswith("/docs/") and self.path[6:].isdigit():
            i=int(self.path[6:])
            amount=200 if i==0 and Site.revision==2 else 100
            body=f'<article><h1>Service {i}</h1><h2>Rate limit</h2><p>Service {i} supports {amount} requests per minute.</p><h2>Access</h2><p>Send an authorization token when connecting to service {i}.</p></article>'
        else:self.send_error(404);return
        self.send_response(200);self.send_header("Content-Type","text/html");self.end_headers();self.wfile.write(body.encode())
    def log_message(self,*args):pass

server=ThreadingHTTPServer(("127.0.0.1",0),Site)
threading.Thread(target=server.serve_forever,daemon=True).start()
origin=f"http://127.0.0.1:{server.server_port}"
try:
    with tempfile.TemporaryDirectory() as tmp:
        config.DATA=Path(tmp)
        model=Embedder("minilm")
        service=Service(DB("sqlite:///"+tmp+"/bench.db"),model,Fetcher(origin))
        source=service.add_source("Synthetic 50-page docs",origin+"/docs/",
            {"allow":["/docs/"],"discovery_only":["/docs/"],"delay":0})
        def run():
            start=time.perf_counter();r=service.run(service.enqueue(source["id"])["id"])
            return {"seconds":time.perf_counter()-start,"metrics":r["metrics"],"status":r["status"]}
        baseline=run();unchanged=run();Site.revision=2;modified=run()
        assert baseline["metrics"]["created"]==50 and baseline["metrics"]["new_vectors"]==100,baseline
        assert unchanged["metrics"]["new_vectors"]==0,unchanged
        assert modified["metrics"]["modified"]==1 and modified["metrics"]["new_vectors"]==1,modified
        result={"scope":"One controlled 50-page website; real HTTP + SQLite + MiniLM; single trial, not a production-scale claim",
                "baseline":baseline,"unchanged":unchanged,"one_section_edit":modified,
                "new_vectors_after_edit":1,"full_reembed_vectors_for_same_corpus":100,
                "vector_work_avoided_vs_full_reembedding":0.99,
                "note":"The 100-vector comparison uses the measured cold baseline count. A separate full re-index timing was not measured."}
        Path("docs/scale_smoke_test.json").write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
finally:server.shutdown();server.server_close()
