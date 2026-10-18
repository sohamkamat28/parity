"""Benchmark through one authenticated shared MiniLM process; no paid services."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from run import OwnedProcesses
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
logs=ROOT/'outputs/runtime/benchmark';logs.mkdir(parents=True,exist_ok=True)
env={**os.environ,'PARITY_EMBEDDING_URL':f'http://127.0.0.1:{port}','PARITY_EMBEDDING_TOKEN':secrets.token_urlsafe(32),'PARITY_OFFLINE':'1','OMP_NUM_THREADS':'4','TOKENIZERS_PARALLELISM':'false'}
started=time.perf_counter();owned=OwnedProcesses(logs)
try:
    owned.start('embedding',[sys.executable,'-m','uvicorn','parity.embedding_server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],ROOT,env)
    deadline=time.monotonic()+90
    with httpx.Client(trust_env=False,timeout=1) as client:
        while True:
            owned.check()
            try:
                if client.get(env['PARITY_EMBEDDING_URL']+'/health/ready').status_code==200:break
            except httpx.HTTPError:pass
            if time.monotonic()>deadline:raise RuntimeError('Shared model did not become ready; inspect outputs/runtime/benchmark/embedding.log')
            time.sleep(.5)
    startup_seconds=time.perf_counter()-started
    result=subprocess.run([sys.executable,str(ROOT/'scripts/benchmark_v2.py'),*sys.argv[1:]],cwd=ROOT,env=env)
    raise SystemExit(result.returncode)
finally:
    owned.close()
    report_path=ROOT/'docs/verification/benchmark.json'
    if report_path.exists():
        report=json.loads(report_path.read_text());report['shared_model_startup_seconds']=locals().get('startup_seconds')
        try:
            import resource
            report['largest_child_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        except ImportError:pass
        report['memory_scope']='Harness peak RSS per corpus; largest child peak is the maximum of shared embedding and benchmark processes, not their sum. Docker is separate.'
        report_path.write_text(json.dumps(report,indent=2)+'\n')
