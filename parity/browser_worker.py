"""Isolated renderer. All HTTP is fulfilled by the address-pinned Python fetcher."""
import base64
import json
import sys
import time

from .fetch import Fetcher, FetchError, Response, canonical, in_scope, resource_in_scope


class BudgetFetcher(Fetcher):
    def __init__(self,payload):
        super().__init__(payload.get("fixture_origin"))
        self.deadline=time.monotonic()+max(1,payload["seconds"]-3)
        self.max_resources=payload["max_resources"]
        self.max_total=payload["max_bytes"]
        self.requests=0
        self.bytes=0

    def remaining_ms(self):
        remaining=int((self.deadline-time.monotonic())*1000)
        if remaining<=0:raise FetchError("Browser capture time budget exceeded")
        return remaining

    def _request(self,url,source,headers):
        self.remaining_ms()
        self.requests+=1
        if self.requests>self.max_resources:raise FetchError("Browser resource limit exceeded (60 requests)")
        response=super()._request(url,source,headers)
        self.bytes+=len(response.body)
        if self.bytes>self.max_total:raise FetchError("Browser transfer limit exceeded (25 MiB)")
        self.remaining_ms()
        return response


def render(payload):
    source=payload["source"]
    fetcher=BudgetFetcher(payload)
    initial=fetcher.get(payload["url"],source,{})
    mime=initial.headers.get("content-type","").split(";")[0].lower()
    if initial.status!=200 or (mime and "html" not in mime):return initial

    from playwright.sync_api import sync_playwright
    from .browser import browser_status
    status=browser_status()
    if status["status"]!="installed":raise FetchError(status["error"])
    fatal=[]
    blocked=[]
    errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,executable_path=status["executable"],
            proxy={"server":"http://127.0.0.1:9","bypass":"<-loopback>"},
            args=["--disable-background-networking","--disable-component-update","--disable-sync",
                  "--no-first-run","--disable-default-apps","--disable-extensions",
                  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
            timeout=min(15000,fetcher.remaining_ms()))
        try:
            context=browser.new_context(service_workers="block",accept_downloads=False,
                user_agent="Parity/0.2 (+source-monitor)",java_script_enabled=True)
            context.add_init_script("""Object.defineProperty(window,'open',{value:()=>null,writable:false});
                Object.defineProperty(window,'WebSocket',{value:class {constructor(){throw new Error('WebSockets are disabled in Parity capture')}},writable:false});""")
            context.route_web_socket("**/*",lambda route:route.close())
            page=context.new_page()
            context.on("page",lambda other:other.close() if other!=page else None)
            page.on("popup",lambda popup:popup.close())
            page.on("download",lambda download:download.cancel())
            page.on("dialog",lambda dialog:dialog.dismiss())
            page.on("pageerror",lambda error:errors.append(str(error)[:250]))
            initial_used=False

            def route_request(route):
                nonlocal initial_used
                request=route.request
                try:
                    fetcher.remaining_ms()
                    if request.resource_type in ('image','font','media'):
                        route.abort('blockedbyclient');return
                    # Each navigation must stay in document scope; assets have their own origin policy.
                    if request.method!="GET":raise FetchError("Non-GET browser request blocked")
                    if request.frame!=page.main_frame:raise FetchError("Frame or popup request blocked")
                    url=canonical(request.url)
                    document=request.resource_type=="document"
                    if not (in_scope(url,source) if document else resource_in_scope(url,source)):
                        raise FetchError("Browser request outside allowed paths or resource origins")
                    if document and not initial_used and url==initial.url:
                        response=initial
                        initial_used=True
                    else:response=fetcher.get(url,source,{},resource=not document)
                    if 300<=response.status<400:raise FetchError("Non-terminal browser response blocked")
                    if response.status>=400:raise FetchError('Required browser resource returned HTTP '+str(response.status))
                    if document and response.url!=url:
                        raise FetchError('A script-initiated navigation redirected. Configure the final URL as the source.')
                    if response.headers.get("content-disposition","").lower().startswith("attachment"):
                        raise FetchError("Browser download blocked")
                    # No cookies, redirect headers, connection headers or stale content lengths.
                    headers={k:v for k,v in response.headers.items() if k in {
                        "content-type","content-language","access-control-allow-origin",
                        "access-control-allow-methods","access-control-allow-headers",
                        "cross-origin-resource-policy","content-security-policy"}}
                    if document:
                        policy="frame-src 'none'; worker-src 'none'; object-src 'none'"
                        headers["content-security-policy"]=(headers.get("content-security-policy","")+", "+policy).lstrip(", ")
                    route.fulfill(status=response.status,headers=headers,body=response.body)
                except Exception as error:
                    message=str(error)
                    blocked.append(message)
                    if "limit exceeded" in message or "budget exceeded" in message or request.resource_type in ('document','script','fetch','xhr'):
                        fatal.append(message)
                    route.abort("blockedbyclient")

            context.route("**/*",route_request)
            page.goto(initial.url,wait_until="domcontentloaded",timeout=fetcher.remaining_ms())
            selector=source["config"].get("ready_selector","")
            if selector:
                page.locator(selector).first.wait_for(state="attached",timeout=min(15000,fetcher.remaining_ms()))
            else:
                # Content must remain stable after a minimum settling period; never wait for networkidle.
                started=time.monotonic();previous=None;stable=0
                while time.monotonic()-started<6:
                    page.wait_for_timeout(min(350,fetcher.remaining_ms()))
                    text=page.locator("body").inner_text(timeout=fetcher.remaining_ms())
                    stable=stable+1 if text==previous else 0
                    previous=text
                    if stable>=3 and time.monotonic()-started>=1.5:break
            if fatal:raise FetchError("; ".join(dict.fromkeys(fatal))[:1000])
            if errors:raise FetchError('Page script failed: '+errors[0])
            if not in_scope(page.url,source):raise FetchError("Rendered navigation outside document scope")
            body=page.content().encode("utf-8")
            if len(body)>min(source["config"].get("max_bytes",10*1024*1024),10*1024*1024):
                raise FetchError("Rendered document exceeds byte limit")
            headers={**initial.headers,"content-type":"text/html; charset=utf-8",
                     "x-parity-rendered":"true","x-parity-resource-requests":str(fetcher.requests),
                     "x-parity-resource-bytes":str(fetcher.bytes),"x-parity-blocked-resources":str(len(blocked))}
            headers.pop("etag",None);headers.pop("last-modified",None);headers.pop("location",None)
            return Response(page.url,200,headers,body)
        except Exception as error:
            diagnostics="; ".join((fatal+blocked+errors)[-5:])
            raise FetchError(str(error)+(": "+diagnostics if diagnostics else "")) from error
        finally:browser.close()


def main():
    try:
        response=render(json.loads(sys.stdin.buffer.read()))
        result={"response":{"url":response.url,"status":response.status,"headers":response.headers,
                            "body":base64.b64encode(response.body).decode("ascii")}}
    except Exception as error:result={"error":type(error).__name__+": "+str(error)[:1600]}
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))


if __name__=="__main__":main()
