"""Real GPU inference. Only explicit benchmark artifacts are written to reports/."""
import argparse
import json
import sys
import time
import subprocess
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from service.config import ROOT
import soundfile as sf
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('--qwen',action='store_true')
parser.add_argument('--audio',type=Path)
args=parser.parse_args()
gpu=[]
finished=threading.Event()
def monitor():
    while not finished.is_set():
        result=subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True)
        try: gpu.append([time.time(),*[int(x.strip()) for x in result.stdout.strip().split(',')]])
        except ValueError: pass
        finished.wait(.3)

thread=threading.Thread(target=monitor,daemon=True);thread.start()
texts=['Сегодня мы узнаем, как работает локальный перевод видео.','Нажмите кнопку, чтобы включить русские субтитры и озвучку.']
report={'backend':'qwen3-tts-0.6b' if args.qwen else 'silero-v5_6_ru','samples':[]}
try:
    import torch
    torch.set_num_threads(4)
    begin=time.perf_counter()
    if args.qwen:
        from qwen_tts import Qwen3TTSModel
        model=Qwen3TTSModel.from_pretrained(str(ROOT/'models/qwen3-tts'),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa')
        def synth(text,voice):
            wavs,rate=model.generate_custom_voice(text=text,language='Russian',speaker='Ryan' if voice=='male' else 'Vivian',max_new_tokens=512,do_sample=False)
            return wavs[0],rate
    else:
        from service.engine import Engine
        engine=Engine()
        synth=engine.synthesize
    report['load_s']=time.perf_counter()-begin
    for index,(text,voice) in enumerate((t,v) for t in texts for v in ['male','female']):
        torch.cuda.synchronize();begin=time.perf_counter()
        with torch.inference_mode(): audio,rate=synth(text,voice)
        torch.cuda.synchronize();elapsed=time.perf_counter()-begin
        path=ROOT/f'reports/{report["backend"]}-{index}.wav'
        sf.write(path,audio,rate)
        row=dict(text=text,voice=voice,seconds=elapsed,audio_s=len(audio)/rate,rtf=elapsed/(len(audio)/rate),artifact=str(path))
        report['samples'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    report['success']=True
    if args.audio and not args.qwen:
        from scipy.signal import resample_poly
        audio,rate=sf.read(args.audio)
        if audio.ndim>1:audio=audio.mean(axis=1)
        audio=resample_poly(audio,16000,rate).astype(np.float32)
        report['pipeline']=[]
        for offset in range(0,len(audio),80000):
            item=engine.process(audio[offset:offset+80000],offset/16000,'both','male')
            for cue in item['cues']: cue.pop('audio',None)
            report['pipeline'].append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
finally:
    finished.set();thread.join(2)
    report['gpu_samples']=gpu
    report['peak_total_vram_mib']=max((x[1] for x in gpu),default=None)
    (ROOT/f'reports/benchmark-{report["backend"]}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
