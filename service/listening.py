"""Select short authorized listening excerpts from an in-memory PCM window."""
import base64,json
from pathlib import Path
import numpy as np
import soundfile as sf
from websockets.asyncio.client import connect
from .config import ROOT,config

async def select_samples(pcm,offset,url,title):
    cfg=config();cues=[];epoch='listening-source'
    async with connect('ws://127.0.0.1:8765/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=8*1024*1024) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}));ready=json.loads(await ws.recv())
        if ready.get('type')!='ready':raise RuntimeError(ready.get('message','ASR session unavailable'))
        await ws.send(json.dumps({'type':'reset','epoch':epoch,'mode':'subtitles','voice':'male','speakers':True}));await ws.recv()
        for first in range(0,len(pcm),160000):
            chunk=pcm[first:first+160000]
            await ws.send(json.dumps({'type':'pcm','epoch':epoch,'start':first/16000,'data':base64.b64encode(chunk.tobytes()).decode(),'final':True}))
            while True:
                message=json.loads(await ws.recv())
                if message['type']=='processing':continue
                if message['type']!='result':raise RuntimeError(message)
                cues.extend(message['cues']);break
    candidates=[c for c in cues if 2.8<=c['end']-c['start']<=10 and len(c['source'].split())>=5]
    groups={}
    for c in candidates:groups.setdefault(c['speaker_id'],[]).append(c)
    out=ROOT/'reports/listening';out.mkdir(exist_ok=True);selected=[]
    for speaker,items in sorted(groups.items(),key=lambda x:sum(c['end']-c['start'] for c in x[1]),reverse=True)[:2]:
        cue=max(items,key=lambda c:(c.get('speaker_similarity') or 0,c['end']-c['start']))
        left=max(0,round((cue['start']-.12)*16000));right=min(len(pcm),round((cue['end']+.12)*16000))
        name=f'original-{len(selected)+1}.wav';sf.write(out/name,pcm[left:right],16000,subtype='PCM_16')
        selected.append({'id':len(selected)+1,'anonymous_speaker_id':speaker,'file':name,'video_start':offset+left/16000,'video_end':offset+right/16000,'source':cue['source'],'translation':cue['text']})
    if not selected:raise RuntimeError('Не найдены чистые речевые фрагменты длительностью от 3 секунд.')
    report={'video':url,'title':title,'analysis_window_s':[offset,offset+len(pcm)/16000],'stored_samples':selected,
            'note':'Only user-requested short excerpts are saved. Bulk PCM was RAM-only. Anonymous IDs do not verify identity, age or gender.'}
    (out/'source.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
