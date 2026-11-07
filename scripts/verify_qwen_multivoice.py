"""Actual websocket/ASR/translation/Qwen with public, known same/different speakers."""
import asyncio,base64,json,sys,time,subprocess,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from websockets.asyncio.client import connect
from service.config import ROOT,config
parser=argparse.ArgumentParser();parser.add_argument('--repeats',type=int,default=1);args=parser.parse_args()

async def main():
    cfg=config();out=ROOT/'reports/qwen-integration';out.mkdir(exist_ok=True)
    names=['spk1_snt1.wav','spk2_snt1.wav','spk1_snt2.wav','spk2_snt1.wav','spk1_snt1.wav']*args.repeats
    report={'kind':'real public SpeechBrain same/different-speaker WAVs; websocket + local CUDA models, no tabCapture','results':[],'gpu':[],'source_windows':[]}
    async with connect('ws://127.0.0.1:8765/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=8*1024*1024) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}));assert json.loads(await ws.recv())['type']=='ready'
        await ws.send(json.dumps({'type':'reset','epoch':'multivoice','mode':'both','voice':'male'}));assert json.loads(await ws.recv())['type']=='reset'
        offset=0;began=time.perf_counter()
        for i,name in enumerate(names):
            audio,rate=sf.read(ROOT/'reports/speaker-fixtures'/name,dtype='float32')
            if audio.ndim>1:audio=audio.mean(axis=1)
            audio=resample_poly(audio,16000,rate)
            # A short source pause keeps whole words inside their known speaker turn.
            audio=np.concatenate((audio,np.zeros(6400,dtype=np.float32)))
            pcm=(np.clip(audio,-1,1)*32767).astype('<i2')
            report['source_windows'].append({'source':name,'start':offset,'end':offset+len(audio)/16000})
            await ws.send(json.dumps({'type':'pcm','epoch':'multivoice','start':offset,'final':True,'data':base64.b64encode(pcm.tobytes()).decode()}))
            progress=[]
            while True:
                message=json.loads(await asyncio.wait_for(ws.recv(),90))
                if message['type']=='processing':progress.append(message);continue
                assert message['type']=='result',message
                break
            for k,cue in enumerate(message['cues']):
                path=out/f'voice-{i}-{k}.wav';path.write_bytes(base64.b64decode(cue.pop('audio')));cue['artifact']=str(path)
            report['results'].append({'source':name,'progress':progress,**message})
            offset+=len(audio)/16000
            gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()
            report['gpu'].append(gpu)
        await ws.send(json.dumps({'type':'flush','epoch':'multivoice'}))
        while True:
            message=json.loads(await asyncio.wait_for(ws.recv(),90))
            if message['type']=='processing':continue
            assert message['type']=='result',message
            for k,cue in enumerate(message['cues']):
                path=out/f'voice-final-{k}.wav';path.write_bytes(base64.b64decode(cue.pop('audio')));cue['artifact']=str(path)
            report['results'].append({'source':'end-of-stream',**message});break
        report.update(input_s=offset,compute_s=time.perf_counter()-began)
    identities=[]
    cues=[cue for result in report['results'] for cue in result['cues']]
    for window in report['source_windows']:
        totals={}
        for cue in cues:
            overlap=max(0,min(cue['end'],window['end'])-max(cue['start'],window['start']))
            if overlap:totals[cue['speaker_id']]=totals.get(cue['speaker_id'],0)+overlap
        identities.append(max(totals,key=totals.get) if totals else None)
    report['dominant_ids']=identities
    report['same_different_pass']=identities[0]!=identities[1] and None not in identities and all(value==identities[0 if i%5 in (0,2,4) else 1] for i,value in enumerate(identities))
    cues=[cue for result in report['results'] for cue in result['cues']]
    report['qwen_only']=bool(cues) and all(c['tts_backend']=='qwen-native' for c in cues)
    report['all_original_references']=bool(cues) and all(c['voice_source']=='original' for c in cues)
    report['max_tempo']=max((c.get('tempo',1) for c in cues),default=1)
    report['max_timing_error_s']=max((c.get('timing_error_s',0) for c in cues),default=0)
    report['fitted_all']=bool(cues) and all(c['audio_s']<=c['end']-c['start']+.04 for c in cues)
    references={}
    for cue in cues:
        if cue.get('reference_id') and cue.get('reference_status')=='stable':references.setdefault(str(cue['speaker_id']),set()).add(cue['reference_id'])
    report['frozen_reference_ids']={key:sorted(value) for key,value in references.items()}
    report['two_frozen_original_refs']=len(references)>=2 and all(len(value)==1 for value in references.values())
    (out/'multivoice-real.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('results','gpu')},ensure_ascii=False),flush=True)
    assert report['same_different_pass'] and report['qwen_only'] and report['two_frozen_original_refs'] and report['all_original_references'] and report['fitted_all']

asyncio.run(main())
