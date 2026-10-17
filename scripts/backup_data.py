"""Create, verify or restore a Parity database and evidence backup."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parity.transfer import backup_database,restore_database,verify_backup

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','verify','restore'])
    parser.add_argument('--archive',required=True)
    parser.add_argument('--data',help='Source data folder for create; new empty folder for restore')
    parser.add_argument('--url-env',default='DATABASE_URL')
    args=parser.parse_args();url=os.getenv(args.url_env,'')
    if args.action!='verify' and (not url or not args.data):parser.error('Set the database URL environment variable and specify --data.')
    try:
        if args.action=='verify':
            report=verify_backup(args.archive);result={'verified':True,'tables':len(report['tables']),'files':len(report['files'])}
        elif args.action=='create':result=backup_database(url,args.data,args.archive)
        else:result=restore_database(args.archive,url,args.data)
    except Exception as error:
        message=str(error).replace(url,'<database>') if url else str(error)
        print('Backup operation failed: '+message,file=sys.stderr);return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
