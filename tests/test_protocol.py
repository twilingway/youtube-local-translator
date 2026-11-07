"""Protocol tests use an explicit fake engine; they are not GPU/YouTube evidence."""
import asyncio
import base64
import importlib
import threading
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def protocol(monkeypatch):
    app = importlib.import_module('service.app')
    cfg = {'token': 'test-token', 'extension_id': 'a'*32}
    monkeypatch.setattr(app,'config',lambda:cfg)
    app.active=False
    app.gpu_lock=asyncio.Lock()
    class FakeEngine:
        def warmup(self):pass
        def process(self,pcm,start,mode,voice,state=None,final=False):
            time.sleep(.1)
            return {'cues':[], 'asr_s':0, 'process_s':.1,'input_s':len(pcm)/16000}
    monkeypatch.setattr(app,'Engine',FakeEngine)
    with TestClient(app.app) as client:
        yield client, {'origin': 'chrome-extension://'+'a'*32}


def auth(ws):
    ws.send_json({'type':'auth','token':'test-token'})
    assert ws.receive_json()['type']=='ready'


def test_explicit_voice_gender_sets_grammar_and_manual_grammar_can_override(protocol,monkeypatch):
    client,headers=protocol;app=importlib.import_module('service.app');seen=[];process=app.engine.process
    def capture(pcm,start,mode,voice,state=None,final=False):
        seen.append(dict(state.get('speaker_grammar',{})))
        return process(pcm,start,mode,voice,state,final)
    monkeypatch.setattr(app.engine,'process',capture)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws);ws.send_json({'type':'reset','epoch':'gender'});assert ws.receive_json()['type']=='reset'
        ws.send_json({'type':'voice-map','epoch':'gender','speaker_id':1,'voice':'xenia'})
        assert ws.receive_json()['grammar']=='female'
        ws.send_json({'type':'pcm','epoch':'gender','start':0,'data':base64.b64encode(bytes(32000)).decode()})
        assert ws.receive_json()['type']=='result'
        ws.send_json({'type':'speaker-grammar','epoch':'gender','speaker_id':1,'grammar':'male'});assert ws.receive_json()['type']=='speaker-grammar'
        ws.send_json({'type':'voice-map','epoch':'gender','speaker_id':1,'voice':'original'})
        assert ws.receive_json()['grammar']=='male'
        ws.send_json({'type':'pcm','epoch':'gender','start':1,'data':base64.b64encode(bytes(32000)).decode()});assert ws.receive_json()['type']=='result'
    assert seen==[{'1':'female'},{'1':'male'}]


def test_timeout_reports_failed_component_and_does_not_commit_packet(protocol,monkeypatch):
    import httpx
    client,headers=protocol;app=importlib.import_module('service.app');attempts=[]
    def fail(pcm,start,mode,voice,state=None,final=False):
        attempts.append(len(state.get('accepted',[])))
        state['accepted']=['uncommitted']
        state['_progress']('translation')
        raise httpx.ReadTimeout('timed out')
    monkeypatch.setattr(app.engine,'process',fail)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws);ws.send_json({'type':'reset','epoch':'cold'});assert ws.receive_json()['type']=='reset'
        ws.send_json({'type':'pcm','epoch':'cold','start':0,'data':base64.b64encode(bytes(32000)).decode()})
        while True:
            result=ws.receive_json()
            if result['type']!='processing':break
        assert result['type']=='error' and 'Модель перевода' in result['message']
        assert attempts==[0,0]
        assert app.work_metrics['failed_stage']=='translation'

def test_voice_mapping_survives_seek_and_rejects_stale_epoch(protocol,monkeypatch):
    client,headers=protocol
    app=importlib.import_module('service.app');seen=[]
    process=app.engine.process
    def capture(pcm,start,mode,voice,state=None,final=False):
        seen.append(dict(state.get('speaker_overrides',{})))
        return process(pcm,start,mode,voice,state,final)
    monkeypatch.setattr(app.engine,'process',capture)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws)
        ws.send_json({'type':'reset','epoch':'first','mode':'both','voice':'male'})
        assert ws.receive_json()['type']=='reset'
        ws.send_json({'type':'voice-map','epoch':'first','speaker_id':7,'voice':'xenia'})
        assert ws.receive_json()['type']=='voice-map'
        ws.send_json({'type':'reset','epoch':'next','mode':'both','voice':'male'})
        assert ws.receive_json()['type']=='reset'
        ws.send_json({'type':'voice-map','epoch':'first','speaker_id':7,'voice':'aidar'})
        ws.send_json({'type':'pcm','epoch':'next','start':0,'data':base64.b64encode(bytes(32000)).decode()})
        assert ws.receive_json()['type']=='result'
        assert seen==[{'7':'xenia'}]

def test_grammar_and_identity_survive_seek_but_reset_when_participant_count_changes(protocol,monkeypatch):
    client,headers=protocol;app=importlib.import_module('service.app');seen=[];process=app.engine.process
    def capture(pcm,start,mode,voice,state=None,final=False):
        seen.append((len(state['speaker_registry']),dict(state['speaker_grammar'])))
        state['speaker_registry'].append({'centroid':'explicit-fake'})
        return process(pcm,start,mode,voice,state,final)
    monkeypatch.setattr(app.engine,'process',capture)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws)
        for epoch,count in [('one',2),('seek',2),('new-count',1)]:
            ws.send_json({'type':'reset','epoch':epoch,'mode':'both','voice':'male','speakerCount':count});assert ws.receive_json()['type']=='reset'
            if epoch=='one':
                ws.send_json({'type':'speaker-grammar','epoch':epoch,'speaker_id':0,'grammar':'female'});assert ws.receive_json()['type']=='speaker-grammar'
            ws.send_json({'type':'pcm','epoch':epoch,'start':0,'data':base64.b64encode(bytes(32000)).decode()});assert ws.receive_json()['type']=='result'
    assert seen==[(0,{'0':'female'}),(1,{'0':'female'}),(0,{})]


def test_origin_and_token_rejected(protocol):
    client,headers=protocol
    for origin in ['https://www.youtube.com','null','chrome-extension://'+'b'*32]:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws',headers={'origin':origin}):pass
    with client.websocket_connect('/ws',headers=headers) as ws:
        ws.send_json({'type':'auth','token':'wrong'})
        with pytest.raises(WebSocketDisconnect):ws.receive_json()
    assert client.get('/metrics').status_code==403


def test_seek_discards_inflight_old_epoch(protocol):
    client,headers=protocol
    pcm=base64.b64encode(np.zeros(80000,dtype='<i2').tobytes()).decode()
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws)
        ws.send_json({'type':'reset','epoch':'old'})
        assert ws.receive_json()['epoch']=='old'
        ws.send_json({'type':'pcm','epoch':'old','start':0,'data':pcm})
        time.sleep(.025)
        ws.send_json({'type':'reset','epoch':'new'})
        assert ws.receive_json()=={'type':'reset','epoch':'new'}
        ws.send_json({'type':'pcm','epoch':'new','start':0,'data':pcm})
        result=ws.receive_json()
        assert result['type']=='result' and result['epoch']=='new'


def test_bounded_queue_requires_new_epoch(protocol):
    client,headers=protocol
    pcm=base64.b64encode(np.zeros(80000,dtype='<i2').tobytes()).decode()
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws)
        ws.send_json({'type':'reset','epoch':'old'})
        ws.receive_json()
        for i in range(10):ws.send_json({'type':'pcm','epoch':'old','start':i*5,'data':pcm})
        assert ws.receive_json()['type']=='overflow'
        ws.send_json({'type':'reset','epoch':'new'})
        assert ws.receive_json()=={'type':'reset','epoch':'new'}
        ws.send_json({'type':'pcm','epoch':'new','start':0,'data':pcm})
        assert ws.receive_json()['epoch']=='new'


def test_nonfinite_timestamp_rejected(protocol):
    client,headers=protocol
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws)
        ws.send_json({'type':'reset','epoch':'x'})
        ws.receive_json()
        ws.send_json({'type':'pcm','epoch':'x','start':'nan','data':'AAA='})
        assert ws.receive_json()['type']=='error'


def test_retry_does_not_commit_partial_words_or_speaker_registry(protocol,monkeypatch):
    client,headers=protocol
    app=importlib.import_module('service.app')
    attempts=[]
    def process(pcm,start,mode,voice,state,final):
        attempts.append((state.get('committed_until'),len(state['speaker_registry'])))
        if len(attempts)==1:
            state['committed_until']=999
            state['speaker_registry'].append({'centroid':'failed'})
            raise TimeoutError()
        assert state.get('committed_until') is None
        state['speaker_registry'].append({'centroid':'success'})
        return {'cues':[],'asr_s':0,'process_s':.01,'input_s':len(pcm)/16000}
    monkeypatch.setattr(app.engine,'process',process)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws);ws.send_json({'type':'reset','epoch':'retry'});ws.receive_json()
        ws.send_json({'type':'pcm','epoch':'retry','start':0,'data':'AAA='})
        assert ws.receive_json()['type']=='result'
        assert attempts==[(None,0),(None,0)]


def test_failed_packet_reports_nonempty_error_and_identity(protocol,monkeypatch):
    client,headers=protocol
    app=importlib.import_module('service.app')
    def fail(*args,**kwargs):raise TimeoutError()
    monkeypatch.setattr(app.engine,'process',fail)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws);ws.send_json({'type':'reset','epoch':'error'});ws.receive_json()
        ws.send_json({'type':'pcm','epoch':'error','start':0,'data':'AAA='})
        result=ws.receive_json()
        assert result['type']=='error' and result['epoch']=='error'
        assert result['start']==0 and result['end']>0
        assert result['message'].startswith('TimeoutError:')


def test_inflight_processing_stage_is_reported_before_completion(protocol,monkeypatch):
    client,headers=protocol
    app=importlib.import_module('service.app')
    def slow(pcm,start,mode,voice,state,final):
        state['_progress']('tts');time.sleep(1.3)
        return {'cues':[],'asr_s':0,'process_s':1.3,'input_s':len(pcm)/16000}
    monkeypatch.setattr(app.engine,'process',slow)
    with client.websocket_connect('/ws',headers=headers) as ws:
        auth(ws);ws.send_json({'type':'reset','epoch':'stage'});ws.receive_json()
        ws.send_json({'type':'pcm','epoch':'stage','start':0,'data':'AAA='})
        progress=ws.receive_json()
        assert progress['type']=='processing' and progress['stage']=='tts'
        assert progress['epoch']=='stage' and progress['elapsed_s']>.5
        assert ws.receive_json()['type']=='result'
