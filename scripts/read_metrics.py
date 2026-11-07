import json
import sys
import urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
cfg=json.loads((root/'config.local.json').read_text(encoding='utf-8'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
req=urllib.request.Request('http://127.0.0.1:8765/metrics',headers={'Authorization':'Bearer '+cfg['token']})
with opener.open(req) as response:
    report=json.load(response)
out=json.dumps(report,ensure_ascii=False,indent=2)
if len(sys.argv)>1:(root/sys.argv[1]).write_text(out,encoding='utf-8')
print(out)
