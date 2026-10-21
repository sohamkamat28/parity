"""Independent worker entrypoint: python -m parity.worker --role capture."""
import argparse
import logging
import signal
import threading
from .service import Service
from .jobs import Jobs


def main(argv=None):
    parser=argparse.ArgumentParser(description='Parity background service')
    parser.add_argument('--role',choices=['scheduler','capture','index','automation','notification'],required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
    jobs=Jobs(Service(inline_index=False))
    jobs.status(args.role,'starting')
    if args.role=='automation':
        from .automation import Automations
        automation=Automations(jobs.service)
        def action():
            automation.scheduler_once()
            return automation.once()
    elif args.role=='notification':
        from .automation_notifications import Notifications
        action=Notifications(jobs.service).once
    else:action={'scheduler':jobs.scheduler_once,'capture':jobs.capture_once,'index':jobs.index_once}[args.role]
    while not stopped.is_set():
        try:
            action()
            if args.role!='index':jobs.status(args.role,'ready')
        except Exception as exc:
            logging.exception('%s worker recovered from an iteration failure',args.role)
            jobs.status(args.role,'error',str(exc)[:1000])
        if args.once:break
        stopped.wait(1 if args.role=='scheduler' else .25)
    jobs.status(args.role,'stopped')


if __name__=='__main__':main()
