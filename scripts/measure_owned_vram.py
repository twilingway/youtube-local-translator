"""Bounded before/after measurement; terminate only the verified project worker."""
import json,statistics,subprocess,time
from pathlib import Path
import httpx,psutil
ROOT=Path(__file__).resolve().parent.parent
def sample():
    line=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip().splitlines()[0]
    memory,utilization=map(int,line.split(','));return {'memory_mib':memory,'gpu_percent':utilization,'at':time.time()}
worker=psutil.Process(60168)
args=worker.cmdline()
assert Path(worker.cwd()).resolve()==ROOT and 'uvicorn' in args and '8765' in args,args
before=[]
for _ in range(5):before.append(sample());time.sleep(.4)
worker.terminate();worker.wait(10)
for _ in range(40):
    if not any(c.status==psutil.CONN_LISTEN and c.laddr.port in (8765,11439) for c in psutil.net_connections('tcp')):break
    time.sleep(.25)
time.sleep(2)
after=[]
for _ in range(5):after.append(sample());time.sleep(.4)
report={'kind':'aggregate GPU before/after only verified project worker stopped; foreign applications untouched; WDDM attribution estimate',
        'backend_before':'Silero + large-v3 + TranslateGemma4B + ECAPA','terminated_worker':60168,'before':before,'after':after,
        'before_median_mib':statistics.median(x['memory_mib'] for x in before),'after_median_mib':statistics.median(x['memory_mib'] for x in after)}
report['estimated_project_mib']=report['before_median_mib']-report['after_median_mib']
(ROOT/'reports/vram-owned-20261106.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('before','after')},ensure_ascii=False),flush=True)
