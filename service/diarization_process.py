"""Keep native offline diarization outside the WebSocket process and its GIL."""
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

_model=None

def _initialize():
    global _model
    from .diarization import ConversationDiarizer
    _model=ConversationDiarizer()

def _run(kind,args):
    if kind=='encode':return _model.encode(*args)
    audio,start,registry,previous,limit,lexical=args
    turns,seconds=_model.diarize(audio,start,registry,previous,limit,lexical)
    return turns,seconds,registry

class ConversationDiarizerProcess:
    def __init__(self):
        self.pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'),initializer=_initialize)

    def encode(self,audio):return self.pool.submit(_run,'encode',(audio,)).result(timeout=180)

    def diarize(self,audio,start,registry,previous,limit=8,lexical=None):
        turns,seconds,updated=self.pool.submit(_run,'diarize',(audio,start,registry,previous,limit,lexical)).result(timeout=180)
        registry[:]=updated
        return turns,seconds

    def close(self):self.pool.shutdown(wait=True,cancel_futures=True)
