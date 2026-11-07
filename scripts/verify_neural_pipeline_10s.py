"""Real GPU pipeline with 10-second packets; all input is available up front."""
import asyncio,base64,json,sys,time,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np,soundfile as sf
from scipy.signal import resample_poly
from websockets.asyncio.client import connect
from service.config import ROOT,config
parser=argparse.ArgumentParser();parser.add_argument('--chunk-seconds',type=int,choices=(5,10),default=10);parser.add_argument('--quality-minute',action='store_true');parser.add_argument('--speaker-count',type=int,default=0);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--report-folder',choices=('player-043','player-044','player-045','player-046'));parser.add_argument('--realtime',action='store_true');args=parser.parse_args()

async def main():
    names=['spk1_snt1.wav','spk2_snt1.wav','spk1_snt2.wav','spk2_snt1.wav','spk1_snt1.wav']*args.repeats
    clips=[];windows=[];offset=0
    for name in names:
        a,r=sf.read(ROOT/'reports/speaker-fixtures'/name,dtype='float32');a=resample_poly(a,16000,r)
        clip=np.concatenate((a,np.zeros(6400,dtype=np.float32)));clips.append(clip)
        windows.append((offset,offset+len(clip)/16000));offset+=len(clip)/16000
    audio=np.concatenate(clips);cfg=config();results=[];cues=[]
    folder=args.report_folder or ('player-044' if args.quality_minute else 'player-043');out=ROOT/'reports'/folder;out.mkdir(exist_ok=True)
    async with connect('ws://127.0.0.1:8765/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None,max_size=16*1048576) as ws:
        await ws.send(json.dumps({'type':'auth','token':cfg['token']}));assert json.loads(await ws.recv())['type']=='ready'
        await ws.send(json.dumps({'type':'reset','epoch':'neural10','mode':'both','voice':'male','speakerCount':args.speaker_count,'qualityMinute':args.quality_minute}));assert json.loads(await ws.recv())['type']=='reset'
        began=time.perf_counter()
        size=args.chunk_seconds*16000
        for i in range(0,len(audio)+1,size):
            chunk=audio[i:i+size]
            if args.realtime:await asyncio.sleep(max(0,(i+len(chunk))/16000-(time.perf_counter()-began)))
            msg={'type':'pcm' if len(chunk) else 'flush','epoch':'neural10','start':i/16000,'final':True}
            if len(chunk):msg['data']=base64.b64encode((np.clip(chunk,-1,1)*32767).astype('<i2').tobytes()).decode()
            await ws.send(json.dumps(msg))
            while True:
                result=json.loads(await asyncio.wait_for(ws.recv(),120))
                if result['type']=='processing':continue
                assert result['type']=='result',result
                break
            for k,cue in enumerate(result['cues']):
                p=out/f'neural{args.chunk_seconds}-{i//size}-{k}.wav'
                p.write_bytes(base64.b64decode(cue.pop('audio')));cue['artifact']=str(p);cues.append(cue)
            result['available_at_s']=time.perf_counter()-began
            results.append(result)
        await ws.send(json.dumps({'type':'flush','epoch':'neural10'}))
        while True:
            final=json.loads(await asyncio.wait_for(ws.recv(),120))
            if final['type']=='processing':continue
            assert final['type']=='result',final
            for k,cue in enumerate(final['cues']):
                p=out/f'neural{args.chunk_seconds}-final-{k}.wav';p.write_bytes(base64.b64decode(cue.pop('audio')));cue['artifact']=str(p);cues.append(cue)
            final['available_at_s']=time.perf_counter()-began;results.append(final);break
        seconds=time.perf_counter()-began
    ids=[]
    for a,b in windows:
        votes={}
        for c in cues:
            amount=max(0,min(b,c['end'])-max(a,c['start']))
            if amount:votes[c['speaker_id']]=votes.get(c['speaker_id'],0)+amount
        ids.append(max(votes,key=votes.get) if votes else None)
    identity=ids[0]!=ids[1] and None not in ids and all(v==ids[0 if i%5 in (0,2,4) else 1] for i,v in enumerate(ids))
    available=0.;required_buffer=0.;first_audio=None
    for result in results:
        available=max(available,result['end'])+result['process_s']
        if result['cues'] and first_audio is None:first_audio=available
        for cue in result['cues']:required_buffer=max(required_buffer,available-cue['start'])
    report={'kind':'real local ASR/diarization/translation/Qwen/FFmpeg via WS, prerecorded input '+('paced in real time' if args.realtime else 'available up front')+'; not tabCapture','realtime':args.realtime,'chunk_seconds':args.chunk_seconds,'quality_minute':args.quality_minute,'speaker_count':args.speaker_count,
            'input_s':offset,'compute_s':sum(r['process_s'] for r in results) if args.realtime else seconds,'wall_s':seconds,
            'rtf':(sum(r['process_s'] for r in results) if args.realtime else seconds)/offset,'ids':ids,'same_different_pass':identity,
            'all_original':all(c['voice_source']=='original' for c in cues),'all_fitted':all(c['audio_s']<=c.get('audio_deadline',c['end'])-c['start']+.04 for c in cues),
            'first_audio_live_estimate_s':first_audio,'required_buffer_estimate_s':required_buffer,
            'max_tempo':max(c['tempo'] for c in cues),'median_tempo':float(np.median([c['tempo'] for c in cues])),
            'p90_tempo':float(np.quantile([c['tempo'] for c in cues],.9)),'shortened_count':sum(bool(c.get('shortened_for_dubbing')) for c in cues),'results':results}
    if args.realtime:
        report['required_delay_measured_s']=max((r['available_at_s']-cue['start'] for r in results for cue in r['cues']),default=0)
        position=0.;ready=0.;playing=False;started=False;pauses=0;first=None;j=0
        for wall in np.arange(0,seconds+.05,.05):
            while j<len(results) and results[j]['available_at_s']<=wall:
                ready=max(ready,results[j]['readyThrough']);j+=1
            head=min(offset,wall);all_done=j==len(results)
            if not started and head>=60 and ready>=min(head,20):started=playing=True;first=float(wall)
            elif playing and ready-position<.3 and not all_done:playing=False;pauses+=1
            elif started and not playing and (ready-position>=8 or all_done):playing=True
            if playing:position=min(ready,position+.05)
        report['readiness_simulation']={'kind':'numeric 1x playback readiness simulation, not browser playback','first_start_s':first,'underruns':pauses,'position_s':position}
    folder=args.report_folder or ('player-044' if args.quality_minute else 'player-043');(ROOT/'reports'/folder).mkdir(exist_ok=True)
    (ROOT/f'reports/{folder}/neural-pipeline-{args.chunk_seconds}s.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}),flush=True)
    assert identity and report['all_original'] and report['all_fitted']

asyncio.run(main())
