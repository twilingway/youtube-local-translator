"""Project-local official yt-dlp binary for explicit short listening samples."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open('https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest',timeout=30) as r:release=json.load(r)
asset=next(a for a in release['assets'] if a['name']=='yt-dlp')
target=ROOT/'.runtime/ytdlp/yt-dlp';target.parent.mkdir(parents=True,exist_ok=True)
digest=asset['digest'].removeprefix('sha256:')
if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
    temp=target.with_suffix('.part')
    with op.open(asset['browser_download_url'],timeout=90) as r,temp.open('wb') as f:
        while block:=r.read(1024*1024):f.write(block)
    if hashlib.sha256(temp.read_bytes()).hexdigest()!=digest:raise RuntimeError('yt-dlp checksum mismatch')
    temp.replace(target)
(ROOT/'reports/ytdlp-source.json').write_text(json.dumps({'release':release['tag_name'],'url':asset['browser_download_url'],'sha256':digest},indent=2),encoding='utf-8')
print(json.dumps({'ready':str(target),'release':release['tag_name']}))
