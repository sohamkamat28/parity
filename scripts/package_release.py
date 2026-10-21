"""Create a versioned source ZIP from tracked files, including the prebuilt frontend."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--version',default='2.0.0-dev.20261018');p.add_argument('--committed-source',action='store_true',help='Package exact HEAD blobs while preserving unrelated working-tree edits');args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9.-]+',args.version):p.error('Use a filename-safe version')
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
    if not args.committed_source and (git('diff','--name-only').strip() or git('diff','--cached','--name-only').strip()):p.error('Commit tracked changes before packaging so BUILD_INFO identifies the source exactly')
    names=git('ls-tree','-rz','--name-only','HEAD').decode().split('\0') if args.committed_source else git('ls-files','-z').decode().split('\0');prefix='parity-'+args.version
    output=ROOT/'outputs';output.mkdir(exist_ok=True);destination=output/(prefix+'.zip')
    info={'version':args.version,'commit':git('rev-parse','HEAD').decode().strip(),'branch':git('branch','--show-current').decode().strip(),'contains':'Tracked source, documentation, deterministic tests and prebuilt frontend; no runtime data or downloaded assets.'}
    count=0
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in names:
            if not name:continue
            path=Path(name)
            if any(part in ('.git','.venv','node_modules','.cache','data','model_cache','test-runtime') for part in path.parts):raise ValueError('Refusing tracked runtime files: '+name)
            if path.name in ('.env','automation-connections.json') or path.suffix in ('.db','.sqlite','.sqlite3','.gguf','.log','.pem','.key'):raise ValueError('Refusing private/runtime file: '+name)
            if path.parts[0]=='outputs':continue
            if args.committed_source:archive.writestr(prefix+'/'+path.as_posix(),git('show','HEAD:'+name))
            else:
                if not (ROOT/path).is_file():raise ValueError('Tracked source missing: '+name)
                archive.write(ROOT/path,prefix+'/'+path.as_posix())
            count+=1
        archive.writestr(prefix+'/BUILD_INFO.json',json.dumps(info,indent=2)+'\n')
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert prefix+'/frontend/dist/index.html' in archive.namelist()
    info.update(file=destination.name,sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),bytes=destination.stat().st_size,files=count+1)
    (output/(prefix+'.manifest.json')).write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
