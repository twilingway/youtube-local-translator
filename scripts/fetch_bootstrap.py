"""Dependency-free model download, with all writes inside this project."""
import concurrent.futures
import json
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def fetch(url, target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        print('Exists:',target.name,flush=True)
        return
    temporary=target.with_suffix(target.suffix+'.part')
    print('Downloading:',url,flush=True)
    urllib.request.urlretrieve(url,temporary)
    temporary.replace(target)
    print('Ready:',target.name,target.stat().st_size,flush=True)

repo='dropbox-dash/faster-whisper-large-v3-turbo'
with urllib.request.urlopen('https://huggingface.co/api/models/'+repo) as response:
    metadata=json.load(response)
revision=metadata['sha']
files=[entry['rfilename'] for entry in metadata['siblings'] if entry['rfilename'].endswith(('.bin','.json','.txt'))]
jobs=[('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+f,ROOT/'models/whisper'/f) for f in files]
jobs.append(('https://models.silero.ai/models/tts/ru/v5_6_ru.pt',ROOT/'models/silero.pt'))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(lambda job:fetch(*job),jobs))
(ROOT/'reports/model-sources.json').write_text(json.dumps({'whisper':{'repo':repo,'revision':revision,'files':files},'silero':'https://models.silero.ai/models/tts/ru/v5_6_ru.pt'},indent=2),encoding='utf-8')
