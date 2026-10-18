"""Download a pinned, CPU-only local model runtime. No account or API key needed."""
import hashlib, sys, urllib.request, zipfile, zlib, tarfile, platform
import os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from parity import config
CACHE=config.CACHE/'local-chat'
RUNTIME_URL='https://github.com/ggml-org/llama.cpp/releases/download/b11642/llama-b11642-bin-win-cpu-x64.zip'
RUNTIME_SHA='0145f328421169f96b79a42ee27df8403df2276f1d94c7a82fea61901acec38f'
MODEL_URL='https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf'
MODEL_SHA='6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def download(url,path,expected):
    if path.is_file() and digest(path)==expected:
        print(path.name+' verified',flush=True);return
    temporary=path.with_suffix(path.suffix+'.partial');done=0;printed=-1
    print('Downloading '+path.name,flush=True)
    with urllib.request.urlopen(url,timeout=60) as response,temporary.open('wb') as output:
        size=int(response.headers.get('Content-Length','0'))
        while block:=response.read(4*1024*1024):
            output.write(block);done+=len(block)
            progress=(done*10//size if size else done//(100*1024*1024))
            if progress!=printed:
                print(str(round(done/1024/1024))+' MiB downloaded',flush=True);printed=progress
    if digest(temporary)!=expected:raise RuntimeError('Download checksum mismatch: '+path.name)
    temporary.replace(path)

def install_mac_runtime(archive, runtime):
    # Never truncate a mapped Mach-O file: macOS caches signatures by inode.
    # Re-running setup must also leave an already running server intact.
    with tempfile.TemporaryDirectory(prefix='runtime-install-', dir=runtime.parent) as folder:
        staging=Path(folder)
        with tarfile.open(archive) as packaged:packaged.extractall(staging,filter='data')
        for source in staging.rglob('*'):
            destination=runtime/source.relative_to(staging)
            if source.is_symlink() or source.is_file():
                destination.parent.mkdir(parents=True,exist_ok=True)
                os.replace(source,destination)
            elif source.is_dir():destination.mkdir(parents=True,exist_ok=True)

def main():
    mac = sys.platform=='darwin' and platform.machine()=='arm64'
    if sys.platform!='win32' and not mac:raise SystemExit('Use a native llama-server on PATH or PARITY_LLAMA_SERVER, and place the verified GGUF in PARITY_CACHE_DIR/local-chat. Bundled runtime downloads support Windows x64 and macOS arm64.')
    CACHE.mkdir(parents=True,exist_ok=True)
    archive=CACHE/('runtime.tar.gz' if mac else 'runtime.zip')
    url='https://github.com/ggml-org/llama.cpp/releases/download/b11642/llama-b11642-bin-macos-arm64.tar.gz' if mac else RUNTIME_URL
    sha='9b08d85971cafd4fc41f3a07727e7a7ebf05c25c423ad556be300bcb7cf0df1d' if mac else RUNTIME_SHA
    download(url,archive,sha)
    runtime=CACHE/'runtime';runtime.mkdir(exist_ok=True)
    if mac:
        install_mac_runtime(archive,runtime)
    else:
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                destination=(runtime/info.filename).resolve()
                if not destination.is_relative_to(runtime.resolve()):raise RuntimeError('Unsafe runtime archive path')
                if destination.is_file() and destination.stat().st_size==info.file_size:
                    if zlib.crc32(destination.read_bytes())==info.CRC:continue
                zipped.extract(info,runtime)
    executable=next(runtime.rglob('llama-server' if mac else 'llama-server.exe'))
    probe=subprocess.run([str(executable),'--version'],capture_output=True,timeout=30)
    if probe.returncode:
        raise RuntimeError(f'Local answer runtime failed its startup check (exit {probe.returncode}). '
                           'Re-run setup before starting Parity; monitoring can run without models.')
    download(MODEL_URL,CACHE/'qwen2.5-1.5b-instruct-q4_k_m.gguf',MODEL_SHA)
    print('Free local chat is installed and checksums are verified.',flush=True)

if __name__=='__main__':main()
