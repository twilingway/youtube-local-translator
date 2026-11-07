import asyncio
import base64
import hmac
import json
import math
import time
import copy
import httpx
from contextlib import asynccontextmanager
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from collections import deque
from .config import config
from .engine import Engine

engine = None
gpu_lock = asyncio.Lock()
active = False
measurements = deque(maxlen=500)
player_metrics = {}
work_metrics = {}


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = await asyncio.to_thread(Engine)
    print('Прогрев перевода и синтеза перед захватом…', flush=True)
    await asyncio.to_thread(engine.warmup)
    try:yield
    finally:
        if hasattr(getattr(engine,'speakers',None),'close'):await asyncio.to_thread(engine.speakers.close)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/health')
async def health():
    return {'ready': engine is not None, 'recording': False, 'asr':getattr(engine,'asr_name',None),
            'tts':getattr(engine,'tts_backend',None),'diarization':type(getattr(engine,'speakers',None)).__name__}


@app.get('/metrics')
async def metrics(request: Request):
    if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer '+config()['token']):
        raise HTTPException(403)
    work=dict(work_metrics)
    if work.get('started_at'):work['elapsed_s']=time.monotonic()-work.pop('started_at')
    return {'active': active, 'pipeline': list(measurements), 'player': player_metrics,'processing':work}


def valid_origin(origin):
    return origin == 'chrome-extension://' + config()['extension_id']


@app.websocket('/ws')
async def socket(ws: WebSocket):
    global active, player_metrics, work_metrics
    if not valid_origin(ws.headers.get('origin', '')):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        auth = await asyncio.wait_for(ws.receive_json(), 5)
        if auth.get('type') != 'auth' or not hmac.compare_digest(str(auth.get('token', '')), config()['token']):
            await ws.close(code=1008)
            return
    except Exception:
        await ws.close(code=1008)
        return
    if active:
        await ws.send_json({'type': 'error', 'message': 'Уже работает другая сессия'})
        await ws.close(code=1013)
        return
    active = True
    measurements.clear()
    player_metrics = {}
    work_metrics = {}
    epoch = None
    mode, voice = 'both', 'male'
    queue = asyncio.Queue(maxsize=6)  # at most 30 seconds of PCM
    send_lock = asyncio.Lock()
    last_end = 0
    stream_state = {}
    speaker_registry=[]
    speaker_overrides={}
    speaker_grammar={}
    previous_speaker_limit=None

    async def send(obj):
        async with send_lock:
            await ws.send_json(obj)

    async def worker():
        while True:
            item = await queue.get()
            try:
                item_epoch, pcm, start, item_mode, item_voice, received, item_state, final = item
                async with gpu_lock:
                    if epoch != item_epoch:
                        continue
                    began=time.monotonic()
                    def progress(stage):
                        work_metrics.update(epoch=item_epoch,start=start,end=start+len(pcm)/16000,stage=stage,started_at=began)
                    # A failed decode/translation must not partially commit words
                    # and make a retry silently omit them.
                    for attempt in range(2):
                        working_state=copy.deepcopy({k:v for k,v in item_state.items() if k!='_progress'})
                        # User preferences are live controls, not recognition
                        # state that should roll back on a model retry.
                        working_state['speaker_grammar']=speaker_grammar
                        working_state['speaker_overrides']=speaker_overrides
                        working_state['_progress']=progress
                        work_metrics['attempt']=attempt+1;progress('asr')
                        work = asyncio.create_task(asyncio.to_thread(engine.process, pcm, start, item_mode, item_voice, working_state, final))
                        try:
                            result = await asyncio.shield(work)
                            break
                        except asyncio.CancelledError:
                            # A CUDA call cannot be cancelled. Retain ownership until it returns.
                            await work
                            raise
                        except Exception:
                            if attempt or epoch!=item_epoch:raise
                            progress('retry')
                    if epoch==item_epoch:
                        registry=item_state.get('speaker_registry')
                        updated_registry=working_state.pop('speaker_registry',None)
                        working_state.pop('_progress',None)
                        item_state.clear();item_state.update(working_state)
                        if registry is not None:
                            registry[:]=updated_registry or [];item_state['speaker_registry']=registry
                        item_state['speaker_overrides']=speaker_overrides
                        item_state['speaker_grammar']=speaker_grammar
                if epoch == item_epoch:
                    measurements.append({'epoch': epoch, 'start': start, 'end': start+len(pcm)/16000,
                        'process_s': result['process_s'], 'asr_s': result['asr_s'],
                        'translation_s': sum(c.get('translation_s', 0) for c in result['cues']),
                        'tts_s': sum(c.get('tts_s', 0) for c in result['cues']),
                        'speaker_s':sum(c.get('speaker_s',0) for c in result['cues']),
                        'diarization_s':result.get('diarization_s',0),
                        'max_tempo':max((c.get('tempo',1) for c in result['cues']),default=1),
                        'max_timing_error_s':max((c.get('timing_error_s',0) for c in result['cues']),default=0),
                        'cue_count': len(result['cues']), 'queue': queue.qsize()})
                    await send(dict(type='result', epoch=epoch, start=start,
                        end=start+len(pcm)/16000, queue=queue.qsize(),
                        queue_wait_s=max(0,time.monotonic()-received-result['process_s']), **result))
            except Exception as exc:
                if epoch==item_epoch:
                    failed_stage=work_metrics.get('stage')
                    if isinstance(exc,httpx.TimeoutException):
                        component='Модель перевода' if failed_stage=='translation' else 'Синтезатор речи' if failed_stage=='tts' else 'Локальная модель'
                        message=f'{component} не ответила вовремя. Обработка остановлена; завершите сессию и запустите перевод заново.'
                    else:message=f'{type(exc).__name__}: {str(exc) or "ошибка без описания"}'
                    work_metrics.update(stage='error',failed_stage=failed_stage,message=message[:300])
                    await send({'type':'error','epoch':item_epoch,'start':start,'end':start+len(pcm)/16000,
                                'message':message[:500]})
            finally:
                if work_metrics.get('stage')!='error':work_metrics['stage']='idle'
                queue.task_done()

    task = asyncio.create_task(worker())
    async def report_progress():
        while True:
            await asyncio.sleep(1)
            status=dict(work_metrics)
            if epoch is not None and status.get('stage') not in (None,'idle','done'):
                elapsed=max(0,time.monotonic()-status.pop('started_at',time.monotonic()))
                await send({**status,'type':'processing','epoch':epoch,'elapsed_s':elapsed})
    progress_task=asyncio.create_task(report_progress())
    await send({'type': 'ready'})
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get('type')
            if kind == 'reset':
                epoch = str(msg['epoch'])[:80]
                mode, voice = msg.get('mode', 'both'), msg.get('voice', 'male')
                if mode not in ('both', 'subtitles', 'voice') or voice not in ('male', 'female'):
                    raise ValueError('Неверный режим')
                last_end = 0
                count=int(msg.get('speakerCount',8));count=8 if count==0 else count
                if count not in range(1,9):raise ValueError('Неверное число участников')
                if previous_speaker_limit is not None and count!=previous_speaker_limit:
                    speaker_registry.clear();speaker_overrides.clear();speaker_grammar.clear()
                previous_speaker_limit=count
                stream_state = {'speaker_registry':speaker_registry,'speaker_enabled':bool(msg.get('speakers',True)),
                                'speaker_overrides':speaker_overrides,'speaker_grammar':speaker_grammar,
                                'speaker_limit':count,'quality_minute':bool(msg.get('qualityMinute',False))}
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
                await send({'type': 'reset', 'epoch': epoch})
            elif kind == 'pcm' and epoch is not None and msg.get('epoch') == epoch:
                raw = base64.b64decode(msg['data'], validate=True)
                start = float(msg['start'])
                if not math.isfinite(start) or start < last_end - .1 or len(raw) > 320000 or len(raw) % 2:
                    raise ValueError('Неверная временная шкала или размер PCM')
                pcm = np.frombuffer(raw, dtype='<i2').astype(np.float32)/32768
                if not len(pcm):
                    continue
                last_end = start+len(pcm)/16000
                if queue.full():
                    # Fail closed: caller must begin a new epoch, never silently skip words.
                    epoch = None
                    while not queue.empty():
                        queue.get_nowait()
                        queue.task_done()
                    await send({'type': 'overflow', 'message': 'Очередь перевода переполнена. Повторное накопление буфера.'})
                else:
                    queue.put_nowait((epoch, pcm, start, mode, voice, time.monotonic(), stream_state, bool(msg.get('final',False))))
            elif kind == 'ping':
                await send({'type': 'pong'})
            elif kind == 'voice-map' and msg.get('epoch')==epoch:
                speaker_id=int(msg.get('speaker_id',-1));selection=msg.get('voice')
                if speaker_id not in range(8) or selection not in ('original','eugene','aidar','xenia','baya','kseniya'):
                    raise ValueError('Неверный голос говорящего')
                speaker_overrides[str(speaker_id)]=selection
                if selection!='original':speaker_grammar[str(speaker_id)]='female' if selection in ('xenia','baya','kseniya') else 'male'
                await send({'type':'voice-map','epoch':epoch,'speaker_id':speaker_id,'voice':selection,'grammar':speaker_grammar.get(str(speaker_id),'neutral')})
            elif kind == 'speaker-grammar' and msg.get('epoch')==epoch:
                speaker_id=int(msg.get('speaker_id',-1));grammar=msg.get('grammar')
                if speaker_id not in range(8) or grammar not in ('male','female','neutral'):raise ValueError('Неверный род перевода')
                speaker_grammar[str(speaker_id)]=grammar
                await send({'type':'speaker-grammar','epoch':epoch,'speaker_id':speaker_id,'grammar':grammar})
            elif kind == 'flush' and epoch is not None and msg.get('epoch') == epoch:
                await queue.put((epoch, np.empty(0,dtype=np.float32), last_end, mode, voice,
                                 time.monotonic(), stream_state, True))
            elif kind == 'diagnostics' and msg.get('epoch') == epoch:
                # Statistics only; original audio/video are never persisted.
                value = msg.get('value', {})
                if len(json.dumps(value)) < 12000:
                    player_metrics = value
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        try:
            await send({'type': 'error', 'message': str(exc)[:500]})
        except RuntimeError:
            pass
    finally:
        epoch = None
        task.cancel()
        progress_task.cancel()
        await asyncio.gather(task,progress_task, return_exceptions=True)
        active = False
