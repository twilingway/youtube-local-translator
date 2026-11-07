import argparse
import json
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('--seconds',type=int,default=60)
parser.add_argument('--output',default='reports/session-benchmark.json')
parser.add_argument('--wait-active',action='store_true')
parser.add_argument('--build')
args=parser.parse_args()
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
samples=[]
if args.wait_active:
    print('Ожидание работающего плеера…',flush=True)
    for _ in range(150):
        req=urllib.request.Request('http://127.0.0.1:8765/metrics',headers={'Authorization':'Bearer '+cfg['token']})
        with opener.open(req,timeout=3) as response:pending=json.load(response)
        player=pending.get('player',{})
        if pending['active'] and player.get('position',0)>0 and not player.get('paused',True) and (not args.build or player.get('build')==args.build):
            print('Плеер начал воспроизведение; измерение60сек.',flush=True);break
        time.sleep(2)
    else:raise SystemExit('Плеер не запущен; реальный замер не выполнен')
for _ in range(max(1,min(args.seconds,600))):
    begin=time.monotonic()
    req=urllib.request.Request('http://127.0.0.1:8765/metrics',headers={'Authorization':'Bearer '+cfg['token']})
    with opener.open(req,timeout=3) as response:data=json.load(response)
    raw=subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True).stdout
    vram,util=[int(x.strip()) for x in raw.strip().split(',')]
    samples.append({'time':time.time(),'vram_mib':vram,'gpu_util':util,**data})
    time.sleep(max(0,1-(time.monotonic()-begin)))
latencies=[s['player']['head']-s['player']['position'] for s in samples if s.get('player',{}).get('position',0)>0 and not s['player'].get('paused',True)]
last=samples[-1];pipeline=last['pipeline']
first_player=samples[0].get('player',{});last_player=last.get('player',{})
first_metrics=first_player.get('metrics',{});last_metrics=last_player.get('metrics',{})
report={'samples':samples,'summary':{'samples':len(samples),'peak_total_vram_mib':max(s['vram_mib'] for s in samples),
    'latency_s_min':min(latencies) if latencies else None,'latency_s_median':statistics.median(latencies) if latencies else None,
    'latency_s_max':max(latencies) if latencies else None,
    'process_s_median':statistics.median(x['process_s'] for x in pipeline) if pipeline else None,
    'processing_rtf_median':statistics.median(x['process_s']/(x['end']-x['start']) for x in pipeline if x['end']>x['start']) if any(x['end']>x['start'] for x in pipeline) else None,
    'auto_pause_events':last_metrics.get('autoPauseEvents',0)-first_metrics.get('autoPauseEvents',0),
    'waiting_events':last_metrics.get('waitingEvents',0)-first_metrics.get('waitingEvents',0),
    'speech_rate_min':last_metrics.get('speechRateMin'),'speech_rate_max':last_metrics.get('speechRateMax'),
    'max_speech_delay_ms':last_metrics.get('maxSpeechDelayMs'),'speech_queue':last_player.get('speechQueue'),
    'build':last_player.get('build'),
    'scope':'actual extension session; total GPU VRAM includes other applications; scheduling offsets do not measure DAC/display latency'}}
(ROOT/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report['summary'],ensure_ascii=False,indent=2))
