"""Run deterministic suites; --postgres adds isolated database acceptance."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--postgres',action='store_true');args,extra=p.parse_known_args()
from parity import config
if args.postgres:
    from parity.deployment import configure_database
    os.environ.setdefault('PARITY_TEST_DATABASE_URL',configure_database(start=False))
raise SystemExit(subprocess.run([sys.executable,'-m','pytest','-q','--tb=short',*extra],cwd=ROOT,env=os.environ.copy()).returncode)
