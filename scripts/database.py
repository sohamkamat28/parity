"""Initialize a fresh database or explicitly back up and upgrade an installation."""
import argparse,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parity import config
from parity.deployment import configure_database,docker_status

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--upgrade',action='store_true',help='Back up existing data, then explicitly apply additive migrations; stop services first')
    parser.add_argument('--profile',choices=['postgresql','sqlite'],default=config.PROFILE)
    parser.add_argument('--archive',help='New backup ZIP path for --upgrade')
    args=parser.parse_args()
    try:
        if args.check:
            status=docker_status()
            if status['status']!='ready':raise ValueError(status['error'])
            print('PostgreSQL prerequisites ready')
        else:
            from parity.db import DB
            url=config.DATABASE_URL if args.profile=='sqlite' else configure_database()
            if args.upgrade:
                from parity.transfer import backup_database,verify_backup
                archive=Path(args.archive) if args.archive else config.ROOT/'outputs'/('parity-before-upgrade-'+time.strftime('%Y%m%d-%H%M%S')+'.zip')
                backup_database(url,config.DATA,archive);verify_backup(archive)
                print('Verified pre-upgrade backup: '+str(archive.resolve()))
            db=DB(url,upgrade=args.upgrade);db.engine.dispose()
            print('Database schema ready. Existing history and evidence are retained.')
    except Exception as error:
        message=str(error)
        if 'url' in locals():message=message.replace(url,'<database>')
        print('Database setup needs attention: '+message);raise SystemExit(1)
