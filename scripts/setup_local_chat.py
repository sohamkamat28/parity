"""Download a pinned, CPU-only local model runtime. No account or API key needed."""
import hashlib, sys, urllib.request, zipfile, zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.cache'/'local-chat'
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

def main():
    if sys.platform!='win32':raise SystemExit('Bundled local chat setup currently targets Windows x64.')
    CACHE.mkdir(parents=True,exist_ok=True)
    archive=CACHE/'runtime.zip';download(RUNTIME_URL,archive,RUNTIME_SHA)
    runtime=CACHE/'runtime';runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            destination=(runtime/info.filename).resolve()
            if not destination.is_relative_to(runtime.resolve()):raise RuntimeError('Unsafe runtime archive path')
            if destination.is_file() and destination.stat().st_size==info.file_size:
                if zlib.crc32(destination.read_bytes())==info.CRC:continue
            zipped.extract(info,runtime)
    download(MODEL_URL,CACHE/'qwen2.5-1.5b-instruct-q4_k_m.gguf',MODEL_SHA)
    print('Free local chat is installed and checksums are verified.',flush=True)

if __name__=='__main__':main()
