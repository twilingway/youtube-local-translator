"""Actual moving-window neural diarization; session labels must survive overlaps."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np,soundfile as sf
from scipy.signal import resample_poly
from service.diarization import ConversationDiarizer
from service.config import ROOT
model=ConversationDiarizer();reports=[]
for name in ('1-two-speakers-en.wav','2-two-speakers-en.wav','3-two-speakers-en.wav'):
    audio,rate=sf.read(ROOT/'reports'/name,dtype='float32');audio=resample_poly(audio,16000,rate)
    if audio.ndim>1:audio=audio.mean(axis=1)
    registry=[];previous=[];rows=[]
    ends=list(range(20,len(audio)//16000,10))+[len(audio)/16000]
    for end in ends:
        start=max(0,end-30);clip=audio[round(start*16000):round(end*16000)]
        turns,seconds=model.diarize(clip,start,registry,previous)
        disagreements=0.;shared=0.
        for old in previous:
            for new in turns:
                amount=max(0,min(old['end'],new['end'])-max(old['start'],new['start']))
                if amount:shared+=amount;disagreements+=amount*(old['speaker']!=new['speaker'])
        rows.append({'window':[start,end],'compute_s':seconds,'bank_count':len(registry),'shared_s':shared,'changed_label_s':disagreements,'turns':turns})
        previous=turns
    report={'file':name,'known_speakers':2,'bank_count':len(registry),'rows':rows,'references_s':[x.get('reference_s',0) for x in registry]}
    reports.append(report);print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
(ROOT/'reports/conversation-diarizer-real.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
