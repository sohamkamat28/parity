import argparse,json,time,sys
from datetime import datetime
from parity.service import Service

def main():
    p=argparse.ArgumentParser(description="Parity local knowledge monitor")
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("add-source");a.add_argument("name");a.add_argument("url");a.add_argument("--config")
    a=sub.add_parser("crawl");a.add_argument("source_id")
    a=sub.add_parser("search");a.add_argument("query");a.add_argument("--source");a.add_argument("--as-of")
    a=sub.add_parser("history");a.add_argument("page_id")
    a=sub.add_parser("diff");a.add_argument("page_id");a.add_argument("v1",type=int);a.add_argument("v2",type=int)
    a=sub.add_parser("page");a.add_argument("page_id");a.add_argument("--version",type=int)
    sub.add_parser("status");sub.add_parser("worker")
    a=sub.add_parser('automations');a.add_argument('--source')
    a=sub.add_parser('automation-preview');a.add_argument('instructions');a.add_argument('--answers',help='JSON file with clarification answers');a.add_argument('--plan',help='JSON file containing a visual calculation plan')
    a=sub.add_parser('automation-start');a.add_argument('draft_id')
    a=sub.add_parser('automation-history');a.add_argument('automation_id')
    a=sub.add_parser('automation-pause');a.add_argument('automation_id');a.add_argument('--resume',action='store_true')
    a=sub.add_parser('automation-archive');a.add_argument('automation_id')
    a=sub.add_parser('automation-parameters');a.add_argument('automation_id');a.add_argument('json_file')
    sub.add_parser('automation-alerts')
    args=p.parse_args();s=Service()
    if args.command.startswith('automation'):
        from parity.automation import Automations
        automation=Automations(s)
        if args.command=='automations':out=automation.listing(args.source)
        elif args.command=='automation-preview':
            payload={'instructions':args.instructions}
            for option in ('answers','plan'):
                filename=getattr(args,option)
                if filename:
                    with open(filename,encoding='utf-8') as f:payload[option]=json.load(f)
            out=automation.preview(payload)
        elif args.command=='automation-start':out=automation.activate({'draft_id':args.draft_id})
        elif args.command=='automation-history':out=automation.history(args.automation_id)
        elif args.command=='automation-pause':out=automation.patch(args.automation_id,{'paused':not args.resume})
        elif args.command=='automation-archive':out=automation.archive(args.automation_id)
        elif args.command=='automation-parameters':
            with open(args.json_file,encoding='utf-8') as f:parameters=json.load(f)
            out=automation.patch(args.automation_id,{'parameters':parameters})
        else:out=automation.alerts()
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
