import os, sys, time, socket, subprocess, json
from pathlib import Path
import pytest, httpx
from sqlalchemy import select
from parity import config
from parity.service import Service
from parity.db import DB, pages, versions, cache, runs, sources, intervals
from parity.embedding import Embedder
from parity.fetch import canonical, Fetcher, FetchError
from parity.extract import extract

@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    root=tmp_path_factory.mktemp("portal")
    sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1];sock.close()
    base=f"http://127.0.0.1:{port}"
    env=os.environ.copy()
    env.update(PARITY_DATA_DIR=str(root),PARITY_FIXTURE_ORIGIN=base,PARITY_FIXTURE_TOKEN="test-fixture-only")
    proc=subprocess.Popen([sys.executable,"-m","uvicorn","tests.support.fixture_site:app","--host","127.0.0.1","--port",str(port)],
        env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    client=httpx.Client(base_url=base,trust_env=False,timeout=15)
    for _ in range(100):
        try:
            if client.get("/health/ready").status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(.1)
    else:
        proc.terminate();raise RuntimeError("Portal startup failed")
    yield base,client
    client.close();proc.terminate();proc.wait(timeout=5)

@pytest.fixture
def system(tmp_path,monkeypatch,portal):
    base,client=portal

    monkeypatch.setattr(config,"DATA",tmp_path)
    client.post("/admin/reset",headers={"X-Fixture-Token":"test-fixture-only"}).raise_for_status()
    s=Service(DB("sqlite:///"+str(tmp_path/"test.db")),Embedder("lexical"),Fetcher(base))
    source=s.add_source('Lifecycle fixture',base+'/en/circulars/',{'allow':['/en/'],'deny':['/admin','/test'],'seeds':[base+'/en/circulars/',base+'/en/sitemap.xml'],'discovery_only':['/en/','/en/circulars/','/en/sitemap.xml'],'selector':'article','delay':0,'interval':60,'missing_interval':2})
    with s.db.tx() as c:
        cfg={**source["config"],"missing_interval":0}
        c.execute(sources.update().where(sources.c.id==source["id"]).values(config=cfg))
    def crawl():return s.run(s.enqueue(source["id"])["id"])
    def act(name,body=None):
        r=client.post("/admin/"+name,headers={"X-Fixture-Token":"test-fixture-only"},json=body)
        r.raise_for_status();return r.json()
    return s,source,crawl,act,client

def test_lifecycle(system):
    s,src,crawl,act,client=system
    a=crawl();assert a["status"]=="succeeded",a
    assert a["metrics"]["created"]==3
    assert len(s.overview()["pages"])==3
    t1=time.time()
    honours=next(p for p in s.overview()["pages"] if "honours" in p["url"])
    scholarship=next(p for p in s.overview()["pages"] if "scholarship" in p["url"])
    assert "20 August" in s.get_page(honours["id"])["version"]["content"]
    unchanged=crawl();assert unchanged["metrics"]["unchanged"]==3
    assert unchanged["metrics"]["new_vectors"]==0
    act("noise-only");noise=crawl();assert noise["metrics"]["unchanged"]==3
    assert len(s.db.all(select(versions)))==3
    act("modify-honours");changed=crawl()
    assert changed["metrics"]["modified"]==1
    assert changed["metrics"]["new_vectors"]==2
    assert changed["metrics"]["reused_vectors"]==3
    assert "28 August" in s.get_page(honours["id"])["version"]["content"]
    diff=s.diff(honours["id"],1,2)["diff"]
    assert "+Registration closes on 28 August" in diff and "NOC" in diff
    now=s.search("honours registration deadline",source_ids=[src["id"]])
    assert any(r["page_id"]==honours["id"] for r in now["results"])
    assert all(r["number"]==2 for r in now["results"] if r["page_id"]==honours["id"])
    past=s.search("honours registration deadline",source_ids=[src["id"]],mode="as_of",as_of=t1)
    assert any(r["page_id"]==honours["id"] for r in past["results"])
    assert all(r["number"]==1 for r in past["results"] if r["page_id"]==honours["id"])
    act("delete-scholarship")
    first=crawl();assert first["metrics"]["missing"]==1
    gap=time.time()
    assert not any(r["page_id"]==scholarship["id"] for r in s.search("scholarship renewal",source_ids=[src["id"]])["results"])
    crawl();last=crawl();assert last["metrics"]["deleted"]==1
    assert s.get_page(scholarship["id"])["page"]["availability"]=="deleted"
    act("restore-scholarship");restored=crawl();assert restored["metrics"]["restored"]==1
    assert s.get_page(scholarship["id"])["version"]["number"]==2
    historical=s.search("scholarship renewal",source_ids=[src["id"]],mode="as_of",as_of=gap)
    assert not any(r["page_id"]==scholarship["id"] for r in historical["results"])
    act("add-notice");added=crawl();assert added["metrics"]["created"]==2,added
    pdf=next(p for p in s.overview()["pages"] if p["url"].endswith(".pdf"))
    assert "4 October" in s.get_page(pdf["id"])["version"]["content"]
    act("modify-pdf");assert crawl()["metrics"]["modified"]==1
    assert "7 October" in s.get_page(pdf["id"])["version"]["content"]

def test_transient_errors_preserve_current(system):
    s,src,crawl,act,client=system;crawl()
    p=next(p for p in s.overview()["pages"] if "honours" in p["url"])
    verified=p["verified_at"];version=p["current_id"]
    act("fault",{"target":"honours-registration","status":503})
    r=crawl();assert r["status"]=="partial"
    p=s.get_page(p["id"])["page"]
    assert p["current_id"]==version and p["verified_at"]==verified and p["missing_count"]==0
    assert p["health"]=="error"
    act("clear-faults");crawl()
    assert s.get_page(p["id"])["page"]["health"]=="healthy"

def test_failed_index_keeps_old_version(system,monkeypatch):
    s,src,crawl,act,client=system;crawl()
    p=next(p for p in s.overview()["pages"] if "honours" in p["url"])
    act("modify-honours")
    original=s.embedder.encode
    def fail(text):raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(s.embedder,"encode",fail)
    r=crawl();assert r["status"]=="partial"
    assert s.get_page(p["id"])["version"]["number"]==1
    monkeypatch.setattr(s.embedder,"encode",original)
    assert crawl()["metrics"]["modified"]==1
    assert s.get_page(p["id"])["version"]["number"]==2

def test_duplicate_jobs_and_disabled_source(system):
    s,src,crawl,act,client=system
    a=s.enqueue(src["id"]);b=s.enqueue(src["id"]);assert a["id"]==b["id"]
    s.run(a["id"]);s.run(a["id"])
    assert len(s.db.all(select(versions)))==3
    s.set_source(src["id"],enabled=False)
    assert s.search("honours",source_ids=[src["id"]])["results"]==[]
    with pytest.raises(ValueError):s.enqueue(src["id"])

def test_missing_recovery_and_reversion(system):
    s,src,crawl,act,client=system;crawl()
    p=next(p for p in s.overview()["pages"] if "scholarship" in p["url"])
    act("delete-scholarship");crawl()
    act("restore-scholarship");crawl()
    assert len(s.history(p["id"])["versions"])==1
    assert len(s.history(p["id"])["intervals"])==2
    act("modify-honours");crawl();act("reset");crawl()
    h=next(p for p in s.overview()["pages"] if "honours" in p["url"])
    assert [x["number"] for x in s.history(h["id"])["versions"]]==[1,2,3]

def test_old_lease_rejected(system):
    s,src,crawl,act,client=system
    r=s.enqueue(src["id"]);s.run(r["id"])
    with s.db.tx() as c:
        with pytest.raises(ValueError,match="STALE_WORKER"):s._guard(c,src["id"],r["id"],0)

def test_admin_auth_and_reset(system):
    s,src,crawl,act,client=system
    assert client.post("/admin/reset").status_code==401
    act("add-notice");act("modify-honours");act("delete-scholarship");act("reset")
    assert client.get("/en/circulars/reassessment-supplementary").status_code==404
    assert client.get("/en/circulars/scholarship-notice").status_code==200
    a=client.get("/en/circulars/honours-registration")
    assert "20 August" in a.text
    assert client.get("/en/circulars/honours-registration",headers={"If-None-Match":a.headers["etag"]}).status_code==304

def test_url_scope_and_private_addresses(system):
    s,src,crawl,act,client=system
    assert canonical("https://EXAMPLE.org/docs/?utm_source=x&id=2#part")=="https://example.org/docs/?id=2"
    assert canonical("https://example.org/docs")!=canonical("https://example.org/docs/")
    with pytest.raises(ValueError):canonical("file:///etc/passwd")
    with pytest.raises(ValueError):canonical("http://name:password@example.org/")
    with pytest.raises(ValueError):s.add_source("unsafe","http://127.0.0.1:5432/")
    with pytest.raises(ValueError):s.add_source("unsafe","http://169.254.169.254/")
    with pytest.raises(ValueError):s.add_source("private destination","http://127.0.0.1:5432/",{})
    with pytest.raises(ValueError):s.add_source("too large",src["root_url"],{"max_bytes":20*1024*1024})

def test_extraction_preserves_meaning():
    a=b'<html><title>Rule</title><article><h1>Notice</h1><h2>Date</h2><p>20 August. Do NOT pay.</p><p><a href="/a">form</a></p></article><footer>clock 1</footer></html>'
    b=a.replace(b'clock 1',b'clock 2')
    d1=extract(a,"text/html","https://example.org/",{})
    assert d1.hash==extract(b,"text/html","https://example.org/",{}).hash
    assert d1.hash==extract(b,"text/html","https://example.org/",{"exclude":""}).hash
    assert d1.hash!=extract(a.replace(b'20 August',b'28 August'),"text/html","https://example.org/",{}).hash
    assert d1.hash!=extract(a.replace(b'href="/a"',b'href="/b"'),"text/html","https://example.org/",{}).hash
    with pytest.raises(ValueError):extract(b'<html><article><h1>404 Page not found</h1></article></html>',"text/html","https://example.org/",{})
    with pytest.raises(ValueError):extract(b'%PDF corrupt',"application/pdf","https://example.org/a.pdf",{})

def test_no_answer_and_invalid_history(system):
    s,src,crawl,act,client=system;crawl()
    assert s.search("zzqnonexistentwords",source_ids=[src["id"]])["results"]==[]
    assert s.search("honours",source_ids=[src["id"]],mode="as_of",as_of=1)["results"]==[]
    with pytest.raises(ValueError):s.search("honours",mode="as_of")
    with pytest.raises(ValueError):s.get_page("unknown",1)



def test_generic_layouts_and_scope(tmp_path,monkeypatch):
    """A separate docs server proves the engine has no college route dependency."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import threading
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            bodies={
              "/docs/":("text/html",b'<main><h1>Developer docs</h1><p><a href="/docs/auth">Auth</a><a href="/docs/limits.md">Limits</a><a href="/outside">Outside scope</a></p></main>'),
              "/docs/auth":("text/html",b'<html><title>Authentication</title><body><nav>Volatile navigation</nav><main><h1>Authentication</h1><h2>API tokens</h2><p>Send the token in the Authorization header.</p></main></body></html>'),
              "/docs/limits.md":("text/markdown",b'# Rate limits\n## Default\nThe default request limit is 100 per minute.'),
              "/outside":("text/plain",b'Never index this document')}
            if self.path not in bodies:self.send_error(404);return
            mime,body=bodies[self.path];self.send_response(200);self.send_header("Content-Type",mime);self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(config,"DATA",tmp_path)
    try:
        s=Service(DB("sqlite:///"+str(tmp_path/"generic.db")),Embedder("lexical"),Fetcher(base))
        src=s.add_source("Developer docs",base+"/docs/",{"allow":["/docs/"],
            "discovery_only":["/docs/"],"delay":0})
        result=s.run(s.enqueue(src["id"])["id"])
        assert result["metrics"]["created"]==2,result
        assert all("/docs/" in p["url"] for p in s.overview()["pages"])
        assert any("Authorization" in r["text"] for r in s.search("API authentication token")["results"])
        assert any("Authorization" in r["text"] for r in s.search("API authentication token",source_ids=[src['id']])["results"])
        assert any("100 per minute" in r["text"] for r in s.search("request limit",source_ids=[src['id']])["results"])
    finally:server.shutdown();server.server_close()

def test_worker_recovers_abandoned_job(system):
    s,src,crawl,act,client=system
    job=s.enqueue(src["id"])
    with s.db.tx() as c:
        c.execute(runs.update().where(runs.c.id==job["id"]).values(status="running"))
        c.execute(sources.update().where(sources.c.id==src["id"]).values(lease_run=job["id"],lease_until=1))
    new=s.worker_once()
    assert new["status"]=="succeeded" and new["id"]!=job["id"]
    assert len(s.overview()["pages"])==3

def test_model_signature_change_forces_reindex(system):
    s,src,crawl,act,client=system;crawl()
    s.embedder.signature+=":changed"
    result=crawl()
    assert result["metrics"]["modified"]==3,result
    assert len(s.db.all(select(versions)))==6

def test_robots_redirect_and_refresh(monkeypatch):
    from parity.fetch import Response
    fetcher=Fetcher()
    root="https://example.org"
    source={"root_url":root+"/docs/","config":{"allow":["/docs/"],"deny":[]}}
    requested=[]
    def request(url,source,headers):
        requested.append(url)
        if url.endswith("robots.txt"):
            return Response(url,200,{},b"User-agent: *\nDisallow: /docs/private\n")
        return Response(url,302,{"location":"/docs/private"},b"")
    monkeypatch.setattr(fetcher,"_request",request)
    with pytest.raises(FetchError,match="ROBOTS_BLOCKED"):fetcher.get(root+"/docs/public",source)
    assert root+"/docs/private" not in requested
    fetcher.robots_checked[root]=-3601
    with pytest.raises(FetchError,match="ROBOTS_BLOCKED"):fetcher.get(root+"/docs/public",source)
    assert requested.count(root+"/robots.txt")==2
