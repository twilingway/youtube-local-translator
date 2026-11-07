"""Fetch official CUDA12.4 llama.cpp binaries + pinned Qwen3-TTS GGUF locally."""
import concurrent.futures
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
BASE=ROOT/'.runtime/tts-native';BASE.mkdir(parents=True,exist_ok=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def metadata(url):
    with opener.open(url,timeout=30) as r:return json.load(r)
release=metadata('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b12175')
assets=[a for a in release['assets'] if a['name'] in ('cudart-llama-bin-win-cuda-12.4-x64.zip',f'llama-{release["tag_name"]}-bin-win-cuda-12.4-x64.zip')]
if len(assets)!=2:raise RuntimeError('Official Windows CUDA12.4 bundle unavailable')
repo='ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF'
revision='ca27d74bc954b73dadab5b71ca265d87fc861a7c'
tree=metadata(f'https://huggingface.co/api/models/{repo}/tree/{revision}')
names=['Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf','mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf']
weights=[x for x in tree if x['path'] in names]
if len(weights)!=2:raise RuntimeError('Expected official GGUF files unavailable')
jobs=[]
for a in assets:
    jobs.append((a['browser_download_url'],BASE/a['name'],a['size'],a['digest'].removeprefix('sha256:')))
for w in weights:
    jobs.append((f'https://huggingface.co/{repo}/resolve/{revision}/{w["path"]}',ROOT/'models/qwen3-tts-gguf'/w['path'],w['size'],w['lfs']['oid']))

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(4*1024*1024):h.update(b)
    return h.hexdigest()

def fetch(job):
    url,path,size,digest=job;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size==size and sha(path)==digest:return
    part=path.with_suffix(path.suffix+'.part');start=part.stat().st_size if part.exists() else 0
    if start>size:raise RuntimeError('Unexpected partial size: '+path.name)
    print(json.dumps({'downloading':path.name,'bytes':size,'resume':start}),flush=True)
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-'} if start else {})
    with opener.open(req,timeout=90) as response:
        if start and (response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {start}-')):raise RuntimeError('Range resume rejected')
        with part.open('ab' if start else 'wb') as f:
            while chunk:=response.read(1024*1024):f.write(chunk)
    if part.stat().st_size!=size or sha(part)!=digest:raise RuntimeError('Checksum failed: '+path.name)
    part.replace(path);print(json.dumps({'ready':path.name,'sha256':digest}),flush=True)

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(fetch,jobs))
destination=(BASE/release['tag_name']).resolve();destination.mkdir(exist_ok=True)
for a in assets:
    with zipfile.ZipFile(BASE/a['name']) as archive:
        if archive.testzip():raise RuntimeError('Invalid zip CRC')
        for name in archive.namelist():
            if not (destination/name).resolve().is_relative_to(destination):raise RuntimeError('Unsafe zip path')
        archive.extractall(destination)
report={'release':release['tag_name'],'revision':revision,'repo':repo,'runtime':str(destination),
        'files':[{'path':str(p),'size':s,'sha256':h,'url':u} for u,p,s,h in jobs]}
(ROOT/'reports/native-tts-sources.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'ready':str(destination),'files':len(jobs)}),flush=True)
