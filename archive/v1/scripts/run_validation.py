import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os,sys,subprocess,time
from pathlib import Path
import httpx
env=os.environ.copy()
validation_dir=Path(os.environ.get("PARITY_VALIDATION_DIR","validation_data")).resolve()
if (validation_dir/"parity.db").exists():
    raise SystemExit("Validation data already exists. Set PARITY_VALIDATION_DIR to a new empty directory.")
env.update(PARITY_ADMIN_TOKEN="validation-only",DEMO_ADMIN_TOKEN="validation-only",
           PARITY_DATA_DIR=str(validation_dir))
log=open("validation_runtime.log","w")
proc=subprocess.Popen([sys.executable,"run.py"],env=env,stdout=log,stderr=subprocess.STDOUT)
try:
    with httpx.Client(trust_env=False,timeout=2) as c:
        for _ in range(100):
            try:
                if c.get("http://127.0.0.1:8000/health/ready").status_code==200 and c.get("http://127.0.0.1:8080/health/ready").status_code==200:break
            except httpx.HTTPError:pass
            if proc.poll() is not None:raise RuntimeError("Server exited; see validation_runtime.log")
            time.sleep(.1)
        else:raise RuntimeError("Server not ready")
        for path in ["/","/static/app.js","/static/style.css","/docs"]:
            assert c.get("http://127.0.0.1:8000"+path).status_code==200,path
    subprocess.run([sys.executable,"scripts/validate_running_demo.py"],env=env,check=True)
    subprocess.run([sys.executable,"scripts/validate_mcp.py"],env=env,check=True)
finally:
    import signal
    proc.send_signal(signal.SIGINT)
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.kill()
    log.close()
