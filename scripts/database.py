import sys,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parity.deployment import configure_database,docker_status

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Check Docker prerequisites and initialize the local PostgreSQL database')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        if args.check:
            status=docker_status()
            if status['status']!='ready':raise ValueError(status['error'])
        else:
            from parity.db import DB
            db=DB(configure_database());db.engine.dispose()
        print('PostgreSQL prerequisites ready' if args.check else 'PostgreSQL schema ready. Data persists in the parity2 Docker volume.')
    except Exception as error:
        print('Database setup needs attention: '+str(error));raise SystemExit(1)
