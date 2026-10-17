import hashlib, re, unicodedata, json
from dataclasses import dataclass
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()

def clean(s):
    return unicodedata.normalize("NFC",re.sub(r"[ \t\u00a0]+"," ",s).strip())

@dataclass
class Document:
    title: str
    sections: list
    links: list
    content: str
    hash: str

def extract(body, mime, url, rules):
    links=[]
    if "pdf" in mime or body.startswith(b"%PDF"):
        import subprocess, sys
        try:
            result=subprocess.run([sys.executable,"-m","parity.pdf_worker"],input=body,
                capture_output=True,timeout=20)
            parsed=json.loads(result.stdout)
            if parsed.get("error"):raise ValueError(parsed["error"])
            title=parsed["title"];sections=parsed["sections"]
            for section in sections:section["text"]=clean(section["text"])
        except (subprocess.TimeoutExpired,json.JSONDecodeError) as e:
            raise ValueError("PDF extraction failed or exceeded timeout") from e
    elif any(x in mime for x in ("text/plain","text/markdown")):
        text=body.decode("utf-8")
        title=next((x.lstrip("# ").strip() for x in text.splitlines() if x.strip()),url)
        sections=[]; heading=title; buf=[]
        for line in text.splitlines():
            if re.match(r"^#{1,6}\s",line):
                if buf: sections.append({"heading":heading,"text":"\n".join(buf).strip(),"locator":heading})
                heading=line.lstrip("# ").strip();buf=[]
            else: buf.append(line)
        if buf: sections.append({"heading":heading,"text":"\n".join(buf).strip(),"locator":heading})
    elif "html" in mime or not mime:
        soup=BeautifulSoup(body,"lxml")
        links=[urljoin(url,a["href"]) for a in soup.select("a[href]")]
        if soup.select_one('input[type="password"]'):
            raise ValueError("Authentication page is not document content")
        root=None
        if rules.get("selector"):
            root=soup.select_one(rules["selector"])
            if root is None: raise ValueError("Configured content selector was not found")
        else: root=soup.find("article") or soup.find("main") or soup.body
        if root is None: raise ValueError("No usable HTML content")
        h=root.find("h1")
        title=clean(h.get_text(" ",strip=True) if h else (soup.title.get_text() if soup.title else url))
        if re.search(r"\b(404|page not found|access denied)\b",title,re.I):
            raise ValueError("Soft error page")
        noise="nav,footer,script,style,aside,form"
        if rules.get("exclude",".render-timestamp,#cookie-banner"):
            noise+=","+rules.get("exclude",".render-timestamp,#cookie-banner")
        for element in root.select(noise):
            element.decompose()
        for a in root.select("a[href]"):
            a.replace_with(a.get_text(" ",strip=True)+" ("+urljoin(url,a["href"])+")")
        sections=[]; heading=title; buf=[]
        for element in root.find_all(["h1","h2","h3","h4","p","li","tr","pre"]):
            if element.name in ("li","p") and element.find_parent(["li","tr"]): continue
            text=element.get_text(" | " if element.name=="tr" else " ",strip=True)
            if not text: continue
            if element.name.startswith("h"):
                if buf: sections.append({"heading":heading,"text":"\n".join(buf),"locator":heading})
                heading=clean(text);buf=[]
            else: buf.append(clean(text))
        if buf: sections.append({"heading":heading,"text":"\n".join(buf),"locator":heading})
        if not sections:
            text=clean(root.get_text(" ",strip=True))
            if text: sections=[{"heading":title,"text":text,"locator":"main content"}]
    else:
        raise ValueError("Unsupported content type: "+mime)
    sections=[s for s in sections if s["text"].strip()]
    if not sections: raise ValueError("Empty extraction")
    content="# "+title+"\n\n"+"\n\n".join("## "+s["heading"]+"\n"+s["text"] for s in sections)
    return Document(title,sections,links,content,digest(content))

def chunk(document, embedder):
    result=[]
    for section in document.sections:
        prefix=document.title+"\n"+section["heading"]+"\n"
        for part in embedder.split(section["text"],prefix):
            result.append({**section,"text":part,"input":prefix+part})
    return result
