import concurrent.futures
import json
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
repo='Systran/faster-whisper-large-v3'
with urllib.request.urlopen('https://huggingface.co/api/models/'+repo) as response:metadata=json.load(response)
revision=metadata['sha']
files=[x['rfilename'] for x in metadata['siblings'] if x['rfilename'].endswith(('.json','.txt','.bin'))]
def fetch(name):
    target=ROOT/'models/whisper-quality'/name;target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return
    print('Downloading',name,flush=True)
    temporary=target.with_suffix(target.suffix+'.part')
    urllib.request.urlretrieve('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,temporary)
    temporary.replace(target);print('Ready',name,target.stat().st_size,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,files))
(ROOT/'reports/asr-quality-source.json').write_text(json.dumps({'repo':repo,'revision':revision,'files':files},indent=2),encoding='utf-8')
