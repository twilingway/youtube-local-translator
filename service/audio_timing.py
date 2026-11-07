"""Fit whole synthesized speech to a source interval, preserving pitch and words."""
import os,shutil,subprocess
import numpy as np

def fit_speech(audio,rate,seconds):
    audio=np.asarray(audio,dtype=np.float32)
    raw_s=len(audio)/rate
    size=max(1,round(rate*.01));count=len(audio)//size
    if count:
        frames=audio[:count*size].reshape(-1,size)
        threshold=max(.002,float(np.sqrt(np.mean(audio**2)))*.07)
        active=np.flatnonzero(np.sqrt(np.mean(frames**2,axis=1))>threshold)
        if len(active):
            left=max(0,(active[0]-4)*size);right=min(len(audio),(active[-1]+5)*size)
            audio=audio[left:right]
    clean_s=len(audio)/rate;budget=max(.12,float(seconds)-.05)
    tempo=max(1.,clean_s/budget)
    if tempo>1.015:
        executable=shutil.which('ffmpeg')
        if not executable:raise RuntimeError('Для подгонки русской речи нужен FFmpeg в PATH.')
        original=audio
        for _ in range(2):
            remaining=tempo;filters=[]
            while remaining>2:filters.append('atempo=2');remaining/=2
            filters.append(f'atempo={remaining:.8f}')
            result=subprocess.run([executable,'-hide_banner','-loglevel','error','-f','f32le','-ar',str(rate),'-ac','1','-i','pipe:0',
                '-af',','.join(filters),'-f','f32le','pipe:1'],input=original.astype('<f4').tobytes(),capture_output=True,timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if result.returncode:raise RuntimeError('FFmpeg не смог подогнать темп речи: '+result.stderr.decode(errors='replace')[:150])
            audio=np.frombuffer(result.stdout,dtype='<f4').copy()
            if len(audio)/rate<=seconds+.01:break
            tempo*=len(audio)/rate/budget
        if not len(audio) or len(audio)/rate>seconds+.04:
            raise RuntimeError('Не удалось вместить озвучку в реплику без обрезания слов.')
    return audio,{'native_audio_s':raw_s,'trimmed_s':max(0,raw_s-clean_s),'tempo':tempo,
                  'target_audio_s':float(seconds),'timing_error_s':max(0,len(audio)/rate-seconds)}
