import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from service.config import ROOT
from service.speakers import SpeakerEncoder
import soundfile as sf
from scipy.signal import resample_poly
import numpy as np
encoder=SpeakerEncoder();registry=[];results=[];embeddings=[]
for name in ('spk1_snt1.wav','spk1_snt2.wav','spk2_snt1.wav'):
    audio,rate=sf.read(ROOT/'reports/speaker-fixtures'/name)
    if audio.ndim>1:audio=audio.mean(axis=1)
    audio=resample_poly(audio,16000,rate).astype(np.float32)
    begin=time.perf_counter();embedding=encoder.encode(audio)
    speaker,similarity=encoder.assign(audio,registry)
    embeddings.append(embedding)
    results.append({'file':name,'speaker':speaker,'similarity':similarity,'seconds':time.perf_counter()-begin,'audio_s':len(audio)/16000})
report={'source':'official SpeechBrain real-human same/different speaker fixtures','results':results,
    'same_speaker_cosine':float(np.dot(embeddings[0],embeddings[1])),
    'different_speaker_cosine':float(np.dot(embeddings[0],embeddings[2]))}
report['passed']=results[0]['speaker']==results[1]['speaker'] and results[0]['speaker']!=results[2]['speaker']
(ROOT/'reports/speakers-real-fixtures.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2));assert report['passed']
