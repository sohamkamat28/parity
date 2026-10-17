import argparse,json,time,sys
from datetime import datetime
from parity.service import Service

def main():
    p=argparse.ArgumentParser(description="Parity local knowledge monitor")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("demo-source")
    a=sub.add_parser("add-source");a.add_argument("name");a.add_argument("url");a.add_argument("--config")
    a=sub.add_parser("crawl");a.add_argument("source_id")
    a=sub.add_parser("search");a.add_argument("query");a.add_argument("--source");a.add_argument("--as-of")
    a=sub.add_parser("history");a.add_argument("page_id")
    a=sub.add_parser("diff");a.add_argument("page_id");a.add_argument("v1",type=int);a.add_argument("v2",type=int)
    a=sub.add_parser("page");a.add_argument("page_id");a.add_argument("--version",type=int)
    sub.add_parser("status");sub.add_parser("worker")
    args=p.parse_args();s=Service()
    if args.command=="demo-source":out=s.seed_demo()
    elif args.command=="add-source":
        settings=json.loads(open(args.config,encoding="utf-8").read()) if args.config else None
        out=s.add_source(args.name,args.url,settings)
    elif args.command=="crawl":out=s.run(s.enqueue(args.source_id)["id"])
    elif args.command=="search":
        when=datetime.fromisoformat(args.as_of.replace("Z","+00:00")).timestamp() if args.as_of else None
        out=s.search(args.query,[args.source] if args.source else None,mode="as_of" if when else "current",as_of=when)
    elif args.command=="history":out=s.history(args.page_id)
    elif args.command=="diff":out=s.diff(args.page_id,args.v1,args.v2)
    elif args.command=="page":out=s.get_page(args.page_id,args.version)
    elif args.command=="status":out=s.overview()
    else:
        print("Worker running. Ctrl+C stops it.")
        while True:s.worker_once();time.sleep(1)
    print(json.dumps(out,indent=2,ensure_ascii=False,default=str))

if __name__=="__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    main()
