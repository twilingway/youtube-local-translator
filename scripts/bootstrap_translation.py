"""Download the translation model using a temporary, project-owned Ollama."""
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))
with socket.socket() as sock:
    try:sock.bind(('127.0.0.1',11439))
    except OSError:raise SystemExit('Port 11439 occupied; no existing service modified')
profile=ROOT/'.runtime/ollama-profile';profile.mkdir(exist_ok=True)
env={**os.environ,'USERPROFILE':str(profile),'OLLAMA_MODELS':str(ROOT/'models/ollama'),
    'OLLAMA_HOST':'127.0.0.1:11439','OLLAMA_NO_CLOUD':'1','OLLAMA_NOHISTORY':'1'}
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with (ROOT/'reports/ollama-pull.log').open('w',encoding='utf-8') as log:
    child=subprocess.Popen([str(ROOT/'.runtime/ollama/ollama.exe'),'serve'],env=env,stdout=log,stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        for _ in range(40):
            try:
                with opener.open('http://127.0.0.1:11439/api/version',timeout=1) as r:print(r.read().decode(),flush=True)
                break
            except OSError:time.sleep(.5)
        req=urllib.request.Request('http://127.0.0.1:11439/api/pull',data=json.dumps({'model':cfg['translation_model'],'stream':True}).encode(),headers={'Content-Type':'application/json'})
        last=0
        with opener.open(req,timeout=600) as response:
            for line in response:
                msg=json.loads(line)
                if 'error' in msg:raise RuntimeError(msg['error'])
                if time.monotonic()-last>5 or msg.get('status')=='success':
                    print(json.dumps(msg),flush=True);last=time.monotonic()
        with opener.open('http://127.0.0.1:11439/api/tags') as response:tags=json.load(response)
        (ROOT/'reports/translation-model.json').write_text(json.dumps(tags,indent=2),encoding='utf-8')
    finally:
        child.terminate();child.wait(timeout=15)
