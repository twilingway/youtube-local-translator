"""Bounded numeric-only live observation; never stores captured media or text."""
import argparse,json,time,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from service.config import ROOT,config
p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=180);args=p.parse_args()
out=ROOT/'reports/player-046';out.mkdir(exist_ok=True);samples=[];began=time.monotonic()
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=3,headers={'Authorization':'Bearer '+config()['token']}) as c:
    while time.monotonic()-began<min(300,args.seconds):
        try:
            d=c.get('/metrics').json();v=d.get('player',{});position=v.get('position',0);processing=d.get('processing',{})
            samples.append({'t':round(time.monotonic()-began,2),'active':d.get('active'),'epoch':v.get('epoch'),
                'position':position,'ready_s':v.get('readyThrough',0)-position,'head_s':v.get('head',0)-position,
                'paused':v.get('paused'),'waiting':v.get('metrics',{}).get('waitingEvents'),
                'auto_pauses':v.get('metrics',{}).get('autoPauseEvents'),'stage':processing.get('stage'),
                'stage_elapsed_s':processing.get('elapsed_s'),'queue_s':v.get('transport',{}).get('audioSeconds'),
                'video_ranges':v.get('buffered',[])})
        except Exception as e:samples.append({'t':round(time.monotonic()-began,2),'error':type(e).__name__})
        (out/'live-buffer-trace.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')
        time.sleep(1)
print('Saved numeric samples:',len(samples),flush=True)
