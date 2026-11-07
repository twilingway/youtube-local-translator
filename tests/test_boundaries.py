"""Boundary alignment regression tests. No model-quality claims."""
from types import SimpleNamespace
import numpy as np
from service.boundaries import matched_prefix
from service.engine import Engine

def w(text,start,end):return dict(text=text,start=start,end=end)

def test_shared_words_at_same_audio_time_are_emitted_once():
    old=[w('about',3,3.4),w('Space.',3.4,4)]
    new=[w('about',3.05,3.45),w('space',3.45,4.05),w('and',4.1,4.3),w('time',4.3,4.7)]
    assert matched_prefix(old,new,4.5)==2

def test_repeated_phrase_at_a_new_time_is_not_deleted():
    old=[w('thank',0,.3),w('you',.3,.6)]
    new=[w('thank',2,2.3),w('you',2.3,2.6)]
    assert matched_prefix(old,new,2)==0

def fake_engine(words):
    engine=Engine.__new__(Engine);engine.speakers=None
    class ASR:
        def transcribe(self,audio,**kwargs):
            assert kwargs['max_new_tokens']==256 and kwargs['temperature']==0
            return [SimpleNamespace(words=[SimpleNamespace(word=t,start=a,end=b) for t,a,b in words])],SimpleNamespace(language='en',language_probability=1.)
    engine.asr=ASR();engine.translate=lambda text,language,grammar=None:text
    return engine

def test_a_new_whole_word_with_retimed_start_is_not_dropped():
    engine=fake_engine([(' result.',.05,.5)])
    state={'committed_until':1.,'last_word_key':'the','committed_words':[w('the',.6,1.)]}
    result=engine.process(np.zeros(16000,np.float32),.8,'subtitles','male',state,True)
    assert [c['source'] for c in result['cues']]==['result.']

def test_pending_partial_word_is_replaced_by_full_overlap_word():
    engine=fake_engine([(' background.',.01,.75)])
    partial=w('back',0,.5)
    state={'committed_until':.5,'last_word_key':'back','committed_words':[dict(partial)],'pending':[dict(partial)],
           'tail':np.zeros(9600,np.float32),'tail_end':.6}
    result=engine.process(np.zeros(16000,np.float32),.6,'subtitles','male',state,True)
    assert [c['source'] for c in result['cues']]==['background.']
