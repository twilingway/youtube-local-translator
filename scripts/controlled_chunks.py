"""Controlled real CUDA/translation/TTS comparison, using an existing public WAV.

The file is available up front: these are compute timings, not live viewing
latency. Warm each setting, shuffle repeated runs, save no new source audio.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=8766)
parser.add_argument('--repeats',type=int,default=5)
args=parser.parse_args()
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))
path=ROOT/'reports/english-fixture.wav'
audio,rate=sf.read(path)
if audio.ndim>1:audio=audio.mean(axis=1)
audio=resample_poly(audio,16000,rate)
pcm=(np.clip(audio,-1,1)*32767).astype('<i2')
out=ROOT/'reports/pipeline-032/controlled-chunks.json'

def gpu():
    return subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,utilization.gpu,clocks.sm,temperature.gpu',
        '--format=csv,noheader,nounits'],capture_output=True,text=True).stdout.strip()

report={'kind':'real CUDA ASR -> Ollama -> ECAPA -> Silero; same existing 10.8-second public English WAV, not live YouTube',
    'fixture':str(path),'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'input_s':len(pcm)/16000,
    'port':args.port,'repeats':args.repeats,'warmup_per_size':1,'seed':20261106,
    'settings':{'asr':'local full large-v3','beam_size':5,'temperature':0,'max_new_tokens':256,
        'overlap_s':1.5,'translation':cfg['translation_model'],'voice':'male','speakers':True,'tts':'Silero v5_6_ru 24kHz'},
    'gpu_before':gpu(),'runs':[],'limitations':['One short public English recording; no universal optimum or listening-quality claim.',
        'Input available up front. End-to-end timings exclude live capture accumulation.',
        'Main service remains loaded but its translation session is stopped; total VRAM includes both model instances and other applications.',
        'All results include local WS, ASR, translation, speaker assignment and WAV synthesis. No synthesis artifacts are written.']}

async def run(seconds,warmup,round_index):
    epoch=f'controlled-{seconds}-{round_index}-{warmup}'
    async with connect(f'ws://127.0.0.1:{args.port}/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=8*1024*1024) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}))
        ready=json.loads(await ws.recv())
        if ready.get('type')!='ready':raise RuntimeError(ready)
        await ws.send(json.dumps({'type':'reset','epoch':epoch,'mode':'both','voice':'male','speakers':True}))
        reset=json.loads(await ws.recv())
        if reset.get('type')!='reset':raise RuntimeError(reset)
        begin=time.perf_counter();first=None;packets=[];texts=[];tts_audio=0.;progress=[];virtual_available=0.;virtual_first=None
        for offset in range(0,len(pcm),seconds*16000):
            data=pcm[offset:offset+seconds*16000]
            await ws.send(json.dumps({'type':'pcm','epoch':epoch,'start':offset/16000,
                'data':base64.b64encode(data.tobytes()).decode(),'final':offset+len(data)>=len(pcm)}))
            while True:
                msg=json.loads(await asyncio.wait_for(ws.recv(),90))
                if msg['type']=='processing':progress.append({'stage':msg.get('stage'),'elapsed_s':msg.get('elapsed_s')});continue
                if msg['type']!='result':raise RuntimeError(msg)
                break
            elapsed=time.perf_counter()-begin
            virtual_available=max(virtual_available,(offset+len(data))/16000)+msg['process_s']
            if msg['cues'] and first is None:first=elapsed;virtual_first=virtual_available
            packets.append({k:msg[k] for k in ['start','end','process_s','asr_s','queue']})
            for cue in msg['cues']:
                wav=base64.b64decode(cue['audio'])
                if wav[:4]!=b'RIFF' or b'WAVE'!=wav[8:12]:raise RuntimeError('Invalid synthesized WAV')
                tts_audio+=cue['audio_s']
                texts.append({k:cue.get(k) for k in ['source','text','start','end','audio_s','translation_s','tts_s']})
        total=time.perf_counter()-begin
    return {'chunk_s':seconds,'warmup':warmup,'round':round_index,'elapsed_s':total,'first_cue_compute_s':first,
        'first_cue_live_estimate_s':virtual_first,'live_completion_estimate_s':virtual_available,
        'rtf':total/(len(pcm)/16000),'cue_count':len(texts),'tts_audio_s':tts_audio,'packets':packets,'cues':texts,'progress':progress,'gpu_after':gpu()}

async def main():
    sizes=[3,5,8,10]
    for seconds in sizes:
        row=await run(seconds,True,-1);report['runs'].append(row)
        print(json.dumps({'warmup':seconds,'elapsed_s':round(row['elapsed_s'],3)}),flush=True)
    rng=random.Random(report['seed'])
    for i in range(args.repeats):
        order=sizes.copy();rng.shuffle(order)
        for seconds in order:
            row=await run(seconds,False,i);report['runs'].append(row)
            out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'round':i+1,'chunk_s':seconds,'elapsed_s':round(row['elapsed_s'],3),'first_cue_compute_s':round(row['first_cue_compute_s'] or 0,3)}),flush=True)
    report['summary']=[]
    for seconds in sizes:
        rows=[r for r in report['runs'] if not r['warmup'] and r['chunk_s']==seconds]
        values=[r['elapsed_s'] for r in rows]
        report['summary'].append({'chunk_s':seconds,'n':len(rows),'median_s':statistics.median(values),
            'min_s':min(values),'max_s':max(values),'first_cue_compute_median_s':statistics.median(r['first_cue_compute_s'] for r in rows),
            'first_cue_live_estimate_median_s':statistics.median(r['first_cue_live_estimate_s'] for r in rows),
            'tts_audio_s_min':min(r['tts_audio_s'] for r in rows),'tts_audio_s_max':max(r['tts_audio_s'] for r in rows),
            'cue_count_min':min(r['cue_count'] for r in rows),'cue_count_max':max(r['cue_count'] for r in rows)})
    report['gpu_after']=gpu()
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False),flush=True)

asyncio.run(main())
