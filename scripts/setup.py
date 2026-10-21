"""Reproducible native setup, shared by Windows and macOS/Linux launchers."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['postgresql','sqlite'],default='postgresql')
    parser.add_argument('--without-models',action='store_true')
    parser.add_argument('--without-browser',action='store_true')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,14):parser.error('Use Python 3.14 in a fresh .venv; existing environments are never replaced.')
    def run(*command):subprocess.run(command,cwd=ROOT,check=True)
    requirements='requirements-test.txt' if args.without_models else 'requirements-lock.txt'
    run(sys.executable,'-m','pip','install','--disable-pip-version-check','-r',str(ROOT/requirements))
    if args.profile=='postgresql':
        run(sys.executable,'-m','pip','install','-r',str(ROOT/'requirements-postgres.txt'))
    from parity import config
    # Child processes use the same explicit paths, including values loaded from .env.
    for key in ('PLAYWRIGHT_BROWSERS_PATH','PARITY_MODEL_CACHE','HF_HOME'):
        os.environ[key]=str(os.environ[key])
    if args.profile=='postgresql':run(sys.executable,str(ROOT/'scripts/database.py'))
    if not args.without_browser:run(sys.executable,'-m','playwright','install','chromium')
    if not args.without_models:
        os.environ['PARITY_OFFLINE']='0'
        run(sys.executable,str(ROOT/'scripts/cache_model.py'))
        run(sys.executable,str(ROOT/'scripts/setup_local_chat.py'))
    print('Setup complete. Start with: '+sys.executable+' run.py --profile '+args.profile+(' --without-models' if args.without_models else ''))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print('Setup stopped at exit code '+str(error.returncode)+'. Resolve the error above and rerun; verified downloads are reused.',file=sys.stderr)
        raise SystemExit(1)
