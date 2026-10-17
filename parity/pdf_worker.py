"""Bounded subprocess PDF extraction; no network or executable document actions."""
import json,sys
import fitz

def main():
    try:
        raw=sys.stdin.buffer.read(10*1024*1024+1)
        if len(raw)>10*1024*1024:raise ValueError("PDF exceeds byte limit")
        with fitz.open(stream=raw,filetype="pdf") as doc:
            if doc.is_encrypted:raise ValueError("Encrypted PDF unsupported")
            if len(doc)>50:raise ValueError("PDF exceeds 50 pages")
            sections=[];size=0
            for i,page in enumerate(doc):
                text=page.get_text("text").strip();size+=len(text)
                if size>2_000_000:raise ValueError("Extracted PDF text exceeds limit")
                if text:sections.append({"heading":doc.metadata.get("title") or "PDF document","text":text,"locator":f"page {i+1}"})
            if not sections:raise ValueError("No readable PDF text; OCR required")
            result={"title":doc.metadata.get("title") or "PDF document","sections":sections}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error":type(e).__name__+": "+str(e)}))

if __name__=="__main__":main()
