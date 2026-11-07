"""Fetch only short user-requested listening samples; bulk audio stays in RAM."""
import asyncio,base64,io,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf
from websockets.asyncio.client import connect
ROOT=Path(__file__).resolve().parent.parent
url='https://www.youtube.com/watch?v=ocGJWc2F1Yk'
out=ROOT/'reports/listening';out.mkdir(exist_ok=True)
command=[sys.executable,str(ROOT/'.runtime/ytdlp/yt-dlp'),'--dump-single-json','--skip-download','--no-playlist',
    '--js-runtimes','node','--proxy','','--cache-dir',str(ROOT/'.cache/ytdlp'),'-f','bestaudio',url]
temp=ROOT/'.runtime/ytdlp/tmp';temp.mkdir(exist_ok=True)
result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150,
    env={**os.environ,'TEMP':str(temp),'TMP':str(temp)},cwd=ROOT)
if result.returncode:
    (out/'source-error.txt').write_text(result.stderr,encoding='utf-8')
    raise RuntimeError('YouTube media extraction failed; source-error.txt contains diagnostics')
data=json.loads(result.stdout);media=data['url']
print(json.dumps({'video':data['id'],'title':data.get('title'),'codec':data.get('acodec')}),flush=True)
# A short analysis window is streamed as PCM to RAM, never written to disk.
offset=30;duration=90
ff=subprocess.run(['ffmpeg','-v','error','-ss',str(offset),'-i',media,'-t',str(duration),'-vn','-ac','1','-ar','16000','-f','s16le','pipe:1'],capture_output=True,timeout=150)
if ff.returncode:raise RuntimeError('Audio sample stream failed')
pcm=np.frombuffer(ff.stdout,dtype='<i2');print(json.dumps({'analysis_audio_s':len(pcm)/16000,'stored_source_audio':False}),flush=True)
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))

async def analyze():
    cues=[];epoch='listening-source'
    async with connect('ws://127.0.0.1:8765/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=8*1024*1024) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}));ready=json.loads(await ws.recv())
        if ready.get('type')!='ready':raise RuntimeError(ready)
        await ws.send(json.dumps({'type':'reset','epoch':epoch,'mode':'subtitles','voice':'male','speakers':True}));await ws.recv()
        for first in range(0,len(pcm),160000):
            chunk=pcm[first:first+160000]
            await ws.send(json.dumps({'type':'pcm','epoch':epoch,'start':first/16000,'data':base64.b64encode(chunk.tobytes()).decode(),'final':True}))
            while True:
                message=json.loads(await ws.recv())
                if message['type']=='processing':continue
                if message['type']!='result':raise RuntimeError(message)
                cues.extend(message['cues']);break
    candidates=[c for c in cues if 4<=c['end']-c['start']<=10 and len(c['source'].split())>=7]
    groups={}
    for c in candidates:groups.setdefault(c['speaker_id'],[]).append(c)
    selected=[]
    for speaker,items in sorted(groups.items(),key=lambda x:sum(c['end']-c['start'] for c in x[1]),reverse=True)[:2]:
        cue=max(items,key=lambda c:(c.get('speaker_similarity') or 0,c['end']-c['start']))
        left=max(0,round((cue['start']-.12)*16000));right=min(len(pcm),round((cue['end']+.12)*16000))
        name=f'original-{len(selected)+1}.wav';sf.write(out/name,pcm[left:right],16000,subtype='PCM_16')
        selected.append({'id':len(selected)+1,'anonymous_speaker_id':speaker,'file':name,'video_start':offset+left/16000,'video_end':offset+right/16000,'source':cue['source'],'translation':cue['text']})
    report={'video':url,'title':data.get('title'),'analysis_window_s':[offset,offset+len(pcm)/16000],'stored_samples':selected,
            'note':'Only selected short excerpts saved at the user request. Anonymous clustering is not identity/age/gender verification.'}
    (out/'source.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'selected':selected},ensure_ascii=True),flush=True)
asyncio.run(analyze())
