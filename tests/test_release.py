"""Release regressions: actual Chromium capture, source isolation and upgrade safety."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select

from parity import browser, config
from parity.browser_worker import BudgetFetcher
from parity.db import DB, meta, schema, sources, pages, versions, runs, chat_messages, chat_conversations, demo_sessions
from parity.embedding import Embedder
from parity.fetch import Fetcher, FetchError, Response, in_scope, resource_in_scope
from parity.operations import DemoService, run_observations
from parity.service import Service


@pytest.fixture
def web_fixture(tmp_path,monkeypatch):
    """A separate site's constant HTML shell loads changing JSON outside document paths."""
    state={"deadline":"18 November","api_status":200,"requests":[],"conditional":[]}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            state["requests"].append(("GET",path))
            state["conditional"].append(self.headers.get("If-None-Match"))
            status=200;mime="text/html";extra={}
            if path=="/docs/live":
                extra={"ETag":'"constant-shell"'}
                body=b'<html><head><title>Live grants</title></head><body><article><h1>Loading grant</h1></article><script src="/assets/live.js"></script></body></html>'
                if self.headers.get("If-None-Match")==extra["ETag"]:status=304;body=b""
            elif path=="/assets/live.js":
                mime="application/javascript"
                body=b'''fetch('/api/grant').then(r=>{if(!r.ok)throw Error('Data unavailable');return r.json()}).then(d=>{document.querySelector('article').innerHTML='<h1>Research grant</h1><p>The application deadline is '+d.deadline+'.</p>';document.querySelector('article').dataset.ready='true'}).catch(e=>{document.querySelector('article').dataset.ready='true';document.querySelector('article').textContent=e.message})'''
            elif path=="/api/grant":
                mime="application/json";status=state["api_status"]
                body=json.dumps({"deadline":state["deadline"]}).encode()
            elif path=="/docs/static":body=b'<html><body><article><h1>Policy</h1><p>Applications need an induction certificate.</p></article></body></html>'
            elif path=="/docs/missing-ready":body=b'<html><body><article><h1>Loading</h1><p>No application data has arrived.</p></article></body></html>'
            elif path=="/docs/hang":body=b'<html><body><script>while(true){}</script></body></html>'
            elif path=="/docs/policy":
                action=state["script"]
                body=('<html><body><article data-ready="true"><h1>Test</h1><p>Policy test.</p></article><script>'+action+'</script></body></html>').encode()
            elif path=="/assets/redirect":status=302;extra={"Location":"/admin/secret"};body=b""
            elif path=="/assets/public-redirect":status=302;extra={"Location":"/api/grant"};body=b""
            elif path=="/docs/oversize":body=b"X"*1025
            elif path=="/admin/secret":body=b"Never fetched"
            else:status=404;body=b"Missing"
            self.send_response(status)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(body)))
            for key,value in extra.items():self.send_header(key,value)
            self.end_headers()
            try:self.wfile.write(body)
            except (ConnectionError,OSError):pass
        def do_POST(self):
            state["requests"].append(("POST",urlsplit(self.path).path))
            self.send_response(200);self.end_headers()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(config,"DEMO_ORIGIN",base)
    monkeypatch.setattr(config,"DATA",tmp_path)
    service=Service(DB("sqlite:///"+str(tmp_path/"release.db")),Embedder("lexical"),Fetcher(base))
    def source(path="/docs/live",**settings):
        return service.add_source("Independent site",base+path,{
            "demo":True,"allow":["/docs/"],"deny":["/admin"],"max_depth":0,
            "render_mode":"browser","ready_selector":'article[data-ready="true"]',
            "selector":"article","delay":0,**settings})
    yield service,source,state,base
    server.shutdown();server.server_close();thread.join(timeout=2)
    service.db.engine.dispose()


def require_browser():
    status=browser.browser_status()
    if status["status"]!="installed":pytest.skip(status["error"])


def test_browser_json_changes_with_constant_html_and_immutable_artifacts(web_fixture):
    require_browser()
    service,create,state,base=web_fixture
    source=create()
    def crawl():return service.run(service.enqueue(source["id"])["id"])
    baseline=crawl()
    assert baseline["status"]=="succeeded",baseline
    assert baseline["metrics"]["created"]==1
    page=service.overview()["pages"][0]
    first=service.get_page(page["id"])["version"]
    assert "18 November" in first["content"]
    unchanged=crawl()
    assert unchanged["metrics"]["unchanged"]==1
    assert unchanged["metrics"]["new_vectors"]==0
    state["deadline"]="25 November"
    changed=crawl()
    assert changed["metrics"]["modified"]==1,changed
    second=service.get_page(page["id"])["version"]
    assert second["number"]==2 and "25 November" in second["content"]
    assert first["raw_key"]!=second["raw_key"]
    assert b"18 November" in (config.DATA/"artifacts"/first["raw_key"]).read_bytes()
    assert b"25 November" in (config.DATA/"artifacts"/second["raw_key"]).read_bytes()
    assert not any(state["conditional"]),"Rendered pages must not use the HTML shell's ETag shortcut"
    assert ("GET","/assets/live.js") in state["requests"]
    assert ("GET","/api/grant") in state["requests"]
    assert service.search("grant application deadline")["results"] == []
    assert "25 November" in service.search("grant application deadline",source_ids=[source['id']])["results"][0]["text"]


def test_browser_resource_failure_retains_verified_version(web_fixture):
    require_browser()
    service,create,state,_=web_fixture;source=create()
    first=service.run(service.enqueue(source["id"])["id"])
    assert first["status"]=="succeeded"
    old=service.overview()["pages"][0]
    state["api_status"]=503
    failure=service.run(service.enqueue(source["id"])["id"])
    assert failure["status"]=="partial",failure
    current=service.get_page(old["id"])["page"]
    assert current["current_id"]==old["current_id"]
    assert current["verified_at"]==old["verified_at"]
    assert current["health"]=="error" and "503" in current["last_error"]
    details=run_observations(service,failure["id"])["items"]
    assert any("503" in row["detail"] for row in details)


@pytest.mark.parametrize("script,blocked",[
    ("fetch('/admin/secret').catch(()=>{})",("GET","/admin/secret")),
    ("fetch('/api/write',{method:'POST',body:'unsafe'}).catch(()=>{})",("POST","/api/write")),
    ("fetch('/assets/redirect').catch(()=>{})",("GET","/admin/secret")),
    ("fetch('http://127.0.0.1:1/private').catch(()=>{})",None),
])
def test_browser_blocks_mutation_scope_escape_and_redirects(web_fixture,script,blocked):
    require_browser()
    _,create,state,base=web_fixture
    state["script"]=script
    source=create("/docs/policy",ready_selector="")
    with pytest.raises(FetchError):browser.capture(base+"/docs/policy",source,base)
    if blocked:assert blocked not in state["requests"]


def test_browser_blocks_frames_websockets_workers_and_downloads(web_fixture):
    require_browser()
    _,create,state,base=web_fixture
    state["script"]="""
    const frame=document.createElement('iframe');frame.src='/admin/frame';document.body.append(frame);
    try{new WebSocket('ws://127.0.0.1:1/socket')}catch(e){}
    if(navigator.serviceWorker)navigator.serviceWorker.register('/admin/worker.js').catch(()=>{});
    """
    source=create("/docs/policy",ready_selector="")
    result=browser.capture(base+"/docs/policy",source,base)
    assert result.status==200
    assert not any(path.startswith("/admin") for _,path in state["requests"])


def test_browser_resolves_terminal_redirect_in_pinned_fetcher(web_fixture):
    require_browser()
    _,create,state,base=web_fixture
    state["script"]="""fetch('/assets/public-redirect').then(r=>r.json()).then(d=>{document.querySelector('article').innerHTML='<h1>Grant</h1><p>'+d.deadline+'</p>'})"""
    source=create("/docs/policy",ready_selector="")
    result=browser.capture(base+"/docs/policy",source,base)
    assert b"18 November" in result.body
    assert result.status==200 and "location" not in result.headers
    assert ("GET","/assets/public-redirect") in state["requests"]
    assert ("GET","/api/grant") in state["requests"]


def test_browser_readiness_is_required_and_execution_is_time_bounded(web_fixture,monkeypatch):
    require_browser()
    _,create,_,base=web_fixture
    monkeypatch.setattr(browser,"CAPTURE_SECONDS",6)
    source=create("/docs/missing-ready")
    started=time.monotonic()
    with pytest.raises(FetchError,match="Timeout|time budget|hard limit"):
        browser.capture(base+"/docs/missing-ready",source,base)
    assert time.monotonic()-started<12
    monkeypatch.setattr(browser,"CAPTURE_SECONDS",3)
    source=create("/docs/hang")
    started=time.monotonic()
    with pytest.raises(FetchError,match="hard limit|Timeout|budget"):
        browser.capture(base+"/docs/hang",source,base)
    assert time.monotonic()-started<9


def test_browser_transfer_and_request_budgets_stop_transport(monkeypatch):
    actual=[]
    def response(self,url,source,headers):
        actual.append(url);return Response(url,200,{},b"abcd")
    monkeypatch.setattr(Fetcher,"_request",response)
    payload={"seconds":45,"max_resources":2,"max_bytes":25*1024*1024}
    fetcher=BudgetFetcher(payload)
    fetcher._request("https://example.org/a",{},{});fetcher._request("https://example.org/b",{},{})
    with pytest.raises(FetchError,match="resource limit"):fetcher._request("https://example.org/c",{},{})
    assert len(actual)==2
    fetcher=BudgetFetcher({**payload,"max_bytes":7})
    fetcher._request("https://example.org/a",{},{})
    with pytest.raises(FetchError,match="transfer limit"):fetcher._request("https://example.org/b",{},{})


def test_individual_response_size_limit(web_fixture):
    service,create,_,base=web_fixture
    source=create("/docs/oversize",max_bytes=1024)
    with pytest.raises(FetchError,match="byte limit"):service.fetcher.get(base+"/docs/oversize",source)


def test_asset_scope_and_private_origin_validation(monkeypatch):
    source={"root_url":"https://docs.example/docs/","config":{
        "allow":["/docs"],"deny":["/admin"],"resource_origins":["https://cdn.example"]}}
    assert not in_scope("https://docs.example/assets/main.js",source)
    assert resource_in_scope("https://docs.example/assets/main.js",source)
    assert resource_in_scope("https://cdn.example/main.js",source)
    for url in ("https://other.example/main.js","https://cdn.example/admin/token",
                "https://docs.example/docs/%252e%252e/admin","https://docs.example/docs/../admin"):
        assert not resource_in_scope(url,source)
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))])
    with pytest.raises(FetchError,match="Non-public"):Fetcher().addresses("https://cdn.example/main.js",source)


def test_resource_robots_are_checked_after_cross_origin_redirect(monkeypatch):
    source={"root_url":"https://docs.example/docs/","config":{
        "allow":["/docs"],"deny":[],"resource_origins":["https://cdn.example"]}}
    calls=[]
    def request(self,url,source,headers):
        calls.append(url)
        if url=="https://docs.example/robots.txt":return Response(url,200,{},b"User-agent: *\nAllow: /\n")
        if url=="https://cdn.example/robots.txt":return Response(url,200,{},b"User-agent: *\nDisallow: /private\n")
        return Response(url,302,{"location":"https://cdn.example/private/asset.js"},b"")
    monkeypatch.setattr(Fetcher,"_request",request)
    with pytest.raises(FetchError,match="ROBOTS_BLOCKED"):
        Fetcher().get("https://docs.example/assets/main.js",source,resource=True)
    assert "https://cdn.example/robots.txt" in calls
    assert "https://cdn.example/private/asset.js" not in calls


def test_source_preview_does_not_index_and_updates_merge(web_fixture):
    service,create,_,base=web_fixture
    source=create("/docs/static",render_mode="static",ready_selector="")
    preview=service.test_source("Preview",base+"/docs/static",source["config"])
    assert "induction certificate" in preview["text"]
    assert preview["render_mode"]=="static" and preview["elapsed_ms"]>=0
    assert service.overview()["pages"]==[] and service.overview()["runs"]==[]
    updated=service.update_source(source["id"],name="Edited",settings={"interval":30})
    assert updated["name"]=="Edited" and updated["config"]["interval"]==30
    assert updated["config"]["selector"]=="article" and updated["config"]["allow"]==["/docs/"]
    for setting in ({"render_mode":"unsafe"},{"ready_selector":"["},{"resource_origins":["http://127.0.0.1:1"]}):
        with pytest.raises(ValueError):service.update_source(source["id"],settings=setting)
    assert service.source(source["id"])["config"]==updated["config"]


def test_model_warmup_precedes_lease_and_heartbeat_survives_slow_encoding(web_fixture,monkeypatch):
    service,create,_,_=web_fixture
    source=create("/docs/static",render_mode="static",ready_selector="")
    job=service.enqueue(source["id"])
    real_model=service.model;observed=[]
    def model():
        if not observed:
            row=service.source(source["id"])
            observed.append((row["lease_until"],row.get("lease_run")))
            time.sleep(.25)
        return real_model()
    monkeypatch.setattr(service,"model",model)
    monkeypatch.setattr(config,"LEASE_SECONDS",.8)
    encode=service.embedder.encode
    def slow_encode(text):time.sleep(1.3);return encode(text)
    monkeypatch.setattr(service.embedder,"encode",slow_encode)
    result=service.run(job["id"])
    assert observed==[(0,None)]
    assert result["status"]=="succeeded",result
    assert service.source(source["id"])["lease_until"]==0


def test_model_initialization_failure_finishes_job_without_claiming(web_fixture,monkeypatch):
    service,create,_,_=web_fixture
    source=create("/docs/static",render_mode="static",ready_selector="")
    job=service.enqueue(source["id"])
    def fail():raise RuntimeError("Model cache unavailable")
    monkeypatch.setattr(service,"model",fail)
    result=service.run(job["id"])
    assert result["status"]=="failed" and "Model cache unavailable" in result["error"]
    assert result["finished_at"] is not None
    current=service.source(source["id"])
    assert current["generation"]==0 and not current.get("lease_run") and current["lease_until"]==0


def test_v1_database_migration_preserves_history_and_is_idempotent(tmp_path):
    target=tmp_path/"original-v1.db";url="sqlite:///"+str(target)
    old=create_engine(url)
    from parity.db import _V2_TABLES, _V3_TABLES, SCHEMA_VERSION
    excluded={table.name for table in (*_V2_TABLES, *_V3_TABLES)}
    meta.create_all(old,tables=[table for table in meta.sorted_tables if table.name not in excluded])
    with old.begin() as connection:
        connection.execute(schema.insert().values(number=1))
        connection.execute(sources.insert().values(id="existing-source",name="Preserved",root_url="https://example.org/",config={"allow":["/"]}))
        connection.execute(pages.insert().values(id="existing-page",source_id="existing-source",url="https://example.org/rule",current_id="existing-version",last_version_id="existing-version"))
        connection.execute(versions.insert().values(id="existing-version",page_id="existing-page",number=1,title="Existing rule",content="Original retained evidence",hash="old-hash"))
    old.dispose()
    upgraded=DB(url)
    assert upgraded.one(select(schema))["number"]==SCHEMA_VERSION
    assert upgraded.one(select(versions))["content"]=="Original retained evidence"
    assert upgraded.one(select(pages))["current_id"]=="existing-version"
    assert excluded.issubset(set(inspect(upgraded.engine).get_table_names()))
    upgraded.engine.dispose()
    again=DB(url)
    assert len(again.all(select(versions)))==1 and len(again.all(select(sources)))==1
    assert again.all(select(chat_messages))==[] and again.all(select(demo_sessions))==[]
    again.engine.dispose()


def test_newer_database_schema_is_rejected_without_changes(tmp_path):
    target=tmp_path/"future.db";url="sqlite:///"+str(target)
    engine=create_engine(url);schema.create(engine)
    with engine.begin() as connection:connection.execute(schema.insert().values(number=99))
    engine.dispose()
    with pytest.raises(RuntimeError,match="newer"):DB(url)
    engine=create_engine(url)
    with engine.connect() as connection:assert connection.execute(select(schema.c.number)).scalar()==99
    assert set(inspect(engine).get_table_names())=={"schema_version"}
    engine.dispose()


@pytest.fixture(scope="module")
def namespaced_portal(tmp_path_factory):
    root=tmp_path_factory.mktemp("release-portal")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    base=f"http://127.0.0.1:{port}"
    env={**os.environ,"PARITY_DATA_DIR":str(root),"DEMO_ORIGIN":base,"DEMO_ADMIN_TOKEN":"release-test-token"}
    process=subprocess.Popen([sys.executable,"-m","uvicorn","mock_portal.app:app","--host","127.0.0.1","--port",str(port)],
        env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
    client=httpx.Client(base_url=base,trust_env=False,timeout=10)
    try:
        for _ in range(100):
            try:
                if client.get("/health/ready").status_code==200:break
            except httpx.HTTPError:pass
            if process.poll() is not None:raise RuntimeError(process.stderr.read().decode())
            time.sleep(.1)
        else:raise RuntimeError("Fixture portal failed to become ready")
        yield base,client
    finally:
        client.close();process.terminate();process.wait(timeout=5)


def test_demo_sessions_preserve_prior_state_history_and_live_fixture(namespaced_portal,tmp_path,monkeypatch):
    require_browser()
    base,client=namespaced_portal
    monkeypatch.setattr(config,"DEMO_ORIGIN",base);monkeypatch.setattr(config,"DATA",tmp_path)
    monkeypatch.setenv("DEMO_ADMIN_TOKEN","release-test-token")
    service=Service(DB("sqlite:///"+str(tmp_path/"demos.db")),Embedder("lexical"),Fetcher(base))
    demos=DemoService(service)
    first=demos.create("First presentation")
    baseline=demos.action(first["id"],"baseline")
    assert service.run(baseline["runs"][0]["id"])["metrics"]["created"]==3
    changed=demos.action(first["id"],"modify-honours")
    assert service.run(changed["runs"][0]["id"])["metrics"]["modified"]==1
    versions_before=len(service.db.all(select(versions)))
    second=demos.create("Fresh presentation")
    assert first["static_source_id"]!=second["static_source_id"]
    assert first["browser_source_id"]!=second["browser_source_id"]
    assert demos.get(first["id"])["state"]["deadline"].startswith("28 August")
    assert demos.get(second["id"])["state"]["deadline"].startswith("20 August")
    assert len(service.db.all(select(versions)))==versions_before
    source=service.source(second["browser_source_id"])
    shell_before=client.get(source["root_url"]).content
    run=service.run(service.enqueue(source["id"])["id"])
    assert run["status"]=="succeeded" and run["metrics"]["created"]==2,run
    update=demos.action(second["id"],"modify-live")
    assert client.get(source["root_url"]).content==shell_before
    assert service.run(update["runs"][0]["id"])["metrics"]["modified"]==1
    results=service.search("innovation lab applications deadline",source_ids=[source["id"]])["results"]
    assert any("25 November" in row["text"] for row in results)
    assert demos.get(first["id"])["state"]["live"]==1
    assert client.post("/demo/"+first["id"]+"/admin/reset").status_code==401
    assert len(demos.sessions()["sessions"])==2
    service.db.engine.dispose()
