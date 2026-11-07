let bus;
let uiReady=false,prePlayer=[],prePlayerBytes=0,startupTimer;
let encodedBus,cacheGeneration=null,sourceCacheBytes=0;
let flow,backlogStop=false,deliveryLag=0,maxDeliveryLag=0,lastPCMAt=0,maxPCMBurst=0,pcmBurst=0,burstAt=0,pcmEnd=null,pcmGapSeconds=0,pcmGapCount=0;
setInterval(()=>{if(alive && epoch && flow)emit({type:'transport',epoch,...flow.stats(),sourceCacheBytes,deliveryLag,maxDeliveryLag,maxPCMBurst,pcmGapSeconds,pcmGapCount,lastPCMSeconds:lastPCMAt?(performance.now()-lastPCMAt)/1000:0});},1000);
let stream,context,node,recorder,ws,epoch,settings,origin=0,wallOrigin=0,parts=[],partStart=0,samples=0,alive=false,resetting=false,captureEnded=false,quietSamples=0,hasSpeech=false,mediaSeq=0,lastProgress=0;
let monitor=setInterval(()=>{if(alive && uiReady && Date.now()-lastHeartbeat>12000) stop().finally(()=>chrome.runtime.sendMessage({target:'worker',type:'stop',sessionId:settings.sessionId}).catch(()=>{}));},3000),lastHeartbeat=Date.now();
function emit(message){
  if(uiReady){bus?.postMessage(message);return;}
  prePlayer.push(message);prePlayerBytes+=(message.blob?.size||0)+(message.data?.byteLength||0);
  if(message.type==='result')prePlayerBytes+=message.cues.reduce((sum,cue)=>sum+(cue.audio?.length||0),0);
  if(prePlayerBytes>(settings?.videoMode==='ram'?192:64)*1048576)abortStartup('Не удалось открыть плеер; накоплено слишком много данных.');
}
async function abortStartup(reason){
  if(!alive)return;
  uiReady=true;prePlayer=[];prePlayerBytes=0;
  await stop();
  chrome.runtime.sendMessage({target:'worker',type:'stop',sessionId:settings.sessionId,reason}).catch(()=>{});
}
function bytes64(bytes){let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(s);}
async function stop(){alive=false;epoch=null;clearTimeout(startupTimer);encodedBus?.close();if(recorder && recorder.state!=='inactive')recorder.stop();stream?.getTracks().forEach(t=>t.stop());if(context && context.state!=='closed')await context.close();ws?.close();emit({type:'stopped'});}
function flush(final=false){
  if(ws?.readyState!==WebSocket.OPEN)return;
  if(!samples){if(final)flow.enqueue(new Int16Array(0),partStart, true);return;}
  const pcm=new Int16Array(samples);let offset=0;for(const p of parts){pcm.set(p,offset);offset+=p.length;}
  if(ws.bufferedAmount>1024*1024){emit({type:'error',message:'WebSocket перегружен'});stop();return;}
  flow.enqueue(pcm,partStart,final);parts=[];samples=0;quietSamples=0;hasSpeech=false;
  if(flow.stats().audioSeconds>120 && !backlogStop){
    backlogStop=true;emit({type:'warning',message:'Накоплено больше 120 секунд звука. Источник остановлен; дорабатываем сохранённую очередь.'});
    chrome.runtime.sendMessage({target:'worker',type:'pause-source',sessionId:settings.sessionId}).then(()=>finishCapture('audio-backlog')).catch(fail);
  }
}
async function finishCapture(reason){
  if(captureEnded)return;
  captureEnded=true;const hadSamples=samples>0;flush(true);if(hadSamples)flow.enqueue(new Int16Array(0),partStart,true);const finalHead=context.currentTime-origin;
  if(recorder?.state==='recording')await new Promise(resolve=>{recorder.addEventListener('stop',resolve,{once:true});recorder.stop();});
  emit({type:'ended',epoch,head:finalHead,reason});
}
async function reset(){
  if(!alive || resetting)return;resetting=true;
  if(recorder && recorder.state!=='inactive') {await new Promise(resolve=>{recorder.addEventListener('stop',resolve,{once:true});recorder.stop();});}
  parts=[];samples=0;quietSamples=0;hasSpeech=false;captureEnded=false;backlogStop=false;epoch=crypto.randomUUID();origin=context.currentTime;wallOrigin=performance.now();flow.reset(epoch);
  pcmEnd=null;pcmGapSeconds=0;pcmGapCount=0;deliveryLag=0;maxDeliveryLag=0;maxPCMBurst=0;pcmBurst=0;burstAt=0;
  ws.send(JSON.stringify({type:'reset',epoch,mode:settings.mode,voice:settings.voice,speakers:settings.speakers!==false,speakerCount:settings.speakerCount??2,qualityMinute:settings.qualityMinute!==false}));
  mediaSeq=0;lastProgress=0;
  if(settings.videoMode==='ram'){
    recorder=null;cacheGeneration=crypto.randomUUID();
    const result=await chrome.runtime.sendMessage({target:'worker',type:'cache-resync',sessionId:settings.sessionId,generation:cacheGeneration});
    if(result?.error)throw Error(result.error);resetting=false;return;
  }
  if(settings.videoMode==='native'){
    recorder=null;emit({type:'reset',epoch,settings,mime:null});resetting=false;return;
  }
  const mime='video/webm;codecs=vp8,opus';
  if(!MediaRecorder.isTypeSupported(mime)) throw new Error('Chrome не поддерживает VP8/Opus MediaRecorder');
  recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:Math.max(1,Math.min(24,Number(settings.videoMbps)||6))*1000000,audioBitsPerSecond:96000});
  const currentEpoch=epoch;
  recorder.ondataavailable=e=>{if(e.data.size && epoch===currentEpoch)emit({type:'media',epoch,seq:mediaSeq++,blob:e.data,head:context.currentTime-origin,wallHead:(performance.now()-wallOrigin)/1000,recorderTimecode:e.timecode/1000});};
  recorder.onerror=e=>emit({type:'error',message:e.error?.message || 'Ошибка записи'});
  emit({type:'reset',epoch,settings,mime,track:stream.getVideoTracks()[0]?.getSettings()});recorder.start(1000);resetting=false;
}
async function start(m){
  bus=new BroadcastChannel('translator:'+m.sessionId);bus.onmessage=onBus;
  settings=m;alive=true;lastHeartbeat=Date.now();
  if(m.videoMode==='ram'){
    encodedBus=new BroadcastChannel('cache-input:'+m.sessionId);
    encodedBus.onmessage=event=>{
      const message=event.data;if(message.generation!==cacheGeneration || !alive || !epoch || captureEnded)return;
      sourceCacheBytes=message.cacheBytes??sourceCacheBytes;
      if(message.type==='cache-header'){
        settings.sourceStart=message.time-(context.currentTime-origin);
        emit({type:'reset',epoch,settings:{...settings},tracks:message.tracks,encoded:true});
      }else if(message.type==='cache-data')emit({...message,type:'encoded',epoch});
    };
  }
  uiReady=!m.waitForPlayer;prePlayer=[];prePlayerBytes=0;
  if(!uiReady)startupTimer=setTimeout(()=>abortStartup('Страница плеера не открылась за 30 секунд. Попробуйте отдельное окно.'),30000);
  ws=new WebSocket('ws://127.0.0.1:8765/ws');
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(new Error('Сервис не ответил за 10 секунд')),10000);
    ws.onerror=()=>{clearTimeout(timeout);reject(new Error('Запустите scripts/start.ps1'));};
    ws.onopen=()=>ws.send(JSON.stringify({type:'auth',token:LOCAL_CONFIG.token}));
    ws.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.type==='ready'){clearTimeout(timeout);resolve();}else if(msg.type==='error'){clearTimeout(timeout);reject(new Error(msg.message));}};
  });
  flow=new PCMQueue(item=>{
    const message={type:item.type,epoch:item.epoch,start:item.start,final:item.final};
    if(item.type==='pcm')message.data=bytes64(new Uint8Array(item.pcm.buffer,item.pcm.byteOffset,item.pcm.byteLength));
    ws.send(JSON.stringify(message));
  });
  ws.onmessage=e=>{const msg=JSON.parse(e.data);
    flow.accept(msg);
    if(msg.type==='error'){
      msg.message=msg.message||'Сервис не обработал фрагмент; очередь сохранена, источник остановлен.';
      if(flow.inflight && (!msg.epoch || msg.epoch===epoch)){
        chrome.runtime.sendMessage({target:'worker',type:'pause-source',sessionId:settings.sessionId}).then(()=>finishCapture('processing-error')).catch(fail);
      }
    }
    if(msg.type==='overflow'){emit(msg);reset().catch(fail);}else emit(msg);
  };
  ws.onclose=()=>{if(alive){emit({type:'error',message:'Соединение с сервисом закрыто'});stop();}};
  const height=[480,720,1080,1440,2160].includes(Number(m.videoHeight))?Number(m.videoHeight):1080;
  const fps=Number(m.videoFps)===30?30:60;
  stream=await navigator.mediaDevices.getUserMedia({audio:{mandatory:{chromeMediaSource:'tab',chromeMediaSourceId:m.streamId}},
    video:m.videoMode==='native'||m.videoMode==='ram'?false:{mandatory:{chromeMediaSource:'tab',chromeMediaSourceId:m.streamId,maxWidth:Math.round(height*16/9),maxHeight:height,maxFrameRate:fps}}});
  stream.getTracks().forEach(t=>t.onended=()=>{if(alive)stop();});
  context=new AudioContext();await context.audioWorklet.addModule('pcm-worklet.js');
  node=new AudioWorkletNode(context,'pcm');
  const source=context.createMediaStreamSource(stream);source.connect(node);
  const zero=context.createGain();zero.gain.value=0;node.connect(zero).connect(context.destination);
  node.port.onmessage=e=>{
    if(!alive || resetting || captureEnded || !epoch)return;
    const {pcm,time}=e.data;const relative=time-origin;if(relative<0)return;
    if(pcmEnd!==null && relative-pcmEnd>.03){pcmGapSeconds+=relative-pcmEnd;pcmGapCount++;}pcmEnd=relative+pcm.length/16000;
    lastPCMAt=performance.now();deliveryLag=Math.max(0,context.currentTime-time-pcm.length/16000);maxDeliveryLag=Math.max(maxDeliveryLag,deliveryLag);
    if(lastPCMAt-burstAt>100){burstAt=lastPCMAt;pcmBurst=0;}maxPCMBurst=Math.max(maxPCMBurst,++pcmBurst);
    if(!samples)partStart=relative;
    parts.push(pcm);samples+=pcm.length;
    if(settings.videoMode!=='capture' && relative-lastProgress>=.5){lastProgress=relative;emit({type:'progress',epoch,head:relative});}
    let power=0;for(const value of pcm)power+=(value/32768)**2;
    const speaking=Math.sqrt(power/pcm.length)>.009;
    if(speaking){hasSpeech=true;quietSamples=0;}else quietSamples+=pcm.length;
    try{
      if(samples>=80000 && hasSpeech && quietSamples>=8000)flush(true);
      else if(samples>=80000 && !hasSpeech)flush(true);
      else if(samples>=160000)flush(false);
    }catch(error){fail(error);}
  };
  await context.resume();await reset();
}
function fail(e){emit({type:'error',message:e.message});stop();}
chrome.runtime.onMessage.addListener((m,s,reply)=>{
  if(m.target!=='capture')return;
  (async()=>{
    if(m.type==='start')await start(m);
    if(m.type==='configure' && m.sessionId===settings?.sessionId){
      if(!alive)throw Error('Захват завершён. Завершите старую сессию и запустите перевод заново.');
      if(!['voice','both','subtitles'].includes(m.mode) || !['male','female'].includes(m.voice))throw Error('Неверный режим перевода');
      settings={...settings,mode:m.mode,voice:m.voice,speakers:m.speakers,speakerCount:m.speakerCount??2,qualityMinute:m.qualityMinute!==false,delay:m.delay||60};
      await reset();
    }
    if(m.type==='ui-ready' && m.sessionId===settings?.sessionId){
      uiReady=true;clearTimeout(startupTimer);lastHeartbeat=Date.now();
      for(const message of prePlayer)bus.postMessage(message);prePlayer=[];prePlayerBytes=0;
    }
    if(m.type==='resync-for-player' && m.sessionId===settings?.sessionId)await reset();
    if(m.type==='stop')await stop();
    if(m.type==='source-event'){
      emit({...m,type:'source',captureTime:context?context.currentTime-origin:0});
      if(m.event==='navigation'){emit({type:'error',message:'Страница YouTube сменилась. Запустите новую сессию.'});await stop();return;}
      if(m.event==='seeking'){epoch=null;parts=[];samples=0;emit({type:'invalidated'});}
      if(m.event==='seeked')await reset();
      if(m.event==='ended')await finishCapture('source-ended');
      if(m.event==='ratechange' && m.rate!==1){emit({type:'error',message:'Для прототипа установите скорость источника 1×'});await stop();}
    }
  })().then(()=>reply({ok:true}),e=>{fail(e);reply({error:e.message});});return true;
});
function onBus(e){
  if(e.data.type==='speaker-grammar' && epoch && ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'speaker-grammar',epoch,speaker_id:e.data.speaker_id,grammar:e.data.grammar}));
  if(e.data.type==='voice-map' && epoch && ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'voice-map',epoch,speaker_id:e.data.speaker_id,voice:e.data.voice}));
  if(e.data.type==='heartbeat')lastHeartbeat=Date.now();
  if(e.data.type==='resync')reset().catch(fail);
  if(e.data.type==='capacity-stop' && !captureEnded){
    chrome.runtime.sendMessage({target:'worker',type:'pause-source',sessionId:settings.sessionId}).then(()=>finishCapture('capacity')).catch(fail);
  }
  if(e.data.type==='diagnostics' && ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'diagnostics',epoch,value:e.data.value}));
}
