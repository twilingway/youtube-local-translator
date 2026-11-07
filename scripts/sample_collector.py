"""One-shot loopback-only authorized Chrome tab audio sampler; raw window RAM-only."""
import asyncio,hmac,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import uvicorn
from fastapi import FastAPI,WebSocket
from service.config import config,ROOT
from service.listening import select_samples

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
done=asyncio.Event();record={'audio':[],'bytes':0};busy=False

@app.websocket('/sample')
async def sample(ws:WebSocket):
    global busy
    cfg=config()
    if busy or ws.headers.get('origin')!='chrome-extension://'+cfg['extension_id']:
        await ws.close(code=1008);return
    await ws.accept()
    try:
        auth=await asyncio.wait_for(ws.receive_json(),5)
        if auth.get('type')!='auth' or not hmac.compare_digest(str(auth.get('token','')),cfg['token']):await ws.close(code=1008);return
        busy=True;record.update(url=str(auth.get('url','')),title=str(auth.get('title','')),offset=float(auth.get('time',0)))
        await ws.send_json({'type':'ready'})
        while True:
            message=await asyncio.wait_for(ws.receive(),80)
            if message.get('bytes') is not None:
                data=message['bytes'];record['bytes']+=len(data)
                if len(data)%2 or record['bytes']>75*32000:raise ValueError('Sample duration limit')
                record['audio'].append(data)
            elif message.get('text'):
                if json.loads(message['text']).get('type')=='finish':done.set();await ws.send_json({'type':'captured'});return
            else:raise RuntimeError('Sample capture disconnected before completion')
    except Exception as error:
        record['error']=type(error).__name__+': '+str(error);done.set()
    finally:busy=False

async def main():
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8768,log_level='warning',ws_max_size=524288))
    task=asyncio.create_task(server.serve())
    print('Sample collector ready on loopback8768; waiting for explicit extension click.',flush=True)
    try:
        await asyncio.wait_for(done.wait(),600)
        if record.get('error'):raise RuntimeError(record['error'])
        pcm=np.frombuffer(b''.join(record['audio']),dtype='<i2');record['audio']=[]
        print(json.dumps({'captured_s':len(pcm)/16000,'bulk_stored_on_disk':False}),flush=True)
        result=await select_samples(pcm,record['offset'],record['url'],record['title'])
        print(json.dumps({'selected':len(result['stored_samples']),'files':[x['file']for x in result['stored_samples']]}),flush=True)
    finally:server.should_exit=True;await task

asyncio.run(main())
