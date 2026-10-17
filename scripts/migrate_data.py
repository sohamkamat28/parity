"""Copy an existing installation into an empty PostgreSQL database."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parity.transfer import migrate_sqlite

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,help='Existing installation, data directory or parity.db file')
    parser.add_argument('--target-data',required=True,help='New empty directory for captured evidence')
    parser.add_argument('--target-url-env',default='DATABASE_URL',help='Environment variable containing the target connection URL')
    parser.add_argument('--backup',help='New backup ZIP path; created before migration')
    args=parser.parse_args();url=os.getenv(args.target_url_env,'')
    if not url:parser.error('Set '+args.target_url_env+' to the PostgreSQL connection URL locally.')
    try:result=migrate_sqlite(args.source,url,args.target_data,args.backup)
    except Exception as error:
        print('Migration failed: '+str(error).replace(url,'<database>'),file=sys.stderr);return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
