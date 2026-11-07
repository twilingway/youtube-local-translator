"""Warm local CUDA Qwen3-TTS Base comparison through the official /tts API."""
import base64
import io
import json
import random
import secrets
import socket
import statistics
import subprocess
import time
from pathlib import Path

import httpx
import soundfile as sf

ROOT=Path(__file__).resolve().parent.parent
out=ROOT/'reports/tts-comparison';out.mkdir(exist_ok=True)
source=json.loads((ROOT/'reports/native-tts-sources.json').read_text())
runtime=Path(source['runtime']);model=ROOT/'models/qwen3-tts-gguf/Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf';projector=model.parent/'mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf'
with socket.socket() as check:check.bind(('127.0.0.1',8767))
key=secrets.token_urlsafe(32);keyfile=ROOT/'.runtime/tts-native/benchmark.key';keyfile.write_text(key,encoding='utf-8')
texts=json.loads((out/'silero.json').read_text(encoding='utf-8'))['texts']
refs={v:base64.b64encode((out/f'reference-{v}.wav').read_bytes()).decode() for v in ['male','female']}
report={'backend':'Qwen3-TTS-1.7B-Base-Q8_0 llama.cpp CUDA12.4','release':source['release'],'texts':texts,'runs':[],
        'reference':'synthetic Silero eugene/xenia reference, not original human speaker','source_recording':False,
        'notes':['Same exact texts as other TTS benchmarks; repeated-text cache effects are possible.',
                 'Base cloning versus preset CustomVoice are different tasks, not an isolated Base/non-Base architecture comparison.']}
flags=subprocess.CREATE_NO_WINDOW
process=None
log=(out/'native-server.log').open('w',encoding='utf-8')
try:
    begin=time.perf_counter()
    process=subprocess.Popen([str(runtime/'llama-server.exe'),'-m',str(model),'--mmproj',str(projector),
        '-ngl','999','--flash-attn','on','--ctx-size','2048','--parallel','1','--host','127.0.0.1','--port','8767',
        '--no-webui','--api-key-file',str(keyfile)],cwd=runtime,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    client=httpx.Client(base_url='http://127.0.0.1:8767',headers={'Authorization':'Bearer '+key,'Origin':'http://127.0.0.1:8767'},trust_env=False,timeout=180)
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('Native model exited; inspect native-server.log')
        try:
            if client.get('/health',timeout=1).status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(1)
    else:raise RuntimeError('Native startup timeout')
    report['load_s']=time.perf_counter()-begin
    def synth(text,voice):
        start=time.perf_counter()
        response=client.post('/tts',json={'input':text,'lang':'ru','speaker_ref_b64':refs[voice],
            'seed':20261106,'n_predict':512,'response_format':'wav','stream':False})
        response.raise_for_status();elapsed=time.perf_counter()-start
        wave,rate=sf.read(io.BytesIO(response.content))
        return elapsed,len(wave)/rate,response.content
    for voice in ['male','female']:
        elapsed,duration,_=synth('Проверяем устойчивый голос и локальный синтез речи.',voice)
        print(json.dumps({'native_warmup':voice,'elapsed_s':elapsed,'audio_s':duration}),flush=True)
    rng=random.Random(20261106)
    for repeat in range(3):
        pairs=[(i,v)for i in range(len(texts))for v in ['male','female']];rng.shuffle(pairs)
        for i,voice in pairs:
            elapsed,duration,wav=synth(texts[i],voice)
            row={'round':repeat+1,'text_index':i,'voice':voice,'elapsed_s':elapsed,'audio_s':duration,'rtf':elapsed/duration}
            report['runs'].append(row)
            if repeat==0:(out/f'qwen-native-{i}-{voice}.wav').write_bytes(wav)
            (out/'qwen-native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'native':True,**row}),flush=True)
    report['summary']=[{'text_index':i,'voice':v,
        'median_s':statistics.median(r['elapsed_s'] for r in report['runs']if r['text_index']==i and r['voice']==v),
        'median_audio_s':statistics.median(r['audio_s'] for r in report['runs']if r['text_index']==i and r['voice']==v),
        'median_rtf':statistics.median(r['rtf'] for r in report['runs']if r['text_index']==i and r['voice']==v)}for i in range(len(texts))for v in ['male','female']]
except Exception as error:
    report['error']=type(error).__name__+': '+str(error)
    raise
finally:
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(10)
        except subprocess.TimeoutExpired:process.kill();process.wait(5)
    log.close();report['owned_server_stopped']=True
    (out/'qwen-native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
