"""Local anonymous speaker clustering; does not identify a person's real name."""
import time
import os
import numpy as np
import io
import soundfile as sf
from .config import ROOT

VOICES=('eugene','aidar','xenia','baya','kseniya')
VOICE_NAMES={'eugene':'Мужской 1','aidar':'Мужской 2','xenia':'Женский 1','baya':'Женский 2','kseniya':'Женский 3'}

class SpeakerEncoder:
    def __init__(self,device='cuda:0'):
        import torch
        # SpeechBrain's process-wide JIT quirk breaks the packaged Silero model
        # with PyTorch2.11. Preserve the defaults used by the TTS engine.
        disabled=set(filter(None,os.environ.get('SB_DISABLE_QUIRKS','').split(',')))
        disabled.update(('disable_jit_profiling','allow_tf32'))
        os.environ['SB_DISABLE_QUIRKS']=','.join(sorted(disabled))
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
        path=ROOT/'models/speakers'
        self.torch=torch;self.device=device
        self.model=EncoderClassifier.from_hparams(source=str(path),savedir=str(ROOT/'.cache/speaker-runtime'),
            overrides={'pretrained_path':str(path)},run_opts={'device':device},local_strategy=LocalStrategy.COPY)

    def encode(self,audio):
        with self.torch.inference_mode():
            waveform=self.torch.from_numpy(np.asarray(audio,dtype=np.float32)).unsqueeze(0).to(self.device)
            value=self.model.encode_batch(waveform).flatten().cpu().numpy()
        return value/(np.linalg.norm(value)+1e-9)

    def assign(self,audio,registry,last=0):
        seconds=len(audio)/16000
        if seconds<.7:
            return last,None
        embedding=self.encode(audio)
        scores=[max(float(np.dot(embedding,v)) for v in [item['centroid'],*item.get('profiles',[])]) for item in registry]
        best=int(np.argmax(scores)) if scores else 0
        similarity=scores[best] if scores else None
        novel=seconds>=1.5 and similarity is not None and similarity<.28
        distinct_short=seconds>=.9 and similarity is not None and similarity<.12
        if not registry or ((novel or distinct_short) and len(registry)<8):
            best=len(registry);registry.append({'centroid':embedding,'profiles':[],'seconds':seconds})
        elif similarity is not None and similarity>=.35:
            item=registry[best]
            profiles=item.setdefault('profiles',[])
            if similarity<.8 and seconds>=1.5:profiles.append(embedding.copy());profiles[:]=profiles[-6:]
        if similarity is not None and similarity>.5 and best<len(registry):
            item=registry[best];weight=min(seconds,6)/min(item['seconds']+seconds,60)
            centroid=(1-weight)*item['centroid']+weight*embedding
            item['centroid']=centroid/(np.linalg.norm(centroid)+1e-9);item['seconds']+=seconds
        return best,similarity

def voice_for(speaker,profile):
    order=('xenia','kseniya','baya','eugene') if profile=='female' else ('eugene','aidar','xenia','baya')
    return order[speaker%len(order)]

def split_mixed_words(words,audio,audio_start,encoder):
    """Reject a mixed voice reference before freezing it; split only at whole words."""
    if len(words)<4 or words[-1]['end']-words[0]['start']<2.4:return [words]
    left=max(0,round((words[0]['start']-audio_start)*16000))
    right=min(len(audio),round((words[-1]['end']-audio_start)*16000))
    clip=audio[left:right]
    if len(clip)<38400:return [words]
    first=encoder.encode(clip[:17600]);last=encoder.encode(clip[-17600:])
    if float(np.dot(first,last))>=.2:return [words]
    mid=(words[0]['start']+words[-1]['end'])/2
    eligible=[i for i in range(1,len(words)) if words[i]['start']-words[0]['start']>=.7 and words[-1]['end']-words[i]['start']>=.7]
    if not eligible:return [words]
    gaps=[i for i in eligible if words[i]['start']-words[i-1]['end']>=.16]
    boundary=min(gaps or eligible,key=lambda i:abs(words[i]['start']-mid))
    return [words[:boundary],words[boundary:]]

def retain_reference(item,audio):
    """Collect a bounded reference in RAM; freeze once selected, across all cues."""
    if item.get('reference'):return item['reference']
    audio=np.asarray(audio,dtype=np.float32)
    if len(audio)<12800 or not np.all(np.isfinite(audio)):return None
    # Remove silent edges in 20 ms blocks, without altering pitch or speed.
    size=len(audio)//320
    frames=audio[:size*320].reshape(-1,320)
    threshold=max(.003,float(np.sqrt(np.mean(audio**2)))*.15)
    speech=np.flatnonzero(np.sqrt(np.mean(frames**2,axis=1))>threshold)
    if not len(speech):return None
    clip=audio[max(0,(speech[0]-5)*320):min(len(audio),(speech[-1]+6)*320)]
    if not item.get('reference_preview') and len(clip)>=12800:
        preview=io.BytesIO();sf.write(preview,clip[:96000],16000,format='WAV',subtype='PCM_16')
        item['reference_preview']=preview.getvalue();item['reference_preview_s']=min(len(clip),96000)/16000
    collected=np.concatenate((item.get('reference_pending',np.empty(0,dtype=np.float32)),clip))[:96000]
    item['reference_pending']=collected
    if len(collected)<38400:return item.get('reference_preview')
    buf=io.BytesIO();sf.write(buf,collected,16000,format='WAV',subtype='PCM_16')
    item['reference']=buf.getvalue();item['reference_s']=len(collected)/16000
    item.pop('reference_pending',None)
    return item['reference']
