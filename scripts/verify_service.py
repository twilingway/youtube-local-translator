"""Real WebSocket + GPU path using an explicitly supplied audio fixture."""
import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from websockets.asyncio.client import connect
ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('audio',type=Path)
parser.add_argument('--port',type=int,default=8765)
parser.add_argument('--output',default='reports/websocket-real-fixture.json')
parser.add_argument('--chunk-seconds',type=int,choices=(3,5,8,10),default=5)
args=parser.parse_args()
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))

async def main():
    audio,rate=sf.read(args.audio)
    if audio.ndim>1:audio=audio.mean(axis=1)
    audio=resample_poly(audio,16000,rate)
    pcm=(np.clip(audio,-1,1)*32767).astype('<i2')
    report={'fixture':str(args.audio),'input_s':len(pcm)/16000,'chunk_seconds':args.chunk_seconds,'source':'explicit audio fixture; not tabCapture','results':[],'progress':[]}
    async with connect(f'ws://127.0.0.1:{args.port}/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=8*1024*1024) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}))
        first=json.loads(await ws.recv())
        if first.get('type')!='ready':raise SystemExit(first.get('message',str(first)))
        await ws.send(json.dumps({'type':'reset','epoch':'real-fixture','mode':'both','voice':'male'}))
        assert json.loads(await ws.recv())['type']=='reset'
        chunk=args.chunk_seconds*16000
        count=(len(pcm)+chunk-1)//chunk
        start=time.perf_counter()
        for offset in range(0,len(pcm),chunk):
            await ws.send(json.dumps({'type':'pcm','epoch':'real-fixture','start':offset/16000,
                'data':base64.b64encode(pcm[offset:offset+chunk].tobytes()).decode(), 'final':offset+chunk>=len(pcm)}))
        while len(report['results'])<count:
            msg=json.loads(await asyncio.wait_for(ws.recv(),120))
            if msg['type']=='processing':report['progress'].append(msg);continue
            if msg['type']!='result':raise RuntimeError(msg)
            index=len(report['results'])
            for i,cue in enumerate(msg['cues']):
                if 'audio' in cue:
                    wav=base64.b64decode(cue.pop('audio'))
                    out=ROOT/f'reports/{Path(args.output).stem}-{index}-{i}.wav';out.write_bytes(wav)
                    cue['artifact']=str(out);cue['wav_bytes']=len(wav)
            report['results'].append(msg)
        report['elapsed_s']=time.perf_counter()-start
    (ROOT/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

asyncio.run(main())
