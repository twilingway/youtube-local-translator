const $=id=>document.getElementById(id);
const sessionId=new URLSearchParams(location.search).get('session')||crypto.randomUUID();
const nativeMode=new URLSearchParams(location.search).get('native')==='1';
const ramMode=new URLSearchParams(location.search).get('ram')==='1';
const video=ramMode?createCachedVideo($('video')):nativeMode?createNativeVideo(sessionId):$('video');
if(nativeMode){document.body.classList.add('native-video');document.documentElement.style.background='transparent';document.documentElement.style.colorScheme='normal';$('nativeQuality').hidden=false;}
const bus=new BroadcastChannel('translator:'+sessionId);
const worker=(type,extra={})=>chrome.runtime.sendMessage({target:'worker',type,sessionId,...extra});
if(new URLSearchParams(location.search).get('embed')==='1')document.body.classList.add('embedded');
$('stage').append(document.querySelector('.settings'));
document.querySelector('.settings').append(document.querySelector('.diagnostics'));
$('stage').append($('status'),$('error'));
const limitBytes=()=>Math.max(256,Math.min(8192,Number($('memory').value)||2048))*1048576;
let epoch=null,settings={},mediaSource,buffer,url,appendQueue=[],pendingBytes=0,cues=[],head=0,readyThrough=0,ledger=[];
let captureArchive=new CaptureArchive(),encodedMedia=null,decoderMime='',decoderGeneration=0,rebuildTarget=null,cacheSeekBusy=false,earliestRetained=0,translatedRanges=[],trackInfo={};
let cacheStats={seeks:0,verified:0,failures:0},frameStats={},frameSample={time:performance.now(),total:0,dropped:0},lastInputEnd=0;
let userPaused=false,started=false,stopped=false,held=false,spoken=new Set(),audioNodes=[],lastResult={},lastSource={},captureEnded=false;
let dubAudio=new Audio(),preparedDub=null;dubAudio.preservesPitch=true;
let currentDub=null,dubURL=null,unlocked=true,autoplayBlocked=false,playPending=false,preparingAppend=false,capacityStopRequested=false,decodeAhead=30,targetIncrease=0,dubHold=false;
let metrics={results:0,late:0,played:0,resets:0,mediaBytes:0,lastCue:null,audioStartOffsetsMs:[],autoPauseEvents:0,waitingEvents:0};
let showSubtitles=false,subtitlePreference=null,subtitleMode=null,clockSamples=[],scrubbing=false;
let mediaClock={};
let speakerList=[];const grammarPrefs={};
let speakerControlsKey='';const voiceChoices=[['original','Тембр оригинала'],['eugene','Мужской 1'],['aidar','Мужской 2'],['xenia','Женский 1'],['baya','Женский 2'],['kseniya','Женский 3']];
function renderSpeakers(){
  const key=JSON.stringify(speakerList);if(key===speakerControlsKey)return;speakerControlsKey=key;
  const box=$('speakerInfo');box.replaceChildren();
  if(!speakerList.length){box.textContent='Пока недостаточно речи для различения говорящих';return;}
  for(const speaker of speakerList){
    const card=document.createElement('div'),title=document.createElement('strong');card.className='speaker-profile';title.textContent=speaker.label;card.append(title);
    const label=document.createElement('label'),select=document.createElement('select');
    label.append(document.createTextNode('Озвучка'));select.setAttribute('aria-label','Голос: '+speaker.label);
    for(const [value,text]of voiceChoices){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
    select.value=speaker.override||'original';select.onchange=()=>{
      speaker.override=select.value;bus.postMessage({type:'voice-map',speaker_id:speaker.id,voice:select.value});
      if(select.value!=='original'){
        grammar.value=['xenia','baya','kseniya'].includes(select.value)?'female':'male';
        grammarPrefs[speaker.id]=grammar.value;speaker.grammar=grammar.value;
      }
    };
    label.append(select);card.append(label);
    const grammarLabel=document.createElement('label'),grammar=document.createElement('select');grammarLabel.append(document.createTextNode('Род в переводе'));
    grammar.setAttribute('aria-label','Род: '+speaker.label);
    for(const [value,text]of [['neutral','Не указан'],['female','Женский — сделала'],['male','Мужской — сделал']]){const option=document.createElement('option');option.value=value;option.textContent=text;grammar.append(option);}
    grammar.value=grammarPrefs[speaker.id]??speaker.grammar??'neutral';grammar.onchange=()=>{grammarPrefs[speaker.id]=grammar.value;bus.postMessage({type:'speaker-grammar',speaker_id:speaker.id,grammar:grammar.value});};
    grammarLabel.append(grammar);card.append(grammarLabel);box.append(card);
  }
}
let lastMediaAt=performance.now(),lastResultAt=performance.now();
let transport={pendingPackets:0,audioSeconds:0},processing={},lastControlActivity=performance.now();
const controls=document.querySelector('.player-controls');
function startupReady(){
  const delay=Number($('delay').value)||60;
  return Boolean(epoch && !stopped && video.buffered.length && video.readyState>=3 &&
    (head>=delay || (captureEnded && head>.1)) && readyThrough>=Math.min(head,Math.max(5,Math.min(20,delay/3))));
}
function renderPlayButton(){
  const preparing=!started && !startupReady();
  const paused=userPaused || !unlocked;
  $('play').disabled=preparing || stopped || !epoch;
  $('play').textContent=preparing?(processing.stage==='error'?'Перевод остановлен':'Подготовка перевода…'):
    autoplayBlocked?'▶ Включить звук':paused?'▶ Воспроизвести':'❚❚ Пауза';
  $('play').setAttribute('aria-pressed',String(started && !paused));
  $('play').setAttribute('aria-busy',String(preparing && processing.stage!=='error'));
  $('play').title=preparing?'Начнётся автоматически, когда видео и перевод будут готовы':'Воспроизведение / пауза — Пробел';
}
function blockAutoplay(){
  unlocked=false;autoplayBlocked=true;held=true;video.pause();silence();
  status('Перевод готов. Нажмите «Включить звук» один раз.');renderPlayButton();
}
function startVideo(){
  if(playPending)return;
  const ownEpoch=epoch;playPending=true;
  return video.play().catch(error=>{
    if(epoch!==ownEpoch)return;
    if(error.name==='NotAllowedError')blockAutoplay();
    else{userPaused=true;$('error').textContent='Не удалось запустить видео: '+error.message;}
  }).finally(()=>{if(epoch===ownEpoch)playPending=false;});
}
function revealControls(){lastControlActivity=performance.now();document.body.classList.remove('controls-hidden');}
function updateControls(){
  const fullscreen=Boolean(document.fullscreenElement || (nativeMode && video.nativeState().fullscreen));
  const focused=controls.contains(document.activeElement) && document.activeElement?.matches(':focus-visible');
  const idle=performance.now()-lastControlActivity>2500;
  document.body.classList.toggle('controls-hidden',fullscreen && idle && started && !video.paused && !userPaused && !document.querySelector('.settings').open && !focused);
}
for(const event of ['mousemove','pointerdown','touchstart','keydown','focusin'])document.addEventListener(event,revealControls,{passive:true});
document.addEventListener('fullscreenchange',revealControls);
function renderBufferStatus(){
  const label=$('bufferStatus');if(!label)return;
  const now=performance.now(),captured=Math.max(0,head-video.currentTime),ready=Math.max(0,readyThrough-video.currentTime),goal=Number($('delay').value)||30;
  const playable=video.buffered.length?Math.max(0,video.buffered.end(video.buffered.length-1)-video.currentTime):0;
  let state='Перевод идёт';
  if(stopped)state='Захват остановлен';
  else if(!epoch)state='Подключение';
  else if(capacityStopRequested)state='Архив заполнен; источник на паузе';
  else if(captureEnded)state='Захват завершён';
  else if(userPaused)state='Пауза просмотра; накапливаем';
  else if(cacheSeekBusy || rebuildTarget!==null)state='Возврат из архива';
  else if(lastSource.paused)state='Источник на паузе';
  else if(head>goal && playable<.25)state='Нет кадров видео: проверьте исходную вкладку';
  else if(now-lastMediaAt>4000)state=`Нет новых данных ${Math.floor((now-lastMediaAt)/1000)} с`;
  else if(now-lastResultAt>15000 && (processing.stage || transport.audioSeconds>0))state='Готовим следующие реплики';
  else if(lastResult.waiting_speakers)state='Собираем образцы голосов';
  else if(held && !autoplayBlocked)state='Пополняем запас перевода';
  else if(!started || video.paused)state='Подготовка перевода';
  const cached=ramMode && translatedRanges.length?` · В RAM: ${formatTime(sourceTime(earliestRetained))}–${formatTime(sourceTime(readyThrough))}`:'';
  label.textContent=`${state} · Буфер перевода: ${Math.floor(ready)} с${cached}`;
  label.dataset.stale=String(epoch && !captureEnded && now-lastMediaAt>4000);
  $('capturedBar').style.width=Math.min(100,captured/goal*100)+'%';$('translatedBar').style.width=Math.min(100,ready/goal*100)+'%';
  const meter=label.previousElementSibling;meter.setAttribute('aria-valuemax',String(goal));meter.setAttribute('aria-valuenow',String(Math.min(goal,ready)));meter.setAttribute('aria-valuetext',`Готово ${ready.toFixed(1)} секунд перевода`);
}
function formatTime(seconds){seconds=Math.max(0,Math.floor(seconds||0));return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
function sourceTime(position){
  if(!clockSamples.length)return (settings.sourceStart||0)+position;
  if(position<=clockSamples[0].captureTime)return clockSamples[0].time+position-clockSamples[0].captureTime;
  if(position>=clockSamples.at(-1).captureTime)return clockSamples.at(-1).time+position-clockSamples.at(-1).captureTime;
  let before=clockSamples[0],after=clockSamples.at(-1);
  for(const item of clockSamples){if(item.captureTime<=position)before=item;else{after=item;break;}}
  if(after.captureTime<=before.captureTime)return before.time;
  const ratio=Math.max(0,Math.min(1,(position-before.captureTime)/(after.captureTime-before.captureTime)));
  return before.time+(after.time-before.time)*ratio;
}
function captureTime(time){
  if(!clockSamples.length)return time-(settings.sourceStart||0);
  let before=clockSamples[0];
  if(time<=before.time)return before.captureTime+time-before.time;
  for(const after of clockSamples.slice(1)){
    if(time<=after.time && after.time>before.time)return before.captureTime+(time-before.time)/(after.time-before.time)*(after.captureTime-before.captureTime);
    before=after;
  }
  return before.captureTime+time-before.time;
}
function cachedPosition(time){
  let pos=captureTime(time);
  // A capture often starts just after 0:00 because opening the popup takes
  // time. Snap a near-start click to its first retained frame, not a recapture.
  if(pos<earliestRetained && time>=Math.max(0,sourceTime(earliestRetained)-2))pos=earliestRetained;
  return pos>=earliestRetained && pos<readyThrough-.2 && pos<head-.2 && translatedRanges.some(([a,b])=>pos>=a-.05 && pos<=b-.2)?pos:null;
}
async function seekSource(time){
  if(cacheSeekBusy)return;
  const pos=cachedPosition(time);
  const inDecoder=pos!==null && Array.from({length:video.buffered.length},(_,i)=>[video.buffered.start(i),video.buffered.end(i)]).some(([a,b])=>pos>=a && pos<b-.1);
  if(pos!==null && (nativeMode || ramMode || inDecoder || captureArchive.chunks[0]?.seq===0)){
    const ownEpoch=epoch;cacheSeekBusy=true;video.pause();silence();
    try{
      for(const cue of cues.filter(c=>c.audioBytes && c.end>=pos)){
        if(await CaptureArchive.hash(cue.audioBytes)!==await cue.audioDigest)throw Error('Повреждена сохранённая русская дорожка');
      }
      if(epoch!==ownEpoch)return;
      if(ramMode && !inDecoder){await encodedMedia.seek(pos);if(epoch!==ownEpoch)return;}
      else if(!nativeMode && !inDecoder){
        // Incoming chunks remain retained while verification runs. Take a fresh
        // snapshot after the await so none are lost when replacing the decoder.
        let snapshot=captureArchive.chunks.slice();await captureArchive.verify(snapshot);
        if(epoch!==ownEpoch)return;cacheStats.verified+=snapshot.length;
        const tail=captureArchive.chunks.slice(snapshot.length);
        for(const c of tail)if(await CaptureArchive.hash(c.data)!==c.digest)throw Error('Повреждён фрагмент архива');
        if(epoch!==ownEpoch)return;snapshot=captureArchive.chunks.slice();
        rebuildTarget=pos;createDecoder(decoderMime);
        appendQueue=snapshot.slice();pendingBytes=snapshot.reduce((n,c)=>n+c.data.byteLength,0);
      }else video.currentTime=pos;
      spoken=new Set(cues.filter(c=>c.end<=pos).map(c=>c.id));
      for(const c of cues){c.resume=c.start<=pos && c.end>pos;c.resumeOffset=c.resume?Math.max(0,pos-c.start):0;}
      cacheStats.seeks++;cacheStats.last={kind:'ram',source:time,position:pos,epoch};started=true;held=true;
      status('Перемотка из памяти; перевод повторно не запускается');
    }catch(e){cacheStats.failures++;$('error').textContent=e.message;userPaused=true;}
    finally{if(epoch===ownEpoch)cacheSeekBusy=false;}
    return;
  }
  cacheStats.last={kind:'outside',source:time,from:sourceTime(earliestRetained),through:sourceTime(readyThrough),epoch};
  invalidate();status('Выбран момент вне готового RAM-архива: новый захват и перевод…');worker('seek',{time});
}
function status(s){$('status').textContent=s;}
function silence(){
  if(currentDub){spoken.delete(currentDub.id);currentDub.resume=true;currentDub.resumeOffset=dubAudio.currentTime;}
  currentDub=null;dubHold=false;dubAudio.onended=null;dubAudio.onerror=null;dubAudio.onloadedmetadata=null;dubAudio.pause();dubAudio.removeAttribute('src');
  if(dubURL){URL.revokeObjectURL(dubURL);dubURL=null;}
  if(preparedDub){preparedDub.audio.removeAttribute('src');URL.revokeObjectURL(preparedDub.url);preparedDub=null;}
}
function invalidate(){epoch=null;video.pause();silence();cues=[];spoken.clear();$('subtitle').textContent='';readyThrough=0;started=false;}
function resync(reason){$('error').textContent=reason;invalidate();bus.postMessage({type:'resync'});}
function reset(m){
  encodedMedia?.close();encodedMedia=null;
  $('error').textContent='';transport={pendingPackets:0,audioSeconds:0};processing={};revealControls();
  invalidate();epoch=m.epoch;settings=m.settings;head=0;readyThrough=0;pendingBytes=0;appendQueue=[];ledger=[];held=false;
  playPending=false;autoplayBlocked=false;unlocked=true;
  captureArchive=new CaptureArchive();capacityStopRequested=false;preparingAppend=false;targetIncrease=0;rebuildTarget=null;cacheSeekBusy=false;earliestRetained=0;translatedRanges=[];lastInputEnd=0;trackInfo=m.track||{};
  lastMediaAt=performance.now();lastResultAt=performance.now();
  captureEnded=false;clockSamples=[];settings.sourceStart=ramMode?(settings.sourceStart??lastSource.time??0):(lastSource.time??settings.sourceStart??0);$('delay').value=settings.delay;
  if(subtitleMode!==settings.mode){subtitleMode=settings.mode;subtitlePreference=null;}
  showSubtitles=subtitlePreference??settings.mode!=='voice';$('subtitles').checked=showSubtitles;$('subtitles').disabled=false;
  video.volume=settings.mode==='subtitles'?1:Number($('original').value);
  video.defaultPlaybackRate=Number($('speed').value);video.playbackRate=video.defaultPlaybackRate;metrics.resets++;
  if(ramMode){
    encodedMedia=new EncodedMedia(video,m.tracks,message=>{$('error').textContent=message;userPaused=true;video.pause();});
    video.currentTime=0;buffer=null;status('Исходные сжатые фрагменты в RAM; накапливаем перевод…');return;
  }
  if(nativeMode){video.currentTime=0;buffer=null;status('Исходное видео YouTube; накапливаем перевод…');return;}
  decoderMime=m.mime;createDecoder(m.mime);status('Накопление захваченного видео и перевода…');
}
function createDecoder(mime){
  if(url)URL.revokeObjectURL(url);
  mediaSource=new MediaSource();url=URL.createObjectURL(mediaSource);video.src=url;video.playbackRate=Number($('speed').value);
  const ownEpoch=epoch,ownGeneration=++decoderGeneration;buffer=null;preparingAppend=false;ledger=[];
  mediaSource.addEventListener('sourceopen',()=>{
    if(epoch!==ownEpoch || decoderGeneration!==ownGeneration)return;
    buffer=mediaSource.addSourceBuffer(mime);buffer.mode='segments';
    buffer.addEventListener('updateend',()=>{if(decoderGeneration===ownGeneration)pump();});
    buffer.addEventListener('error',()=>{if(decoderGeneration===ownGeneration)resync('Ошибка декодирования буфера. Повторный захват.');});pump();
  },{once:true});
}
async function pump(){
  if(ramMode){encodedMedia?.pump();return;}
  if(nativeMode || cacheSeekBusy || !buffer || buffer.updating || !epoch || preparingAppend)return;
  if(rebuildTarget!==null && buffer.buffered.length){
    const end=buffer.buffered.end(buffer.buffered.length-1);
    if(end>rebuildTarget+.1){video.currentTime=rebuildTarget;rebuildTarget=null;}
    else if(end>10 && buffer.buffered.start(0)<end-10){buffer.remove(0,end-8);return;}
  }
  // Keep only a short decoder window; the separate Blob archive can retain hours.
  if(video.currentTime>12 && buffer.buffered.length && buffer.buffered.start(0)<video.currentTime-10){
    const before=video.currentTime-8;ledger=ledger.filter(entry=>entry.end>before);
    buffer.remove(0,before);return;
  }
  if(rebuildTarget===null && video.buffered.length && video.buffered.end(video.buffered.length-1)>video.currentTime+decodeAhead)return;
  const next=appendQueue.shift();if(!next)return;
  preparingAppend=true;const ownEpoch=epoch;
  try{
    const bytes=next.data;
    if(epoch!==ownEpoch)return;
    buffer.appendBuffer(bytes);pendingBytes-=bytes.byteLength;ledger.push({end:next.end,bytes:bytes.byteLength});
  }catch(e){
    if(epoch!==ownEpoch)return;
    appendQueue.unshift(next);
    if(e.name==='QuotaExceededError' && decodeAhead>5){decodeAhead=Math.max(5,decodeAhead/2);$('error').textContent='Сокращено окно декодера; архив сохранён.';}
    else{$('error').textContent='Ошибка декодера: '+e.message;video.pause();}
  }finally{if(epoch===ownEpoch)preparingAppend=false;}
}
function memoryUsed(){return captureArchive.bytes+(encodedMedia?.bytes||0)+(transport.sourceCacheBytes||0)+cues.reduce((sum,c)=>sum+(c.audioBytes?.byteLength||0),0)+(transport.audioSeconds||0)*32000;}
function checkCapacity(){
  if(!capacityStopRequested && memoryUsed()>limitBytes()-16*1048576){
    capacityStopRequested=true;bus.postMessage({type:'capacity-stop'});
    $('error').textContent='Лимит архива: источник остановлен. Накопленное видео сохранено.';
  }
}
// Blob conversion must remain ordered, even while source buffer is busy.
let mediaChain=Promise.resolve();
bus.onmessage=e=>{
  const m=e.data;
  if(m.type==='reset' && m.settings){reset(m);return;}
  if(m.type==='invalidated'){invalidate();status('Перемотка источника…');return;}
  if(m.type==='error'){$('error').textContent=m.message;return;}
  if(m.type==='warning'){$('error').textContent=m.message;return;}
  if(m.type==='overflow'){$('error').textContent=m.message;invalidate();return;}
  if(m.type==='stopped'){stopped=true;invalidate();status('Захват остановлен');return;}
  if(m.type==='source'){
    lastSource=m;
    if(Number.isFinite(m.captureTime)){
      const firstClock=clockSamples.length===0;
      clockSamples.push({captureTime:m.captureTime,time:m.time});
      clockSamples=clockSamples.filter(item=>$('keepHistory').checked || item.captureTime>video.currentTime-20);
      if((nativeMode||ramMode) && firstClock && epoch && !started)video.currentTime=0;
    }
    if(m.duration>0){$('timeline').max=m.duration;$('timeline').disabled=false;$('sourceDuration').textContent=formatTime(m.duration);}
    return;
  }
  if(m.epoch!==epoch)return;
  if(m.type==='transport'){transport=m;checkCapacity();return;}
  if(m.type==='processing'){processing=m;return;}
  if(m.type==='progress'){head=m.head;lastMediaAt=performance.now();return;}
  if(m.type==='encoded'){lastMediaAt=performance.now();encodedMedia?.accept(m).then(checkCapacity);return;}
  if(m.type==='ended'){captureEnded=true;head=m.head;status('Источник завершён; доигрывание буфера');return;}
  if(m.type==='media'){
    head=m.head;pendingBytes+=m.blob.size;metrics.mediaBytes+=m.blob.size;
    lastMediaAt=performance.now();
    mediaClock={audioHead:m.head,wallHead:m.wallHead,recorderTimecode:m.recorderTimecode};
    const ownEpoch=epoch;
    mediaChain=mediaChain.then(async()=>{
      const data=await m.blob.arrayBuffer();if(epoch!==ownEpoch)return;
      const chunk=await captureArchive.add(data,m.seq??captureArchive.next,m.head);if(epoch!==ownEpoch)return;appendQueue.push(chunk);checkCapacity();pump();
    }).catch(e=>$('error').textContent=e.message);
  }
  if(m.type==='result'){
    lastResult=m;processing={};metrics.results++;
    const begin=(m.start??0)<=lastInputEnd+.25?readyThrough:(m.start??0),end=m.readyThrough??m.end;
    lastInputEnd=Math.max(lastInputEnd,m.end??0);readyThrough=Math.max(readyThrough,end);
    if(end>begin){const last=translatedRanges.at(-1);if(last && begin<=last[1]+.1)last[1]=Math.max(last[1],end);else translatedRanges.push([begin,end]);}
    lastResultAt=performance.now();
    if(m.speakers){speakerList=m.speakers;renderSpeakers();}
    for(const cue of m.cues){
      if(cue.tts_warning)$('error').textContent=cue.tts_warning;
      cue.id=crypto.randomUUID();cue.epoch=epoch;cues.push(cue);metrics.lastCue={text:cue.text,start:cue.start,end:cue.end};
      if(cue.audio){
        const bytes=Uint8Array.from(atob(cue.audio),c=>c.charCodeAt(0));delete cue.audio;
        cue.audioBytes=bytes;cue.audioDigest=CaptureArchive.hash(bytes);
      }
    }
    cues.sort((a,b)=>a.start-b.start||a.end-b.end);
    checkCapacity();
  }
};
function prepareNextCue(){
  if(!currentDub || preparedDub || settings.mode==='subtitles')return;
  const next=cues.find(c=>!spoken.has(c.id) && c.audioBytes && c.epoch===epoch);if(!next)return;
  const audio=new Audio(),url=URL.createObjectURL(new Blob([next.audioBytes],{type:'audio/wav'}));
  audio.preload='auto';audio.preservesPitch=true;audio.src=url;audio.load();preparedDub={cue:next,audio,url,epoch};
}
function playCue(cue){
  if(spoken.has(cue.id) || !cue.audioBytes || currentDub)return;
  spoken.add(cue.id);
  const late=video.currentTime-cue.start;
  const wasResume=cue.resume,offset=wasResume?(cue.resumeOffset||0):0;
  currentDub=cue;cue.resume=false;
  if(preparedDub?.cue===cue && preparedDub.epoch===epoch){dubAudio=preparedDub.audio;dubURL=preparedDub.url;preparedDub=null;metrics.preloadedStarts=(metrics.preloadedStarts||0)+1;}
  else{dubAudio=new Audio();dubURL=URL.createObjectURL(new Blob([cue.audioBytes],{type:'audio/wav'}));dubAudio.src=dubURL;}
  dubAudio.volume=Number($('dub').value);dubAudio.preservesPitch=true;
  const ownEpoch=epoch;
  const positionAudio=()=>{
    if(currentDub!==cue || epoch!==ownEpoch)return;
    dubAudio.currentTime=Math.min(offset,Math.max(0,dubAudio.duration-.01));
    // A fixed voice tempo: do not squeeze each sentence into its source slot.
    cue.fit=1;dubAudio.playbackRate=video.playbackRate;
  };
  if(dubAudio.readyState>=1)positionAudio();else dubAudio.onloadedmetadata=positionAudio;
  dubAudio.onended=()=>{if(currentDub===cue){currentDub=null;if(dubURL){URL.revokeObjectURL(dubURL);dubURL=null;}
    metrics.lastDubEndedAt=performance.now();
    const next=cues.find(c=>c.start<=video.currentTime+.03 && !spoken.has(c.id) && c.audioBytes);
    if(next && !userPaused && ((!video.paused && video.readyState>=3) || video.ended)){next.continuousJoin=true;playCue(next);}
  }};
  dubAudio.onerror=()=>{if(currentDub===cue){currentDub=null;$('error').textContent='Не удалось декодировать сохранённую русскую дорожку';}};
  dubAudio.play().then(()=>{
    if(currentDub!==cue)return;metrics.played++;
    if(cue.continuousJoin){metrics.joinGapsMs??=[];metrics.joinGapsMs.push(Math.round(performance.now()-metrics.lastDubEndedAt));if(metrics.joinGapsMs.length>100)metrics.joinGapsMs.shift();cue.continuousJoin=false;}
    metrics.lastSpeechDelayMs=Math.round(Math.max(0,video.currentTime-cue.start)*1000);
    metrics.maxSpeechDelayMs=Math.max(metrics.maxSpeechDelayMs||0,metrics.lastSpeechDelayMs);
    metrics.speechRateMin=Math.min(metrics.speechRateMin??dubAudio.playbackRate,dubAudio.playbackRate);
    metrics.speechRateMax=Math.max(metrics.speechRateMax??dubAudio.playbackRate,dubAudio.playbackRate);
    if(!wasResume){metrics.audioStartOffsetsMs.push(Math.round(Math.max(0,video.currentTime-cue.start)*1000));if(metrics.audioStartOffsetsMs.length>100)metrics.audioStartOffsetsMs.shift();}
  }).catch(e=>{if(epoch!==ownEpoch || currentDub!==cue || video.paused)return;spoken.delete(cue.id);currentDub=null;if(e.name==='NotAllowedError')blockAutoplay();else{$('error').textContent='Не удалось воспроизвести русскую дорожку: '+e.message;userPaused=true;video.pause();}});
  prepareNextCue();
}
setInterval(()=>{
  bus.postMessage({type:'heartbeat'});
  renderBufferStatus();
  updateControls();
  renderPlayButton();
  if(!epoch || stopped)return;
  const delay=Number($('delay').value)||20, lag=head-video.currentTime;
  const safe=readyThrough-video.currentTime;
  pump();
  if(cacheSeekBusy || rebuildTarget!==null)return;
  const allTranslated=captureEnded && readyThrough>=head-.4;
  const remainingAudio=cues.some(c=>c.start<=video.currentTime+.3 && c.end>video.currentTime && settings.mode!=='subtitles' && !c.audioBytes);
  if(unlocked && !userPaused && !dubHold && video.buffered.length){
    if(!started && startupReady()){
      started=true;startVideo();
    } else if(started && (((safe<.3 && !allTranslated) || (targetIncrease && lag<targetIncrease)) || remainingAudio)){
      if(!video.paused){held=true;metrics.autoPauseEvents++;metrics.bufferEvents??=[];metrics.bufferEvents.push({position:video.currentTime,ready:safe,captured:lag,stage:processing.stage,reason:remainingAudio?'audio':targetIncrease?'delay':'translation'});metrics.bufferEvents=metrics.bufferEvents.slice(-30);video.pause();silence();}
    } else if(started && video.readyState>=3 && video.paused && held && (allTranslated || safe>=Math.min(8,Math.max(3,delay/6))) && (!targetIncrease || lag>=targetIncrease) && !remainingAudio){
      held=false;targetIncrease=0;startVideo();
    }
  }
  if(allTranslated && !appendQueue.length && !pendingBytes && !preparingAppend && buffer && !buffer.updating && mediaSource.readyState==='open'){
    try{mediaSource.endOfStream();}catch{}
  }
  if(ramMode && allTranslated)encodedMedia?.finish(sourceTime(head));
  const now=video.currentTime;
  if(!$('keepHistory').checked){
    cues=cues.filter(c=>{if(c.end<=now-10){spoken.delete(c.id);return false;}return true;});
    captureArchive.prune(now-10);earliestRetained=Math.max(earliestRetained,now-10);
    if(ramMode)encodedMedia?.prune(sourceTime(now-10));
  }
  const current=cues.filter(c=>c.start<=now && c.end>=now);
  const displayed=currentDub && settings.mode!=='subtitles'?[currentDub]:current;
  $('subtitle').textContent=showSubtitles?displayed.map(c=>(speakerList.length>1?c.speaker_label+': ':'')+c.text).join('\n'):'';
  if(!scrubbing){const time=sourceTime(now);$('timeline').value=time;$('sourcePosition').textContent=formatTime(time);}
  const speechPending=cues.some(c=>c.start<=now && !spoken.has(c.id) && c.audioBytes);
  if(unlocked && !userPaused && ((!video.paused && video.readyState>=3) || video.ended)){const next=cues.find(c=>c.start<=now && !spoken.has(c.id) && c.audioBytes);if(next)playCue(next);}
  prepareNextCue();
  if(userPaused)status('Пауза плеера; источник продолжает захват');
  else if(video.ended)status(currentDub || speechPending?'Доигрывается озвучка':'Просмотр завершён');
  else if(started)status(video.paused?'Ожидание перевода / накопление буфера':'Перевод воспроизводится');
  else status(head<delay?`Накопление буфера: ещё ${Math.ceil(delay-head)} сек. Начнётся автоматически.`:!unlocked?'Перевод готов. Нажмите «Включить звук» один раз.':lastResult.waiting_speakers?'Собираем образцы голосов для озвучки…':video.readyState<3?'Перевод готов; ожидаем кадры видео…':'Завершается перевод первых фраз…');
  if(ramMode && encodedMedia?.repairing)status('Перевод готов; восстанавливаем кадры из RAM…');
  if(ramMode && encodedMedia?.failed)status('Не удалось подготовить видео; смотрите сообщение об ошибке');
  if(autoplayBlocked)status('Перевод готов. Нажмите «Включить звук» один раз.');
  if(processing.stage==='error')status('Перевод остановлен из-за ошибки сервиса');
  renderPlayButton();
  $('metrics').textContent=`Захвачено: ${head.toFixed(1)} с · Плеер: ${now.toFixed(1)} с · Задержка: ${lag.toFixed(1)} с\nПереведено до: ${readyThrough.toFixed(1)} с · Очередь: ${lastResult.queue??0} · Архив: ${(memoryUsed()/1048576).toFixed(1)} / ${(limitBytes()/1048576).toFixed(0)} МиБ\nОбработка: ${(lastResult.process_s??0).toFixed(2)} с / ${(lastResult.input_s??0).toFixed(1)} с звука · ASR: ${(lastResult.asr_s??0).toFixed(2)} с\nОзвучено: ${metrics.played} · Источник: ${(lastSource.time??0).toFixed(1)} с`;
  $('archiveInfo').textContent=`Готовый архив: ${formatTime(sourceTime(earliestRetained))}–${formatTime(sourceTime(readyThrough))}. Возвратов из памяти: ${cacheStats.seeks}. ${nativeMode?'Видео хранится в кэше YouTube; RAM выше — только наш перевод.':'Порядок фрагментов и SHA-256 проверяются при возврате.'}`;
  $('streamInfo').textContent=ramMode?`Исходные сжатые сегменты YouTube · RAM ${(encodedMedia?.bytes/1048576||0).toFixed(1)} МиБ · ${frameStats.fps??'—'} FPS · без повторного кодирования`:
    nativeMode?`Исходное YouTube · ${video.nativeState().width||0}×${video.nativeState().height||0} · ${frameStats.fps??'—'} FPS · пропущено ${frameStats.dropped??0}`:`Захват ${trackInfo.width||'?'}×${trackInfo.height||'?'} · лимит ${trackInfo.frameRate||'?'} FPS · ${settings.videoMbps||6} Мбит/с · фактически ${frameStats.fps??'—'} FPS · пропущено ${frameStats.dropped??0}. Настройки потока — при следующем запуске.`;
},100);
setInterval(()=>{
  const now=performance.now(),q=video.getVideoPlaybackQuality(),elapsed=(now-frameSample.time)/1000;
  if(q.totalVideoFrames>=frameSample.total)frameStats={fps:video.paused?0:Number(((q.totalVideoFrames-frameSample.total)/elapsed).toFixed(1)),dropped:q.droppedVideoFrames,total:q.totalVideoFrames};
  frameSample={time:now,total:q.totalVideoFrames,dropped:q.droppedVideoFrames};
},2000);
video.addEventListener('pause',()=>{if(!video.ended && !dubHold)silence();});
video.addEventListener('waiting',()=>{metrics.waitingEvents++;if(!dubHold)silence();});
$('play').onclick=async()=>{
  if($('play').disabled)return;
  if(started && unlocked && !userPaused){userPaused=true;video.pause();silence();renderPlayButton();return;}
  unlocked=true;autoplayBlocked=false;userPaused=false;held=true;
  if(!video.ended && video.readyState>=3 && (started?readyThrough>video.currentTime+.3:startupReady())){started=true;await startVideo();}
  renderPlayButton();
};
$('pause').onclick=()=>{userPaused=true;video.pause();silence();};
$('stop').onclick=async()=>{stopped=true;invalidate();await worker('stop');status('Сессия остановлена');};
$('original').oninput=()=>video.volume=Number($('original').value);
$('dub').oninput=()=>dubAudio.volume=Number($('dub').value);
$('speed').onchange=()=>{video.defaultPlaybackRate=Number($('speed').value);video.playbackRate=video.defaultPlaybackRate;video.preservesPitch=true;dubAudio.playbackRate=video.playbackRate;};
$('memory').onchange=()=>{$('memory').value=limitBytes()/1048576;checkCapacity();};
$('delay').onchange=()=>{
  const target=Math.max(10,Math.min(60,Number($('delay').value)||60));$('delay').value=target;settings.delay=target;
  // This is a STARTUP setting, not a seek command. In particular, changing it
  // while gathering the first frames must not move or invalidate the decoder.
  targetIncrease=0;renderPlayButton();
};
$('seekButton').onclick=()=>seekSource(Number($('seek').value));
$('timeline').oninput=()=>{scrubbing=true;$('sourcePosition').textContent=formatTime(Number($('timeline').value));};
$('timeline').onchange=()=>{const time=Number($('timeline').value);scrubbing=false;seekSource(time);};
$('subtitles').onchange=()=>{subtitlePreference=$('subtitles').checked;showSubtitles=subtitlePreference;if(!showSubtitles)$('subtitle').textContent='';};
$('cleanVideo').onchange=()=>worker('clean-video',{enabled:$('cleanVideo').checked});
$('fullscreen').onclick=async()=>{if(nativeMode){video.command('fullscreen');return;}if(document.fullscreenElement)await document.exitFullscreen();else await $('stage').requestFullscreen();};
$('nativeQuality').onclick=()=>{userPaused=true;video.pause();silence();video.command('quality');};
$('settingsButton').onclick=()=>{const panel=document.querySelector('.settings');panel.open=!panel.open;$('settingsButton').setAttribute('aria-expanded',String(panel.open));};
document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='c' && !$('subtitles').disabled && !['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)){$('subtitles').checked=!$('subtitles').checked;$('subtitles').dispatchEvent(new Event('change'));}});
document.addEventListener('keydown',e=>{if(e.code==='Space' && !['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName)){e.preventDefault();$('play').click();}});
window.addEventListener('pagehide',()=>{if(!ramMode && !document.body.classList.contains('embedded'))worker('stop').catch(()=>{});});
// Text-only diagnostics for tests and reproducible measurements; no original media.
globalThis.translatorDiagnostics=()=>({build:'0.4.9',sessionId,epoch,head,position:video.currentTime,readyThrough,subtitles:showSubtitles,
  settings:{mode:settings.mode,voice:settings.voice,delay:Number($('delay').value)},metrics,
  source:{time:lastSource.time,paused:lastSource.paused,duration:lastSource.duration},unlocked,started,autoplayBlocked,playPending,
  paused:video.paused,videoReadyState:video.readyState,audioState:dubAudio.paused?'paused':'running',
  speed:video.playbackRate,preservesPitch:dubAudio.preservesPitch,archiveBytes:memoryUsed(),archiveLimitBytes:limitBytes(),capacityStopRequested,
  dubHold,
  speechRate:dubAudio.playbackRate,speechQueue:cues.filter(c=>c.start<=video.currentTime && !spoken.has(c.id) && c.audioBytes).length,
  mediaClock,
  transport,processing,nativeState:nativeMode?video.nativeState():null,controlsHidden:document.body.classList.contains('controls-hidden'),
  videoMode:ramMode?'ram':nativeMode?'native':'capture',encoded:ramMode?{bytes:encodedMedia?.bytes,chunks:encodedMedia?.records.length,tracks:encodedMedia?.tracks,rawPosition:video.raw.currentTime,target:video.targetSourceTime,decoder:encodedMedia?.diagnostics(),source:settings.sourceMeta}:null,
  trackInfo,frameStats,cacheStats,archiveChunks:captureArchive.chunks.length,archiveIntegrity:captureArchive.failure||'ordered',translatedRanges,
  speakers:speakerList,
  buffered:Array.from({length:video.buffered.length},(_,i)=>[video.buffered.start(i),video.buffered.end(i)]),
  originalVolume:video.volume,dubVolume:dubAudio.volume,pendingBytes,
  retainedMediaBytes:ledger.reduce((sum,item)=>sum+item.bytes,0),error:$('error').textContent});
setInterval(()=>{
  const value=globalThis.translatorDiagnostics();
  // Do not include transcript text in background diagnostics.
  value.metrics={...metrics,lastCue:metrics.lastCue?{start:metrics.lastCue.start,end:metrics.lastCue.end}:null};
  bus.postMessage({type:'diagnostics',value});
},1000);
worker('player-ready').then(r=>{if(r.error)$('error').textContent=r.error;});
