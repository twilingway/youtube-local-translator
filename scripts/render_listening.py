"""Render real tab-captured actor references using Silero and native Qwen Base."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import soundfile as sf
import torch
from scipy.signal import correlate,find_peaks,resample_poly
from service.config import ROOT
from service.native_tts import NativeTTS

out=ROOT/'reports/listening';source=json.loads((out/'source.json').read_text(encoding='utf-8'))
phrase='Сегодня мы проверяем перевод видео на русский язык.'
voices=['eugene','aidar','xenia','baya','kseniya'];torch.set_num_threads(4)
model=torch.package.PackageImporter(str(ROOT/'models/silero.pt')).load_pickle('tts_models','model');model.to(torch.device('cuda'))
def pitch(audio,rate):
    if audio.ndim>1:audio=audio.mean(axis=1)
    audio=resample_poly(audio,16000,rate);values=[]
    for offset in range(0,len(audio)-800,320):
        frame=audio[offset:offset+800];frame=frame-frame.mean()
        if np.sqrt(np.mean(frame**2))<.008:continue
        ac=correlate(frame,frame,mode='full',method='fft')[799:];ac/=ac[0]+1e-9
        peaks,_=find_peaks(ac[32:247],height=.35)
        if len(peaks):values.append(16000/(32+peaks[np.argmax(ac[32+peaks])]))
    return float(np.median(values)) if values else None
def save(name,audio,rate):
    peak=float(np.max(np.abs(audio)));rms=float(np.sqrt(np.mean(audio**2)))
    gain=min(.89/max(peak,1e-9),.0794/max(rms,1e-9))
    sf.write(out/name,audio*gain,rate,subtype='PCM_16')
    return gain
presets={}
for voice in voices:
    with torch.inference_mode():audio=model.apply_tts(text=phrase,speaker=voice,sample_rate=24000).cpu().numpy()
    name=f'silero-{voice}.wav';gain=save(name,audio,24000);presets[voice]={'file':name,'pitch_hz':pitch(audio,24000),'gain':gain}
print('Five Silero comparison voices ready.',flush=True)
with NativeTTS(out/'actor-native.log') as native:
    for item in source['stored_samples']:
        reference=out/item['file'];original,rate=sf.read(reference,dtype='float32');f0=pitch(original,rate)
        best=min(voices,key=lambda voice:abs(np.log2((presets[voice]['pitch_hz'] or 150)/(f0 or 150))))
        item.update(phrase=phrase,silero_voices=presets,silero_selected=best,original_pitch_hz=f0)
        sf.write(out/f'actor-{item["id"]}-silero.wav',sf.read(out/presets[best]['file'])[0],24000)
        begin=time.perf_counter();audio,rate=native.synthesize(phrase,reference.read_bytes())
        item['qwen_s']=time.perf_counter()-begin;item['qwen_audio_s']=len(audio)/rate
        item['qwen_gain']=save(f'actor-{item["id"]}-qwen.wav',audio,rate)
        item['original_listening']=f'original-{item["id"]}-level.wav';save(item['original_listening'],original,16000)
        print(json.dumps({'actor':item['id'],'qwen_s':item['qwen_s'],'audio_s':item['qwen_audio_s'],'nearest_pitch_silero':best}),flush=True)
(out/'source.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
print('Actor listening samples ready.',flush=True)
