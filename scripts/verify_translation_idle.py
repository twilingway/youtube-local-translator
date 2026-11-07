"""Explicit cold-load regression on the project's isolated Ollama, no captured audio."""
import json,sys,time
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from service.config import ROOT,config
from service.engine import Engine

out=ROOT/'reports/player-045';out.mkdir(exist_ok=True)
with httpx.Client(base_url='http://127.0.0.1:11439',trust_env=False,timeout=180) as client:
    model=config()['translation_model']
    # Do not unload a translator while someone is watching a live session.
    metrics=client.get('http://127.0.0.1:8765/metrics',headers={'Authorization':'Bearer '+config()['token']}).json()
    assert not metrics['active'],'A translation session is active; cold test aborted'
    response=client.post('/api/generate',json={'model':model,'keep_alive':0});response.raise_for_status()
    assert not client.get('/api/ps').json()['models']
    engine=Engine.__new__(Engine);engine.http=client
    began=time.perf_counter();translated=engine.translate('I was happy. My father was proud of me.','en','female');cold=time.perf_counter()-began
    began=time.perf_counter();warm_translation=engine.translate('I made a mistake and then I went home.','en','female');warm=time.perf_counter()-began
    models=client.get('/api/ps').json()['models']
    assert len(models)==1 and int(models[0]['expires_at'][:4])>2100
    report={'kind':'real local Ollama unload then cold/warm Engine.translate, no audio/capture',
            'cold_s':cold,'warm_s':warm,'translation':translated,'warm_translation':warm_translation,
            'expires_at':models[0]['expires_at'],'size_vram':models[0]['size_vram'],'resident':True}
    (out/'translation-cold.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
