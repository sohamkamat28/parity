import http.client, socket, ssl, ipaddress, time, re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode, unquote
from urllib.robotparser import RobotFileParser
from . import config

class FetchError(ValueError):
    pass

def canonical(url):
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        raise FetchError("Only HTTP/HTTPS URLs without embedded credentials are allowed")
    host = p.hostname.lower().encode("idna").decode()
    port = p.port or (443 if p.scheme.lower()=="https" else 80)
    authority = ("[" + host + "]") if ":" in host else host
    if port != (443 if p.scheme.lower()=="https" else 80):
        authority += ":" + str(port)
    query = [(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid","gclid")]
    path = p.path or "/"
    if any(ord(ch)<32 for ch in url) or len(url)>4096:
        raise FetchError("Invalid URL")
    return urlunsplit((p.scheme.lower(),authority,path,urlencode(query),""))

def origin(url):
    p=urlsplit(canonical(url))
    return p.scheme + "://" + p.netloc

def _path_allowed(url, rules, document=True):
    path=unquote(urlsplit(url).path)
    # Encoded separators/traversals must not acquire a different meaning downstream.
    if "\\" in path or any(segment in (".","..") for segment in path.split("/")):
        return False
    if unquote(path)!=path:return False
    def matches(prefix):
        return prefix=="/" or path==prefix.rstrip("/") or path.startswith(prefix.rstrip("/")+"/")
    if any(matches(x) for x in rules.get("deny",["/admin","/login"])):return False
    return not document or any(matches(x) for x in rules.get("allow",["/"]))

def in_scope(url, source):
    try:
        u=canonical(url)
        if origin(u)!=origin(source["root_url"]): return False
        if source['config'].get('scope_mode') == 'page':
            current=urlsplit(u); root=urlsplit(canonical(source['root_url']))
            if current.path.rstrip('/') != root.path.rstrip('/') or current.query != root.query:
                return False
        return _path_allowed(u,source["config"])
    except (ValueError,UnicodeError):
        return False

def resource_in_scope(url, source):
    """Assets may leave document paths, but never declared origins or denied paths."""
    try:
        u=canonical(url)
        allowed={origin(source["root_url"]),*source["config"].get("resource_origins",[])}
        return origin(u) in allowed and _path_allowed(u,source["config"],document=False)
    except (ValueError,UnicodeError):return False

@dataclass
class Response:
    url: str
    status: int
    headers: dict
    body: bytes

class Fetcher:
    """Connects directly to a validated address; TLS checks the original hostname."""
    def __init__(self, demo_origin=None):
        self.demo_origin = demo_origin or config.DEMO_ORIGIN
        self.last_request={}
        self.robots={}
        self.robots_checked={}

    def addresses(self, url, source):
        u=canonical(url)
        if origin(u) not in {origin(source["root_url"]),*source["config"].get("resource_origins",[])}:
            raise FetchError("Cross-origin request blocked")
        p=urlsplit(u)
        demo=source["config"].get("demo",False) and origin(u)==self.demo_origin
        if source["config"].get("demo") and origin(source["root_url"])!=self.demo_origin:
            raise FetchError("Invalid demo origin")
        addresses=list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(
            p.hostname,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM)))
        if not addresses: raise FetchError("DNS returned no addresses")
        for addr in addresses:
            ip=ipaddress.ip_address(addr)
            if ip.version==6 and ip.ipv4_mapped: ip=ip.ipv4_mapped
            if demo and not ip.is_loopback:
                raise FetchError("Demo destination must resolve only to loopback")
            if not demo and not ip.is_global:
                raise FetchError("Non-public destination blocked")
        return addresses

    def _request(self,url,source,headers):
        p=urlsplit(url)
        addresses=self.addresses(url,source)
        port=p.port or (443 if p.scheme=="https" else 80)
        spacing=source["config"].get("delay",1.0)
        elapsed=time.monotonic()-self.last_request.get(p.netloc,0)
        if elapsed<spacing: time.sleep(spacing-elapsed)
        self.last_request[p.netloc]=time.monotonic()
        connection=None
        try:
            # No second DNS lookup: the validated numeric address is the socket target.
            sock=socket.create_connection((addresses[0],port),timeout=10)
            if p.scheme=="https":
                sock=ssl.create_default_context().wrap_socket(sock,server_hostname=p.hostname)
            connection=http.client.HTTPConnection(p.hostname,port,timeout=10)
            connection.sock=sock
            request_headers={"Host":p.netloc,"User-Agent":"Parity/0.1 (+source-monitor)",
                             "Accept-Encoding":"identity","Accept":"text/html,application/pdf,text/plain,application/xml"}
            request_headers.update(headers)
            connection.request("GET",urlunsplit(("","",p.path or "/",p.query,"")),headers=request_headers)
            r=connection.getresponse()
            rh={k.lower():v for k,v in r.getheaders()}
            if rh.get("content-encoding","identity").lower() not in ("identity",""):
                raise FetchError("Unexpected compressed response")
            size=source["config"].get("max_bytes",10*1024*1024)
            body=r.read(size+1)
            if len(body)>size: raise FetchError("Response exceeds byte limit")
            return Response(url,r.status,rh,body)
        except (OSError,http.client.HTTPException) as e:
            raise FetchError(type(e).__name__ + ": " + str(e)) from e
        finally:
            if connection: connection.close()

    def _robots_for(self,url,source):
        key=origin(url)
        if source["config"].get("demo") and key==self.demo_origin:return None
        if key not in self.robots or time.monotonic()-self.robots_checked.get(key,0)>=3600:
            current=key+"/robots.txt"
            for hop in range(4):
                rr=self._request(current,source,{})
                if rr.status not in (301,302,303,307,308):break
                target=canonical(urljoin(current,rr.headers.get("location","")))
                if hop==3 or origin(target)!=key or not _path_allowed(target,source["config"],False):
                    raise FetchError("Robots redirect outside allowed scope")
                current=target
            if rr.status==404:self.robots[key]=None
            elif rr.status==200:
                rp=RobotFileParser()
                rp.parse(rr.body.decode("utf-8",errors="replace").splitlines())
                self.robots[key]=rp
            else:raise FetchError("Robots rules unavailable; retry later")
            self.robots_checked[key]=time.monotonic()
        return self.robots[key]

    def get(self,url,source,headers=None,robots=True,resource=False):
        url=canonical(url)
        scoped=resource_in_scope if resource else in_scope
        if not scoped(url,source):raise FetchError("URL outside allowed paths or origins")
        current=url
        for hop in range(4):
            rp=self._robots_for(current,source) if robots else None
            if rp and not rp.can_fetch("Parity",current):raise FetchError("ROBOTS_BLOCKED")
            r=self._request(current,source,headers or {})
            if r.status not in (301,302,303,307,308): return r
            if hop==3: raise FetchError("Redirect limit exceeded")
            if not r.headers.get("location"):raise FetchError("Redirect has no destination")
            current=canonical(urljoin(current,r.headers.get("location","")))
            if not scoped(current,source): raise FetchError("Redirect outside allowed scope")
            headers={}
        raise FetchError("Redirect failure")
