"""CPU-only speaker-bank regression using authorized and public real WAV files."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly
from service.config import ROOT
from service.speakers import SpeakerEncoder
torch.set_num_threads(4);encoder=SpeakerEncoder('cpu');bank=[];rows=[]
items=[('listening/original-1.wav',0),('listening/original-2.wav',0),
       ('speaker-fixtures/spk1_snt1.wav',1),('speaker-fixtures/spk2_snt1.wav',2),
       ('listening/original-1.wav',0),('speaker-fixtures/spk1_snt2.wav',1),
       ('listening/original-2.wav',0),('speaker-fixtures/spk2_snt1.wav',2)]
for name,expected in items:
    audio,rate=sf.read(ROOT/'reports'/name,dtype='float32')
    if audio.ndim>1:audio=audio.mean(axis=1)
    audio=resample_poly(audio,16000,rate)
    speaker,score=encoder.assign(audio,bank,rows[-1]['id'] if rows else 0)
    rows.append({'file':name,'id':speaker,'expected_bank':expected,'similarity':score})
passed=all(row['id']==row['expected_bank'] for row in rows)
report={'kind':'CPU real audio bank regression, no ASR/TTS/tabCapture',
        'note':'The two user clips at cosine0.392 are deliberately accepted as one acoustic bank; this test alone does not verify their real-world identity.',
        'rows':rows,'bank_count':len(bank),'passed':passed}
out=ROOT/'reports/player-042';out.mkdir(exist_ok=True)
(out/'voice-bank.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report),flush=True);assert passed
