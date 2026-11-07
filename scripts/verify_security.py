import asyncio
import json
from pathlib import Path
from websockets.asyncio.client import connect
ROOT=Path(__file__).resolve().parent.parent
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8'))
async def main():
    report={}
    try:
        async with connect('ws://127.0.0.1:8765/ws',origin='https://www.youtube.com',proxy=None):pass
        report['foreign_origin_rejected']=False
    except Exception as exc:report['foreign_origin_rejected']='403' in str(exc)
    async with connect('ws://127.0.0.1:8765/ws',origin='chrome-extension://'+cfg['extension_id'],proxy=None) as ws:
        await ws.send(json.dumps({'type':'auth','token':'wrong-token'}))
        try:await ws.recv();report['wrong_token_rejected']=False
        except Exception as exc:report['wrong_token_rejected']='1008' in str(exc)
    (ROOT/'reports/security-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report)
    assert all(report.values())
asyncio.run(main())
