"""Real CPU diarization IPC and event-loop responsiveness, no browser/capture."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np,soundfile as sf
from scipy.signal import resample_poly
from service.config import ROOT
from service.diarization_process import ConversationDiarizerProcess

async def main():
    model=ConversationDiarizerProcess();ticks=[];running=True
    async def heartbeat():
        while running:ticks.append(time.perf_counter());await asyncio.sleep(.02)
    task=asyncio.create_task(heartbeat())
    try:
        files=['spk1_snt1.wav','spk2_snt1.wav','spk1_snt2.wav','spk2_snt1.wav']*4
        clips=[];windows=[];offset=0
        for name in files:
            a,r=sf.read(ROOT/'reports/speaker-fixtures'/name,dtype='float32');a=resample_poly(a,16000,r)
            a=np.concatenate((a,np.zeros(6400,np.float32)));clips.append(a);windows.append((offset,offset+len(a)/16000));offset+=len(a)/16000
        audio=np.concatenate(clips);registry=[]
        turns,seconds=await asyncio.to_thread(model.diarize,audio,0,registry,[],2)
        first_ids=[max(turns,key=lambda t:max(0,min(b,t['end'])-max(a,t['start'])))['speaker'] for a,b in windows]
        assert len(registry)==2 and all(s==first_ids[i%4] for i,s in enumerate(first_ids)) and first_ids[0]!=first_ids[1]
        frozen=[v['reference'] for v in registry]
        clip,r=sf.read(ROOT/'reports/speaker-fixtures/spk1_snt1.wav',dtype='float32');clip=np.tile(resample_poly(clip,16000,r),6)
        single,single_seconds=await asyncio.to_thread(model.diarize,clip,100,registry,[],2)
        assert len(registry)==2 and {t['speaker'] for t in single}=={first_ids[0]}
        assert frozen==[v['reference'] for v in registry]
        report={'kind':'real sherpa CPU in owned subprocess, no GPU/capture','input_s':len(audio)/16000,
                'compute_s':seconds,'known_single_s':single_seconds,'ids':first_ids,'bank':len(registry),
                'single_known_ids':sorted({t['speaker'] for t in single}),'frozen_references':True,
                'heartbeat_samples':len(ticks),'max_heartbeat_gap_s':max(np.diff(ticks),default=0)}
        assert report['max_heartbeat_gap_s']<.5
        out=ROOT/'reports/player-046';out.mkdir(exist_ok=True);(out/'diarization-worker.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True)
    finally:
        running=False;await task;await asyncio.to_thread(model.close)

if __name__=='__main__':asyncio.run(main())
