import concurrent.futures
import json
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
repo='speechbrain/spkrec-ecapa-voxceleb'
with urllib.request.urlopen('https://huggingface.co/api/models/'+repo) as response:metadata=json.load(response)
revision=metadata['sha']
files=[x['rfilename'] for x in metadata['siblings'] if x['rfilename'].endswith(('.json','.yaml','.ckpt','.txt'))]
jobs=[('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,ROOT/'models/speakers'/name) for name in files]
for name in ('spk1_snt1.wav','spk1_snt2.wav','spk2_snt1.wav'):
    jobs.append(('https://raw.githubusercontent.com/speechbrain/speechbrain/develop/tests/samples/ASR/'+name,ROOT/'reports/speaker-fixtures'/name))
def fetch(job):
    url,target=job;target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return
    print('Downloading',target.name,flush=True)
    temp=target.with_suffix(target.suffix+'.part');urllib.request.urlretrieve(url,temp);temp.replace(target)
    print('Ready',target.name,target.stat().st_size,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,jobs))
(ROOT/'reports/speaker-model-source.json').write_text(json.dumps({'repo':repo,'revision':revision,'files':files},indent=2),encoding='utf-8')
