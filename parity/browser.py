"""Bounded browser capture; the crawler never launches Chromium in its worker thread."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from .fetch import FetchError, Response

CAPTURE_SECONDS = 45
MAX_RESOURCES = 60
MAX_CAPTURE_BYTES = 25 * 1024 * 1024


def preview_capture(service, url, source):
    """Interactive previews share the same Chromium reservation as capture workers."""
    import time
    from sqlalchemy import select
    from .jobs import Jobs
    from .db import uid
    from .job_schema import resource_locks
    owner='preview-'+uid()
    with service.db.tx() as connection:
        if not Jobs(service)._reserve(connection,resource_locks,'name','chromium',owner,time.time()):
            raise ValueError('Chromium is capturing another page. Wait for that check to finish, then refresh the preview.')
    try:return capture(url,source,getattr(service.fetcher,"fixture_origin",None))
    finally:
        with service.db.tx() as connection:
            connection.execute(resource_locks.update().where(resource_locks.c.name=='chromium',resource_locks.c.owner==owner).values(owner=None,lease_until=0))


def browser_status():
    """Inspect Playwright's pinned browser installation without starting a browser."""
    try:
        spec=importlib.util.find_spec("playwright")
        if spec is None or not spec.submodule_search_locations:
            raise ValueError("Playwright is missing. Run setup.ps1 to install browser support.")
        package=Path(next(iter(spec.submodule_search_locations)))
        manifest=json.loads((package/"driver"/"package"/"browsers.json").read_text(encoding="utf-8"))
        chromium=next(x for x in manifest["browsers"] if x["name"]=="chromium")
        configured=os.getenv("PLAYWRIGHT_BROWSERS_PATH")
        if configured=="0":root=package/"driver"/"package"/".local-browsers"
        elif configured:root=Path(configured)
        elif sys.platform=="win32":root=Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"ms-playwright"
        elif sys.platform=="darwin":root=Path.home()/"Library"/"Caches"/"ms-playwright"
        else:root=Path(os.getenv("XDG_CACHE_HOME",Path.home()/".cache"))/"ms-playwright"
        revision=chromium.get("revisionOverrides",{}).get(sys.platform,chromium["revision"])
        folder=root/("chromium-"+str(revision))
        candidates=[folder/"chrome-win64"/"chrome.exe",folder/"chrome-win"/"chrome.exe",
                    folder/"chrome-linux64"/"chrome",folder/"chrome-linux"/"chrome",
                    folder/"chrome-mac"/"Chromium.app"/"Contents"/"MacOS"/"Chromium"]
        candidates += [folder/"chrome-mac-arm64"/"Google Chrome for Testing.app"/"Contents"/"MacOS"/"Google Chrome for Testing",
                       folder/"chrome-mac-x64"/"Google Chrome for Testing.app"/"Contents"/"MacOS"/"Google Chrome for Testing"]
        executable=next((p for p in candidates if p.is_file()),None)
        if executable is None:
            raise ValueError("Matching Chromium is missing. Run python -m playwright install chromium.")
        return {"status":"installed","executable":str(executable),"error":None}
    except (OSError,ValueError,StopIteration,KeyError) as error:
        return {"status":"missing","executable":None,"error":str(error)}


def capture(url,source,fixture_origin=None):
    readiness=browser_status()
    if readiness['status']!='installed':raise FetchError(readiness['error'],code='rendering_unavailable',transient=False)
    payload={"url":url,"source":source,"fixture_origin":fixture_origin,
             "seconds":CAPTURE_SECONDS,"max_resources":MAX_RESOURCES,"max_bytes":MAX_CAPTURE_BYTES}
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0
    proc=subprocess.Popen([sys.executable,"-m","parity.browser_worker"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=flags)
    try:
        stdout,stderr=proc.communicate(json.dumps(payload).encode("utf-8"),timeout=CAPTURE_SECONDS)
    except subprocess.TimeoutExpired as error:
        # Windows terminate() does not terminate grandchildren; kill the complete tree.
        if sys.platform=="win32":
            try:subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,timeout=2)
            except (OSError,subprocess.TimeoutExpired):pass
        if proc.poll() is None:proc.kill()
        try:proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:pass
        raise FetchError("Browser capture exceeded the 45-second hard limit") from error
    try:result=json.loads(stdout)
    except (ValueError,UnicodeError) as error:
        detail=stderr.decode("utf-8",errors="replace")[-700:]
        raise FetchError("Browser capture process failed: "+(detail or str(proc.returncode))) from error
    if proc.returncode or result.get("error"):
        raise FetchError("Browser capture failed: "+result.get("error","worker exited unexpectedly"),code=result.get('code','rendering_failed'),transient=result.get('transient',True))
    response=result["response"]
    return Response(response["url"],response["status"],response["headers"],base64.b64decode(response["body"]))
