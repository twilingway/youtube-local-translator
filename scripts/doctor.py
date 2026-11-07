import json
import shutil
import subprocess
import sys
import platform
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
report={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'tools':{}}
for name,args in [('nvidia-smi',['nvidia-smi']),('ffmpeg',['ffmpeg','-version']),('node',['node','--version']),('uv',['uv','--version'])]:
    if shutil.which(name):
        result=subprocess.run(args,capture_output=True,text=True,errors='replace')
        report['tools'][name]={'path':shutil.which(name),'exit_code':result.returncode,'output':result.stdout[:7000]}
try:
    import torch
    report['torch']={'version':torch.__version__,'cuda':torch.version.cuda,'available':torch.cuda.is_available(),
        'gpu':torch.cuda.get_device_name() if torch.cuda.is_available() else None}
    if torch.cuda.is_available():
        a=torch.randn(2048,2048,device='cuda');b=a@a;torch.cuda.synchronize()
        report['torch']['matmul']='passed'
except ImportError as exc:report['torch']={'error':str(exc)}
for name in ['faster-whisper','ctranslate2','fastapi','uvicorn','qwen-tts','transformers','numpy']:
    import importlib.metadata
    try:report[name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:report[name]=None
(ROOT/'reports/environment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='tools'},ensure_ascii=False,indent=2))
