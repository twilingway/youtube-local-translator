"""Minute-buffer scheduling contract with explicit fake ASR/TTS, not model evidence."""
from types import SimpleNamespace
import numpy as np
from service.engine import Engine

def test_minute_mode_uses_lookahead_merges_thoughts_and_keeps_speaker_grammar():
    engine=Engine.__new__(Engine);engine.native=True;calls=[];translated=[]
    class ASR:
        count=0
        def transcribe(self,audio,**kwargs):
            offset=0 if self.count==0 else 2.5;self.count+=1
            words=[SimpleNamespace(start=offset,end=offset+4,word=' First.'),SimpleNamespace(start=offset+4.4,end=offset+8.4,word=' Second.')]
            return [SimpleNamespace(words=words)],SimpleNamespace(language='en',language_probability=1)
    class Diarizer:
        def diarize(self,audio,start,registry,previous,limit,lexical):
            end=start+len(audio)/16000;calls.append((end,limit))
            if not registry:registry.extend([{'reference':b'voice0','reference_s':6},{'reference':b'voice1','reference_s':6}])
            return [{'start':0,'end':20,'speaker':0},{'start':20,'end':100,'speaker':1}],.01
    engine.asr=ASR();engine.speakers=Diarizer()
    def translate(text,language,grammar):translated.append((text,grammar));return 'Готовая реплика.'
    engine.translate=translate
    engine.render_speech=lambda *a:(np.zeros(2400,dtype=np.float32),24000,{'tts_backend':'explicit-test','voice_source':'original'})
    state={'quality_minute':True,'speaker_limit':2,'speaker_grammar':{'0':'female','1':'male'}}
    results=[]
    for i in range(6):results.append(engine.process(np.zeros(160000,np.float32),i*10,'both','male',state,True))
    assert not any(r['cues'] for r in results[:3])
    assert calls==[(40,2),(60,2)]
    assert results[3]['cues'] and results[3]['cues'][0]['source']=='First. Second.'
    assert all(c['speaker_id']==0 and c['grammar']=='female' for c in results[3]['cues'])
    # Completed speech inside the already analysed window is released on the
    # intervening packet, rather than waiting for another full diarization.
    assert results[4]['cues'] and results[4]['diarization_s']==0
    assert all(c['speaker_id']==1 and c['grammar']=='male' for c in results[4]['cues'])
    assert all(c['speaker_id']==1 and c['grammar']=='male' for c in results[5]['cues'])
    assert all(c['audio_deadline']>=c['end'] for r in results for c in r['cues'])

def test_packet_boundary_cannot_finish_a_partial_sentence_in_minute_mode():
    engine=Engine.__new__(Engine);engine.native=None;engine.speakers=None
    info=SimpleNamespace(language='en',language_probability=1)
    engine.asr=SimpleNamespace(transcribe=lambda *a,**kw:([SimpleNamespace(words=[SimpleNamespace(start=.2,end=.8,word=' fragment')])],info))
    engine.translate=lambda text,language,grammar:text
    state={'quality_minute':True}
    first=engine.process(np.zeros(16000,np.float32),0,'subtitles','male',state,True)
    assert not first['cues'] and first['readyThrough']==.2
    engine.asr.transcribe=lambda *a,**kw:([SimpleNamespace(words=[SimpleNamespace(start=1,end=1.8,word=' continued.')])],info)
    second=engine.process(np.zeros(16000,np.float32),1,'subtitles','male',state,True)
    assert len(second['cues'])==1 and second['cues'][0]['source']=='fragment continued.'
