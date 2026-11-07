"""Resume the official portable archive using bounded parallel HTTP ranges."""
import concurrent.futures
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
URL='https://github.com/ollama/ollama/releases/download/v0.40.15/ollama-windows-amd64.zip'
SIZE=1614941966
archive=ROOT/'.runtime/ollama.zip'
archive.parent.mkdir(parents=True,exist_ok=True)
start=archive.stat().st_size if archive.exists() else 0
if start>SIZE:raise RuntimeError('Unexpected archive size')
parts=ROOT/'.runtime/ollama-parts';parts.mkdir(exist_ok=True)
ranges=[(i,offset,min(offset+64*1024*1024,SIZE)-1) for i,offset in enumerate(range(start,SIZE,64*1024*1024))]
def download(item):
    i,first,last=item;out=parts/f'{first}-{last}.part'
    expected=last-first+1
    if out.exists() and out.stat().st_size==expected:return out
    print('Range',first,last,flush=True)
    request=urllib.request.Request(URL,headers={'Range':f'bytes={first}-{last}'})
    with urllib.request.urlopen(request,timeout=90) as response:
        if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {first}-{last}/{SIZE}':
            raise RuntimeError('Server did not honor HTTP Range')
        with out.open('wb') as f:
            while chunk:=response.read(1024*1024):f.write(chunk)
    if out.stat().st_size!=expected:raise RuntimeError('Incomplete range')
    print('Ready range',first,flush=True);return out
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:downloaded=list(pool.map(download,ranges))
with archive.open('ab') as target:
    for part in downloaded:
        with part.open('rb') as source:
            while chunk:=source.read(1024*1024):target.write(chunk)
if archive.stat().st_size!=SIZE:raise RuntimeError('Archive size mismatch')
destination=(ROOT/'.runtime/ollama').resolve();destination.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as z:
    if bad:=z.testzip():raise RuntimeError('CRC error: '+bad)
    for name in z.namelist():
        if not (destination/name).resolve().is_relative_to(destination):raise RuntimeError('Unsafe zip path')
    z.extractall(destination)
print('Ollama portable ready',flush=True)
