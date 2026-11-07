"""Reference lifetime/voice mapping contracts; no claim about acoustic quality."""
import io
import numpy as np
import soundfile as sf
from service.speakers import retain_reference,SpeakerEncoder,split_mixed_words
from service.engine import Engine
import pytest
import httpx
import copy
from types import SimpleNamespace

def signal(seconds,frequency=160):
    return (.15*np.sin(2*np.pi*frequency*np.arange(round(seconds*16000))/16000)).astype(np.float32)


def test_changed_grammar_retranslates_waiting_text_before_synthesizing_it():
    engine=Engine.__new__(Engine);engine.native=True;engine.speakers=SimpleNamespace();calls=[]
    engine.asr=SimpleNamespace(transcribe=lambda *a,**kw:([],SimpleNamespace(language='en',language_probability=1)))
    engine.translate=lambda source,language,grammar:calls.append((source,grammar)) or 'Я способна.'
    engine.render_speech=lambda *a:(np.zeros(2400,np.float32),24000,{'tts_backend':'explicit-test','voice_source':'original'})
    cue={'speaker_id':1,'voice':'aidar','start':0,'end':1,'source':'I am capable.','language':'en',
         'text':'Я способен.','grammar':'neutral','translation_s':0}
    state={'speaker_registry':[{}, {'reference':b'own-original'}],'speaker_grammar':{'1':'female'},'tts_pending':[cue]}
    result=engine.process(np.zeros(16000,np.float32),0,'voice','male',state,True)
    assert calls==[('I am capable.','female')]
    assert result['cues'][0]['text']=='Я способна.' and result['cues'][0]['grammar']=='female'

def test_reference_collects_then_freezes_for_all_following_phrases():
    item={}
    preview=retain_reference(item,signal(1.3))
    assert preview and not item.get('reference')
    assert item['reference_preview_s']==1.3
    reference=retain_reference(item,signal(1.3))
    assert reference and item['reference_s']==2.6
    assert retain_reference(item,signal(6,330))==reference
    audio,rate=sf.read(io.BytesIO(reference))
    assert rate==16000 and len(audio)==41600 and 'reference_pending' not in item

def test_silence_and_nonfinite_audio_never_become_reference():
    item={}
    assert retain_reference(item,np.zeros(64000,dtype=np.float32)) is None
    assert retain_reference(item,np.full(64000,np.nan,dtype=np.float32)) is None
    assert item=={}

def test_eight_distinct_embeddings_get_stable_ids():
    encoder=SpeakerEncoder.__new__(SpeakerEncoder)
    encoder.encode=lambda audio:np.eye(9,dtype=np.float32)[int(audio[0])]
    registry=[]
    for i in range(8):
        assert encoder.assign(np.full(32000,i,dtype=np.float32),registry)[0]==i
    assert len(registry)==8
    assert encoder.assign(np.full(32000,3,dtype=np.float32),registry)[0]==3
    encoder.assign(np.full(32000,8,dtype=np.float32),registry)
    assert len(registry)==8

def test_qwen_error_never_silently_changes_to_silero():
    engine=Engine.__new__(Engine)
    class FailingNative:
        def synthesize(self,text,reference,seed):raise httpx.ReadTimeout('explicit failure')
    engine.native=FailingNative()
    engine.synthesize=lambda *args:pytest.fail('Silero must not be used in Qwen mode')
    with pytest.raises(httpx.ReadTimeout):engine.render_speech('Проверка','eugene',b'RAM reference',3)

def test_clear_voice_change_splits_at_word_boundary_without_cutting_words():
    encoder=SpeakerEncoder.__new__(SpeakerEncoder)
    encoder.encode=lambda audio:np.array([1,0]) if audio[0]>0 else np.array([0,1])
    words=[{'start':i*.5,'end':i*.5+.4,'text':str(i)} for i in range(8)]
    audio=np.concatenate((np.ones(32000),-np.ones(32000))).astype(np.float32)
    groups=split_mixed_words(words,audio,0,encoder)
    assert len(groups)==2 and groups[0]+groups[1]==words
    assert groups[0][-1]['text']=='3' and groups[1][0]['text']=='4'
    encoder.encode=lambda audio:np.array([1,0])
    assert split_mixed_words(words,audio,0,encoder)==[words]

def test_new_distinct_speaker_uses_own_first_clip_instead_of_male_preset():
    engine=Engine.__new__(Engine);engine.native=True
    words=[SimpleNamespace(start=0,end=.6,word=' A'),SimpleNamespace(start=.6,end=1.2,word=' new'),SimpleNamespace(start=1.2,end=2.,word=' speaker.')]
    engine.asr=SimpleNamespace(transcribe=lambda *a,**kw:([SimpleNamespace(words=words)],SimpleNamespace(language='en',language_probability=1)))
    class NewSpeaker:
        def assign(self,audio,registry,last):
            if len(registry)==1:
                registry.append({'centroid':np.zeros(3),'seconds':len(audio)/16000})
                return 1,.07  # Low similarity to the OLD speaker is why this ID is new.
            return 1,.9
    engine.speakers=NewSpeaker();engine.translate=lambda *a:'Новый участник.'
    def render(text,voice,reference,speaker):
        return np.zeros(240),24000,{'tts_backend':'explicit-test','voice_source':'original' if reference else 'preset'}
    engine.render_speech=render
    state={'speaker_registry':[{'centroid':np.ones(3),'seconds':3}]}
    result=engine.process(signal(2),0,'both','male',state,True)
    assert result['cues']==[] and result['readyThrough']==0 and result['waiting_speakers']==1
    assert state['speaker_registry'][1]['reference_preview_s']>=1.9
    unfinished=copy.deepcopy(state)
    engine.asr.transcribe=lambda *a,**kw:([SimpleNamespace(words=[SimpleNamespace(start=2,end=3,word=' Again.')])],SimpleNamespace(language='en',language_probability=1))
    result=engine.process(signal(1),2,'both','male',state,True)
    assert len(result['cues'])==2 and result['waiting_speakers']==0
    assert all(c['speaker_id']==1 and c['voice_source']=='original' and c['reference_status']=='stable' for c in result['cues'])
    assert len({c['reference_id'] for c in result['cues']})==1
    engine.asr.transcribe=lambda *a,**kw:([],SimpleNamespace(language='en',language_probability=1))
    ended=engine.process(np.empty(0,dtype=np.float32),2,'both','male',unfinished,True)
    assert len(ended['cues'])==1 and ended['cues'][0]['voice_source']=='original'
    assert ended['cues'][0]['reference_status']=='initial' and not ended['waiting_speakers']
    short_reply=copy.deepcopy(unfinished)
    short_reply['tts_pending']=[dict(ended['cues'][0])]
    short_reply['speaker_registry'][1].pop('reference',None)
    after_wait=engine.process(np.zeros(160000,dtype=np.float32),2,'both','male',short_reply,True)
    assert len(after_wait['cues'])==1 and not after_wait['waiting_speakers']
    assert after_wait['cues'][0]['reference_status']=='stable'
    assert after_wait['cues'][0]['voice_source']=='original'
