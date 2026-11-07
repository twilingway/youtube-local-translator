import base64
import io
import time
import os
import re
import hashlib
import numpy as np
import httpx
import soundfile as sf
from .config import ROOT, config
from .boundaries import word_key,matched_prefix


class Engine:
    def __init__(self):
        import torch
        # CTranslate2 loads CUDA DLLs from the isolated PyTorch installation.
        self.dll_dir = os.add_dll_directory(str(ROOT / '.venv/Lib/site-packages/torch/lib')) if os.name == 'nt' else None
        from faster_whisper import WhisperModel
        model_path=os.environ.get('TRANSLATOR_ASR_MODEL',str(ROOT/'models'/config().get('asr_model','whisper')))
        self.asr_name=model_path.replace('\\','/').rstrip('/').split('/')[-1]
        self.asr = WhisperModel(model_path, device='cuda', compute_type='float16', local_files_only=True)
        torch.set_num_threads(4)
        self.torch = torch
        self.tts_backend=config().get('tts_backend','silero')
        self.tts=None
        if self.tts_backend=='silero':
            self.tts = torch.package.PackageImporter(str(ROOT / 'models/silero.pt')).load_pickle('tts_models', 'model')
            self.tts.to(torch.device('cuda'))
        self.native=None;self.preset_refs={}
        if self.tts_backend=='qwen-native':
            from .native_tts import NativeTTSClient
            self.native=NativeTTSClient()
        # A model can need more than 20 s to reload after a long idle or GPU reset.
        # Keep this project's translator resident; do not cancel its cold load.
        self.http = httpx.Client(base_url='http://127.0.0.1:11439', timeout=httpx.Timeout(180,connect=5), trust_env=False)
        if config().get('diarization_backend')=='sherpa':
            from .diarization_process import ConversationDiarizerProcess
            self.speakers=ConversationDiarizerProcess()
        else:
            from .speakers import SpeakerEncoder
            self.speakers=SpeakerEncoder() if (ROOT/'models/speakers/embedding_model.ckpt').exists() else None

    def warmup(self):
        # Pay cold model loading before capture begins, not inside its bounded queue.
        self.translate('The local video translator is ready.', 'en')
        self.render_speech('Локальный переводчик готов.', 'male')
        if self.speakers:self.speakers.encode(np.zeros(32000,dtype=np.float32))

    def translate(self, text, language, grammar=None, max_words=None):
        if language == 'ru':
            return text
        source = {'en':'English','de':'German','fr':'French','es':'Spanish','it':'Italian',
                  'pt':'Portuguese','zh':'Chinese','ja':'Japanese','ko':'Korean','uk':'Ukrainian'}.get(language,language)
        gender=('The speaker is a woman. Use feminine agreement in ALL her first-person self-descriptions: я сделала, я была, я способна, я уверена, я готова. ' if grammar=='female' else
                'The speaker is a man. Use masculine agreement in ALL his first-person self-descriptions: я сделал, я был, я способен, я уверен, я готов. ' if grammar=='male' else '')
        brevity=(f'For dubbing, aim for about {max_words} Russian words using shorter idiomatic equivalents. Remove only fillers and repetition; preserve facts, negation, names and numbers. Do not sacrifice meaning to meet the word count. ' if max_words else '')
        prompt = (f'You are a professional {source} ({language}) to Russian (ru) translator. '
                  'Your goal is to accurately convey the meaning and nuances of the original text while adhering to Russian grammar, vocabulary, and cultural sensitivities.\n'
                  'Produce only the Russian translation, without any additional explanations or commentary. '
                  'Use concise, natural spoken Russian suitable for dubbing; preserve all facts and do not expand the wording. '
                  +gender+brevity+'Preserve the gender of other people explicitly mentioned in the source. '
                  +f'Please translate the following {source} text into Russian:\n\n\n{text}')
        r = self.http.post('/api/chat', json={'model': config()['translation_model'], 'stream': False,
            'messages': [{'role': 'user', 'content': prompt}], 'keep_alive': -1,
            'options': {'temperature': 0, 'num_ctx': 2048, 'num_predict': 320}},timeout=httpx.Timeout(180,connect=5))
        r.raise_for_status()
        return r.json()['message']['content'].strip()

    def compact(self,text,max_words,grammar=None):
        gender='Сохрани женский род говорящей.' if grammar=='female' else 'Сохрани мужской род говорящего.' if grammar=='male' else 'Сохрани грамматический род исходного русского текста.'
        prompt=(f'Переформулируй русский текст короче для дубляжа, по возможности не более {max_words} слов. '
                'Используй естественную разговорную речь. Убирай только лишние слова и повторы. '
                'Сохрани ВСЕ факты, отрицания, числа, имена и последовательность событий; смысл важнее лимита слов. '
                +gender+' Не меняй род других упомянутых людей. Ответь только новым русским текстом.\nТекст: '+text)
        response=self.http.post('/api/chat',json={'model':config()['translation_model'],'stream':False,
            'messages':[{'role':'user','content':prompt}],'keep_alive':-1,
            'options':{'temperature':0,'num_ctx':2048,'num_predict':320}},timeout=httpx.Timeout(180,connect=5))
        response.raise_for_status();return response.json()['message']['content'].strip()

    def synthesize(self, text, voice):
        if self.tts is None:raise RuntimeError('Silero не загружен в профиле Qwen')
        with self.torch.inference_mode():
            speaker=voice if voice in ('eugene','aidar','baya','xenia','kseniya') else ('eugene' if voice=='male' else 'xenia')
            audio = self.tts.apply_tts(text=text, speaker=speaker, sample_rate=24000)
        self.torch.cuda.synchronize()
        return audio.cpu().numpy(), 24000

    def render_speech(self,text,voice,reference=None,speaker_id=0):
        if not self.native:
            audio,rate=self.synthesize(text,voice)
            return audio,rate,{'tts_backend':'silero','voice_source':'preset'}
        source='original' if reference else 'preset'
        if not reference:
            if voice not in self.preset_refs:
                name=voice if voice in ('eugene','aidar','xenia','baya','kseniya') else 'xenia' if voice=='female' else 'eugene'
                path=ROOT/'models/voice-presets'/f'{name}.wav'
                if not path.exists():raise RuntimeError('Нет стартовых образцов. Запустите scripts/prepare_voice_presets.py')
                self.preset_refs[voice]=path.read_bytes()
            reference=self.preset_refs[voice]
        audio,rate=self.native.synthesize(text,reference,seed=20261106+speaker_id)
        return audio,rate,{'tts_backend':'qwen-native','voice_source':source}

    def process(self, pcm, start, mode, voice, state=None, final=True):
        """Keep overlap and unfinished phrases within one epoch; never translate cut words."""
        if state is None:
            state = {}
        progress=state.get('_progress',lambda stage:None)
        progress('asr')
        begin = time.perf_counter()
        tail = state.get('tail', np.empty(0, dtype=np.float32))
        if abs(state.get('tail_end', start)-start) > .15:
            tail = np.empty(0, dtype=np.float32)
        window = np.concatenate((tail, pcm))
        window_start = start-len(tail)/16000
        end = start+len(pcm)/16000
        speaker_enabled=bool(state.get('speaker_enabled',True)) and self.speakers is not None
        if speaker_enabled:
            previous=state.get('speaker_audio',np.empty(0,dtype=np.float32))
            if abs(state.get('speaker_audio_end',start)-start)>.15:previous=np.empty(0,dtype=np.float32)
            state['speaker_audio']=np.concatenate((previous,pcm))[-1440000:]
            state['speaker_audio_start']=end-len(state['speaker_audio'])/16000
            state['speaker_audio_end']=end
        cutoff = end if final else max(start, end-.9)
        segments, info = self.asr.transcribe(window, beam_size=5, vad_filter=True,
            language=state.get('language'), initial_prompt=state.get('context', '')[-300:] or None,
            condition_on_previous_text=False, word_timestamps=True,
            temperature=0.0,max_new_tokens=256)
        segments = list(segments)
        if info.language_probability > .8:
            state['language'] = info.language
        state['tail'] = window[-40000:].copy()
        state['tail_end'] = end
        pending = state.setdefault('pending', [])
        utterances = []

        def emit_pending():
            if not pending:
                return
            text = ''.join(w['text'] for w in pending).strip()
            if text:
                utterances.append([dict(w) for w in pending])
                state['context'] = (state.get('context', '')+' '+text)[-1000:]
            pending.clear()

        candidates=[{'start':max(0,window_start+w.start),'end':min(end,window_start+w.end),'text':w.word}
                    for segment in segments for w in segment.words or []]
        history=state.setdefault('committed_words',[])
        skip=matched_prefix(history,candidates,start)
        accepted=0
        for candidate in candidates[skip:]:
            word_start=candidate['start'];word_end=candidate['end'];text=candidate['text']
            committed = state.get('committed_until', -1)
            key=word_key(text)
            if (word_end<=cutoff+.02 and pending and history and
                key.startswith(state.get('last_word_key') or '\0') and len(key)>len(state.get('last_word_key',''))+2 and
                abs(word_start-history[-1]['start'])<.2 and word_key(pending[-1]['text'])==state.get('last_word_key')):
                pending[-1]=dict(candidate);history[-1]=dict(candidate)
                state['committed_until']=word_end;state['last_word_key']=key
                continue  # repair an unfinished word, never replay its prefix
            if word_end > cutoff+.02 or word_end <= committed+.06:
                continue
            if word_start<start and key==state.get('last_word_key') and word_start<committed-.025:
                continue  # same boundary word retimed slightly by the overlapping window
            if pending and word_start-pending[-1]['end'] >= .65:
                emit_pending()
            pending.append({'start':word_start,'end':word_end,'text':text})
            history.append({'start':word_start,'end':word_end,'text':text});history[:]=history[-32:];accepted+=1
            state.setdefault('speech_word_intervals',[]).append({'start':word_start,'end':word_end})
            state['committed_until'] = word_end
            state['last_word_key']=key
            if re.search(r'[.!?][\"\u201d\u2019]?$', text.strip()) or word_end-pending[0]['start'] >= 10:
                emit_pending()
        if final and (not state.get('quality_minute') or not len(pcm)):
            emit_pending()
        ready_through = pending[0]['start'] if pending else cutoff
        asr_s = time.perf_counter() - begin
        planned=[];diarization_s=0
        state['speech_word_intervals']=[w for w in state.get('speech_word_intervals',[]) if w['end']>=end-90]
        if speaker_enabled and hasattr(self.speakers,'diarize'):
            from .diarization import label_words
            from .speakers import voice_for
            waiting=state.pop('diarization_pending',[])+utterances;utterances=[]
            ready=[];later=[];eof=not len(pcm) and final
            quality=bool(state.get('quality_minute',False))
            startup=40 if quality else 20;lookahead=20 if quality else 2
            hop=20 if quality else 0
            if eof or (end>=startup and end-state.get('diarization_end',-1000)>=hop-.1):
                progress('speaker')
                turns,diarization_s=self.speakers.diarize(state['speaker_audio'],state['speaker_audio_start'],
                    state.setdefault('speaker_registry',[]),state.get('diarization_turns',[]),state.get('speaker_limit',8),state.get('speech_word_intervals',[]))
                state['diarization_turns']=turns;state['diarization_end']=end
            else:turns=state.get('diarization_turns',[])
            if turns:
                # A completed phrase covered by the existing window need not
                # wait for the next 20 s analysis batch. Never extrapolate
                # labels beyond the audio actually analysed.
                covered=state.get('diarization_end',0)
                for words in waiting:
                    ready_words=words if eof or words[-1]['end']<=min(covered,end-lookahead) else []
                    later_words=[] if ready_words else words
                    if ready_words and turns:ready.append(ready_words)
                    elif ready_words:later.append(ready_words)
                    if later_words:later.append(later_words)
                for words in ready:
                    for speaker_id,group in label_words(words,turns):
                        planned.append(dict(start=group[0]['start'],end=group[-1]['end'],source=''.join(w['text'] for w in group).strip(),
                            speaker_id=speaker_id,speaker_similarity=None,speaker_s=0,voice=voice_for(speaker_id,voice),reference=None))
            else:later=waiting
            state['diarization_pending']=later
            if later:ready_through=min(ready_through,min(words[0]['start'] for words in later))
            if later and end-ready_through>(75 if quality else 35):raise RuntimeError('Не удалось надёжно разделить речь в буфере. Выключите различение говорящих для этого ролика.')
            if eof and later:raise RuntimeError('Не удалось разделить исходную речь. Выключите различение говорящих для этого ролика.')
        for words in utterances:
            # Word-aligned windows expose a speaker change inside a long ASR sentence.
            groups=[];group=[]
            for i,word in enumerate(words):
                group.append(word)
                if speaker_enabled and word['end']-group[0]['start']>=2.4 and words[-1]['end']-word['end']>=1.2:
                    groups.append(group);group=[]
            if group:groups.append(group)
            if speaker_enabled:
                progress('speaker')
                from .speakers import split_mixed_words
                groups=[part for group in groups for part in split_mixed_words(group,state['speaker_audio'],state['speaker_audio_start'],self.speakers)]
            for group in groups:
                utterance_start=group[0]['start'];utterance_end=group[-1]['end']
                text=''.join(w['text'] for w in group).strip()
                speaker_id=0;speaker_similarity=None;speaker_s=0;selected_voice=voice;reference=None
                if speaker_enabled:
                    progress('speaker')
                    from .speakers import voice_for,retain_reference
                    t=time.perf_counter();audio_start=state['speaker_audio_start']
                    left=max(0,round((utterance_start-audio_start)*16000))
                    right=min(len(state['speaker_audio']),round((utterance_end-audio_start)*16000))
                    speech=state['speaker_audio'][left:right]
                    registry=state.setdefault('speaker_registry',[])
                    previous_speakers=len(registry)
                    speaker_id,speaker_similarity=self.speakers.assign(speech,registry,state.get('last_speaker',0))
                    state['last_speaker']=speaker_id;selected_voice=voice_for(speaker_id,voice)
                    if speaker_id<len(registry):
                        item=registry[speaker_id]
                        if len(speech)>=12800 and (speaker_id>=previous_speakers or speaker_similarity is None or speaker_similarity>=.35):
                            reference=retain_reference(item,speech)
                        reference=item.get('reference') or item.get('reference_preview')
                    speaker_s=time.perf_counter()-t
                if planned and planned[-1]['speaker_id']==speaker_id and utterance_start-planned[-1]['end']<.65:
                    prior=planned[-1];prior['end']=utterance_end;prior['source']+=' '+text
                    prior['speaker_s']+=speaker_s;prior['reference']=reference or prior['reference']
                else:
                    planned.append(dict(start=utterance_start,end=utterance_end,source=text,speaker_id=speaker_id,
                        speaker_similarity=speaker_similarity,speaker_s=speaker_s,voice=selected_voice,reference=reference))
        if state.get('quality_minute'):
            merged=[]
            for item in planned:
                if merged and item['speaker_id']==merged[-1]['speaker_id'] and item['start']-merged[-1]['end']<=1.2 and item['end']-merged[-1]['start']<=12:
                    merged[-1]['end']=item['end'];merged[-1]['source']+=' '+item['source'];merged[-1]['speaker_s']+=item['speaker_s']
                else:merged.append(dict(item))
            planned=merged
        cues = [];awaiting=state.setdefault('tts_pending',[])
        for index,item in enumerate(planned):
            text=item['source'];speaker_id=item['speaker_id'];selected_voice=item['voice']
            registry=state.get('speaker_registry',[])
            bank=registry[speaker_id] if speaker_enabled and speaker_id<len(registry) else {}
            reference=bank.get('reference') or bank.get('reference_preview') or item['reference']
            override=state.get('speaker_overrides',{}).get(str(speaker_id),'original')
            if override!='original':selected_voice=override;reference=None
            t = time.perf_counter()
            progress('translation')
            grammar=state.get('speaker_grammar',{}).get(str(speaker_id),'neutral')
            translated = self.translate(text, info.language,grammar)
            translation_s = time.perf_counter() - t
            cue = dict(start=item['start'], end=item['end'], source=text,
                       text=translated, language=info.language, translation_s=translation_s,
                       speaker_id=speaker_id,speaker_label=f'Говорящий {speaker_id+1}',
                       speaker_similarity=item['speaker_similarity'],speaker_s=item['speaker_s'],voice=selected_voice,
                       reference_id=hashlib.sha256(reference).hexdigest()[:16] if reference else None,
                       reference_status='stable' if bank.get('reference') else 'initial' if reference else 'none',
                       reference_s=bank.get('reference_s',bank.get('reference_preview_s',0)))
            next_start=planned[index+1]['start'] if index+1<len(planned) else ready_through
            cue['audio_deadline']=max(cue['end'],min(cue['end']+1.5,next_start-.04)) if state.get('quality_minute') else cue['end']
            cue['grammar']=grammar
            if mode != 'subtitles':
                awaiting.append(cue)
            else:cues.append(cue)
        deferred=[]
        for cue in awaiting:
            speaker_id=cue['speaker_id'];selected_voice=cue['voice']
            registry=state.get('speaker_registry',[])
            bank=registry[speaker_id] if speaker_enabled and speaker_id<len(registry) else {}
            override=state.get('speaker_overrides',{}).get(str(speaker_id),'original')
            reference=bank.get('reference')
            if override!='original':selected_voice=override;reference=None
            auto=bool(self.native and speaker_enabled and override=='original')
            if auto and not reference:
                if end-cue['start']>=(60 if state.get('quality_minute') else 10) and bank.get('reference_preview'):
                    reference=bank['reference_preview'];bank['reference']=reference
                    bank['reference_s']=bank['reference_preview_s'];bank.pop('reference_pending',None)
                elif not len(pcm) and final:
                    reference=bank.get('reference_preview')
                    if not reference:raise RuntimeError('Недостаточно исходной речи для голоса. Выберите голос вручную или режим субтитров.')
                else:
                    deferred.append(cue);continue
            if mode != 'subtitles':
                grammar=state.get('speaker_grammar',{}).get(str(speaker_id),'neutral')
                if cue.get('grammar','neutral')!=grammar:
                    progress('translation');translation_at=time.perf_counter()
                    cue['text']=self.translate(cue['source'],cue['language'],grammar);cue['grammar']=grammar
                    cue['translation_s']+=time.perf_counter()-translation_at
                progress('tts')
                t = time.perf_counter()
                audio, rate,tts_info = self.render_speech(cue['text'],selected_voice,reference,speaker_id)
                from .audio_timing import fit_speech
                audio,timing=fit_speech(audio,rate,max(.15,cue.get('audio_deadline',cue['end'])-cue['start']))
                retry_s=0
                if state.get('quality_minute') and timing['tempo']>1.65 and len(cue['text'].split())>=7:
                    progress('translation');retry_at=time.perf_counter()
                    grammar=state.get('speaker_grammar',{}).get(str(speaker_id),'neutral')
                    budget=max(4,round(len(cue['text'].split())*1.45/timing['tempo']))
                    shorter=self.compact(cue['text'],budget,grammar)
                    retry_s=time.perf_counter()-retry_at;cue['translation_s']+=retry_s
                    numbers=set(re.findall(r'\d+(?:[.,]\d+)?',cue['text']))
                    if shorter and len(shorter.split())<len(cue['text'].split()) and numbers<=set(re.findall(r'\d+(?:[.,]\d+)?',shorter)):
                        progress('tts');alternative,alternative_rate,alternative_info=self.render_speech(shorter,selected_voice,reference,speaker_id)
                        alternative,alternative_timing=fit_speech(alternative,alternative_rate,max(.15,cue.get('audio_deadline',cue['end'])-cue['start']))
                        if alternative_timing['tempo']<timing['tempo']:
                            audio,rate,tts_info,timing=alternative,alternative_rate,alternative_info,alternative_timing
                            cue['text']=shorter;cue['shortened_for_dubbing']=True
                buf = io.BytesIO()
                sf.write(buf, audio, rate, format='WAV', subtype='PCM_16')
                cue.update(audio=base64.b64encode(buf.getvalue()).decode(), audio_s=len(audio)/rate,
                           tts_s=time.perf_counter() - t-retry_s,voice=selected_voice,
                           reference_id=hashlib.sha256(reference).hexdigest()[:16] if reference else None,
                           reference_status='stable' if bank.get('reference') else 'initial' if reference else 'none',
                           reference_s=bank.get('reference_s',bank.get('reference_preview_s',0)),**tts_info,**timing)
            cues.append(cue)
        state['tts_pending']=deferred
        if deferred:
            ready_through=min(ready_through,min(c['start'] for c in deferred))
            if len(deferred)>180 or end-ready_through>(90 if state.get('quality_minute') else 60):
                raise RuntimeError('Не удалось собрать устойчивый голос за 60 секунд. Выберите голос вручную или режим субтитров; очередь не пропущена.')
        from .speakers import voice_for,VOICE_NAMES
        speakers=[{'id':i,'label':f'Говорящий {i+1}','voice':voice_for(i,voice),
                   'voice_name':('Вручную: '+VOICE_NAMES[state['speaker_overrides'][str(i)]] if state.get('speaker_overrides',{}).get(str(i),'original')!='original' else
                                 'Тембр оригинала' if self.native and (item.get('reference') or item.get('reference_preview')) else
                                 'Собираем образец' if self.native else VOICE_NAMES[voice_for(i,voice)]),
                   'override':state.get('speaker_overrides',{}).get(str(i),'original'),
                   'profile_count':1+len(item.get('profiles',[])),
                   'grammar':state.get('speaker_grammar',{}).get(str(i),'neutral'),
                   'reference_s':item.get('reference_s',0)} for i,item in enumerate(state.get('speaker_registry',[]))] if speaker_enabled else []
        progress('done')
        return dict(cues=cues, speakers=speakers, readyThrough=max(0,ready_through), asr_s=asr_s,
                    diarization_s=diarization_s,
                    waiting_speakers=len({c['speaker_id'] for c in deferred}),
                    asr_words=accepted,overlap_words=skip,
                    process_s=time.perf_counter()-begin, input_s=len(pcm)/16000)
