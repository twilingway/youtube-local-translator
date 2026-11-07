"""Explicit local TTS benchmark, sequential models, same text matrix, warmed runs."""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from service.config import ROOT
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import soundfile as sf
import torch

parser=argparse.ArgumentParser();parser.add_argument('--backend',choices=['silero','qwen-python'],required=True);parser.add_argument('--repeats',type=int,default=3);args=parser.parse_args()
out=ROOT/'reports/tts-comparison';out.mkdir(exist_ok=True)
texts=[
    'Сегодня мы проверяем перевод видео на русский язык.',
    'Каждый участник разговора должен говорить своим постоянным голосом, а перевод должен звучать плавно, сохранять смысл и не обрываться на границе фрагментов.'
]
reference='Это короткий образец голоса для проверки устойчивости тембра при русском синтезе речи.'
voices=['male','female'];torch.set_num_threads(4);torch.manual_seed(20261106)
report={'backend':args.backend,'texts':texts,'runs':[],'source':'explicit synthesized benchmark WAV, not source recordings','repeats':args.repeats,
        'gpu_before':subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True).stdout.strip()}
begin=time.perf_counter()
if args.backend=='silero':
    model=torch.package.PackageImporter(str(ROOT/'models/silero.pt')).load_pickle('tts_models','model');model.to(torch.device('cuda'))
    def synth(text,voice):return model.apply_tts(text=text,speaker='eugene' if voice=='male' else 'xenia',sample_rate=24000).cpu().numpy(),24000
else:
    from qwen_tts import Qwen3TTSModel
    model=Qwen3TTSModel.from_pretrained(str(ROOT/'models/qwen3-tts'),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa')
    def synth(text,voice):
        wavs,rate=model.generate_custom_voice(text=text,language='Russian',speaker='Ryan' if voice=='male' else 'Vivian',max_new_tokens=512,do_sample=False)
        return wavs[0],rate
report['load_s']=time.perf_counter()-begin
for voice in voices:
    with torch.inference_mode():audio,rate=synth(reference,voice)
    if args.backend=='silero':sf.write(out/f'reference-{voice}.wav',audio,rate)
    print(json.dumps({'backend':args.backend,'warmup':voice}),flush=True)
rng=random.Random(20261106)
for repeat in range(args.repeats):
    order=[(i,v) for i in range(len(texts)) for v in voices];rng.shuffle(order)
    for i,voice in order:
        torch.cuda.synchronize();begin=time.perf_counter()
        with torch.inference_mode():audio,rate=synth(texts[i],voice)
        torch.cuda.synchronize();elapsed=time.perf_counter()-begin
        row={'round':repeat+1,'text_index':i,'voice':voice,'elapsed_s':elapsed,'audio_s':len(audio)/rate,'rtf':elapsed/(len(audio)/rate)}
        report['runs'].append(row)
        if repeat==0:sf.write(out/f'{args.backend}-{i}-{voice}.wav',audio,rate)
        (out/f'{args.backend}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'backend':args.backend,**row}),flush=True)
report['summary']=[{'text_index':i,'voice':v,
    'median_s':statistics.median(r['elapsed_s'] for r in report['runs'] if r['text_index']==i and r['voice']==v),
    'median_audio_s':statistics.median(r['audio_s'] for r in report['runs'] if r['text_index']==i and r['voice']==v),
    'median_rtf':statistics.median(r['rtf'] for r in report['runs'] if r['text_index']==i and r['voice']==v)} for i in range(len(texts)) for v in voices]
(out/f'{args.backend}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'backend':args.backend,'summary':report['summary']}),flush=True)
