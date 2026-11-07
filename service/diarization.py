"""Neural diarization over a conversation window, with session-wide label matching."""
import time
import numpy as np
from .config import ROOT
from .speakers import retain_reference

def overlap(a,b):return max(0.,min(a['end'],b['end'])-max(a['start'],b['start']))

def assign_clusters(vectors,local_turns,registry,previous,limit=8):
    """Window-local labels may permute; overlap anchors retain session identities."""
    keys=sorted(vectors,key=lambda key:min(t['start'] for t in local_turns if t['speaker']==key))
    if not keys:return {}
    mapping={}
    for key in keys:
        # Compare to the frozen reference first. Overlap is a tie-breaker, not
        # proof of identity: an earlier wrong label must be able to recover.
        anchors=np.array([float(np.dot(vectors[key],item['centroid'])) for item in registry])
        variants=np.array([max([anchors[i],*[float(np.dot(vectors[key],v)) for v in item.get('profiles',[])]]) for i,item in enumerate(registry)])
        votes=np.array([sum(overlap(turn,old) for turn in local_turns if turn['speaker']==key for old in previous if old['speaker']==col) for col in range(len(registry))])
        scores=.8*anchors+.2*variants+.25*np.minimum(1,votes/2)
        best=int(np.argmax(scores)) if len(scores) else 0
        if not len(scores) or (anchors[best]<.45 and votes[best]<.3 and len(registry)<limit):
            speaker=len(registry);registry.append({'centroid':vectors[key].copy(),'profiles':[],'seconds':0,'backend':'sherpa'})
        else:
            speaker=best
            margin=anchors[best]-max([v for i,v in enumerate(anchors) if i!=best],default=-1)
            if anchors[best]>=.55 and margin>=.1:
                item=registry[best];item.setdefault('profiles',[]).append(vectors[key].copy());item['profiles']=item['profiles'][-6:]
        mapping[key]=speaker
    return mapping

def label_words(words,turns):
    groups=[]
    for word in words:
        if not turns:return []
        mid=(word['start']+word['end'])/2
        best=max(turns,key=lambda t:(overlap(word,t),-abs((t['start']+t['end'])/2-mid)))
        speaker=best['speaker']
        if groups and groups[-1][0]==speaker:groups[-1][1].append(word)
        else:groups.append((speaker,[word]))
    return groups

class ConversationDiarizer:
    def __init__(self):
        import sherpa_onnx as so
        base=ROOT/'models/diarization'
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(base/'nemo_en_titanet_small.onnx'),num_threads=4,provider='cpu')
        cfg=so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(base/'sherpa-onnx-pyannote-segmentation-3-0/model.onnx'),window_shift_ratio=.1),num_threads=4,provider='cpu'),
            embedding=embedding,clustering=so.FastClusteringConfig(num_clusters=-1,threshold=.8),min_duration_on=.3,min_duration_off=.35)
        if not cfg.validate():raise RuntimeError('Нет моделей диаризации. Запустите scripts/fetch_diarization.py')
        self.model=so.OfflineSpeakerDiarization(cfg);self.extractor=so.SpeakerEmbeddingExtractor(embedding)
        self.config=cfg;self.models={}

    def encode(self,audio):
        stream=self.extractor.create_stream();stream.accept_waveform(sample_rate=16000,waveform=np.ascontiguousarray(audio,dtype=np.float32));stream.input_finished()
        if not self.extractor.is_ready(stream):raise RuntimeError('Недостаточно речи для определения говорящего')
        vector=np.asarray(self.extractor.compute(stream),dtype=np.float32)
        return vector/(np.linalg.norm(vector)+1e-9)

    def diarize(self,audio,audio_start,registry,previous,limit=8,lexical=None):
        began=time.perf_counter()
        if len(audio)>960000:audio_start+=(len(audio)-960000)/16000;audio=audio[-960000:]
        fixed=limit<8 and len(registry)>=limit
        if fixed and limit not in self.models:
            import sherpa_onnx as so
            self.config.clustering.num_clusters=limit
            self.models[limit]=so.OfflineSpeakerDiarization(self.config)
        model=self.models[limit] if fixed else self.model
        raw=model.process(np.ascontiguousarray(audio,dtype=np.float32)).sort_by_start_time()
        if not fixed and limit<8 and len({turn.speaker for turn in raw})>limit:
            import sherpa_onnx as so
            if limit not in self.models:
                self.config.clustering.num_clusters=limit
                self.models[limit]=so.OfflineSpeakerDiarization(self.config)
            raw=self.models[limit].process(np.ascontiguousarray(audio,dtype=np.float32)).sort_by_start_time()
        turns=[{'start':audio_start+max(0,t.start),'end':audio_start+min(len(audio)/16000,t.end),'speaker':t.speaker} for t in raw]
        lexical_ranges=[]
        if lexical is not None:
            for word in sorted(lexical,key=lambda w:w['start']):
                a,b=word['start']-.16,word['end']+.16
                if lexical_ranges and a<=lexical_ranges[-1][1]:lexical_ranges[-1]=(lexical_ranges[-1][0],max(b,lexical_ranges[-1][1]))
                else:lexical_ranges.append((a,b))
        vectors={};samples={};clean_ranges={}
        for speaker in sorted({t['speaker'] for t in turns}):
            pieces=[];usable=[]
            for turn in turns:
                if turn['speaker']!=speaker:continue
                ranges=[(turn['start']+.12,turn['end']-.12)]
                for other in turns:
                    if other['speaker']==speaker:continue
                    ranges=[part for a,b in ranges for part in ((a,min(b,other['start'])),(max(a,other['end']),b)) if part[1]-part[0]>=.15]
                if lexical is not None:ranges=[(max(a,x),min(b,y)) for a,b in ranges for x,y in lexical_ranges if min(b,y)-max(a,x)>=.15]
                for a,b in ranges:
                    left=max(0,round((a-audio_start)*16000));right=min(len(audio),round((b-audio_start)*16000))
                    if right-left>=4000:pieces.append(audio[left:right]);usable.append((a,b))
            if not pieces:
                if lexical is not None:continue
                own=max((t for t in turns if t['speaker']==speaker),key=lambda t:t['end']-t['start'])
                pieces=[audio[max(0,round((own['start']-audio_start)*16000)):min(len(audio),round((own['end']-audio_start)*16000))]]
                usable=[(own['start'],own['end'])]
            clip=np.concatenate(sorted(pieces,key=len,reverse=True))[:96000]
            if len(clip)<12800:continue
            vectors[speaker]=self.encode(clip);samples[speaker]=clip;clean_ranges[speaker]=usable
        mapping=assign_clusters(vectors,turns,registry,previous,limit)
        for local,speaker in mapping.items():
            clip=samples[local];item=registry[speaker]
            item['seconds']=max(item.get('seconds',0),len(clip)/16000)
            if not item.get('reference'):
                fresh=[];seen=item.setdefault('reference_seen',[])
                for a,b in clean_ranges[local]:
                    ranges=[(a,b)]
                    for old_a,old_b in seen:
                        ranges=[part for x,y in ranges for part in ((x,min(y,old_a)),(max(x,old_b),y)) if part[1]-part[0]>.05]
                    for x,y in ranges:
                        left=max(0,round((x-audio_start)*16000));right=min(len(audio),round((y-audio_start)*16000))
                        fresh.append(audio[left:right]);seen.append((x-.15,y+.15))
                if fresh:
                    fresh=np.concatenate([item.get('reference_fresh',np.empty(0,dtype=np.float32)),*fresh])[:96000]
                    if len(fresh)>=12800:
                        retain_reference(item,fresh);item.pop('reference_fresh',None)
                        if item.get('reference'):item['centroid']=vectors[local].copy()
                    else:item['reference_fresh']=fresh
        result=[{**t,'speaker':mapping[t['speaker']]} for t in turns if t['speaker'] in mapping]
        return result,time.perf_counter()-began
