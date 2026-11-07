// Only our worker-created view tab embeds the delayed player. The captured
// source has a different, fixed tab ID and never contains this frame.
(async()=>{
  const cfg=await chrome.runtime.sendMessage({target:'worker',type:'view-config'}).catch(()=>null);
  if(!cfg?.sessionId)return;
  let frame=null,active=true,desiredPlaying=false,nativeControls=false,returnButton=null,seekAck=0,requestedSeek=null;
  const native=cfg.videoMode==='native',extensionOrigin=new URL(chrome.runtime.getURL('player.html')).origin;
  const muted=new WeakMap();
  function hush(event){const video=event?.target;if(active && video instanceof HTMLVideoElement && (!native || !desiredPlaying)){video.pause();if(!native)video.muted=true;}}
  document.addEventListener('play',hush,true);
  function mount(){
    if(!active)return;
    document.documentElement.classList.toggle('local-translator-native',native && !nativeControls);
    for(const video of document.querySelectorAll('video')){
      if(!muted.has(video)){muted.set(video,video.muted);if(native){video.volume=0;video.muted=false;}}
      if(!native || !desiredPlaying)video.pause();
      if(!native)video.muted=true;
    }
    const player=document.getElementById('movie_player');
    if(!player){if(frame)frame.hidden=true;return;}
    if(!frame){
      frame=document.createElement('iframe');
      frame.title='Локальный перевод YouTube';frame.allow='autoplay; fullscreen';frame.allowFullscreen=true;
      frame.src=chrome.runtime.getURL('player.html?embed=1&session='+cfg.sessionId+(native?'&native=1':''));
      frame.style.cssText='position:fixed;border:0;z-index:2147483647;background:'+(native?'transparent':'#000');
      if(native)frame.style.colorScheme='normal';
      document.documentElement.append(frame);
    }
    const rect=player.getBoundingClientRect();frame.hidden=nativeControls || rect.width<1 || rect.height<1;
    Object.assign(frame.style,{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px'});
  }
  function reply(value){frame?.contentWindow?.postMessage({type:'native-state',sessionId:cfg.sessionId,...value},extensionOrigin);}
  async function requestPosition(request){
    if(!active || requestedSeek!==request || request.busy)return;
    request.busy=true;request.lastAttempt=performance.now();request.attempts++;
    try{const result=await chrome.runtime.sendMessage({target:'worker',type:'native-seek',sessionId:cfg.sessionId,time:request.time});request.method=result?.method||'unavailable';}
    finally{request.busy=false;}
  }
  const stateTimer=native?setInterval(()=>{
    if(!active)return;
    const v=document.querySelector('video');if(!v)return;
    if(requestedSeek && seekAck!==requestedSeek.id){
      // Watch the actual clock, not an event that YouTube may have emitted
      // before our listener or before its MediaSource became ready.
      if(!v.seeking && v.readyState>=2 && Math.abs(v.currentTime-requestedSeek.time)<.35)seekAck=requestedSeek.id;
      else if(!desiredPlaying && v.readyState>=1 && performance.now()-requestedSeek.lastAttempt>1500 && requestedSeek.attempts<4)requestPosition(requestedSeek).catch(error=>reply({error:error.message}));
    }
    const q=v.getVideoPlaybackQuality();
    reply({time:v.currentTime,duration:Number.isFinite(v.duration)?v.duration:0,paused:v.paused,ended:v.ended,readyState:v.readyState,seeking:v.seeking,seekAck,fullscreen:Boolean(document.fullscreenElement),
      buffered:Array.from({length:v.buffered.length},(_,i)=>[v.buffered.start(i),v.buffered.end(i)]),
      width:v.videoWidth,height:v.videoHeight,totalFrames:q.totalVideoFrames,droppedFrames:q.droppedVideoFrames,
      seekTarget:requestedSeek?.time,seekId:requestedSeek?.id,seekMethod:requestedSeek?.method,seekAttempts:requestedSeek?.attempts,
      ad:!!document.querySelector('#movie_player.ad-showing')});
  },100):null;
  const command=async e=>{
    const m=e.data;
    if(!native || !active || e.source!==frame?.contentWindow || e.origin!==extensionOrigin || m?.type!=='native-command' || m.sessionId!==cfg.sessionId)return;
    const v=document.querySelector('video');if(!v)return;
    try{
      if(m.command==='play'){desiredPlaying=true;await v.play();}
      if(m.command==='pause'){desiredPlaying=false;v.pause();}
      if(m.command==='seek'){
        const time=Math.max(0,Number(m.time)||0),id=Number(m.seekId)||0;
        requestedSeek={id,time,attempts:0,lastAttempt:0,busy:false};
        await requestPosition(requestedSeek);
      }
      if(m.command==='volume'){v.muted=false;v.volume=Math.max(0,Math.min(1,Number(m.value)||0));}
      if(m.command==='speed'){v.preservesPitch=true;v.playbackRate=Math.max(.25,Math.min(2,Number(m.value)||1));}
      if(m.command==='fullscreen'){
        if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();
      }
      if(m.command==='quality'){
        desiredPlaying=false;v.pause();nativeControls=true;mount();
        if(!returnButton){returnButton=document.createElement('button');returnButton.textContent='Вернуть перевод';
          returnButton.style.cssText='position:fixed;top:12px;left:12px;z-index:2147483647;background:#e11d48;color:white;padding:12px;border:0;border-radius:6px;cursor:pointer';
          returnButton.onclick=()=>{nativeControls=false;returnButton.remove();returnButton=null;mount();};document.documentElement.append(returnButton);}
      }
    }catch(error){desiredPlaying=false;reply({error:error.message});}
  };
  window.addEventListener('message',command);
  const fsStyle=document.createElement('style');
  if(native){fsStyle.textContent=`html:fullscreen #movie_player{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;z-index:2147483646}
    html.local-translator-native #movie_player .ytp-chrome-bottom,html.local-translator-native #movie_player .ytp-chrome-top,
    html.local-translator-native #movie_player .ytp-gradient-bottom,html.local-translator-native #movie_player .ytp-gradient-top,
    html.local-translator-native #movie_player .ytp-pause-overlay{opacity:0!important;visibility:hidden!important;pointer-events:none!important}`;document.documentElement.append(fsStyle);}
  const observer=new MutationObserver(mount);observer.observe(document,{subtree:true,childList:true});mount();
  window.addEventListener('resize',mount);window.addEventListener('scroll',mount,{capture:true,passive:true});
  document.addEventListener('fullscreenchange',mount);
  document.addEventListener('yt-navigate-finish',()=>{
    if(new URL(location.href).searchParams.get('v')===cfg.videoId)return;
    active=false;desiredPlaying=false;clearInterval(stateTimer);observer.disconnect();window.removeEventListener('message',command);window.removeEventListener('resize',mount);window.removeEventListener('scroll',mount,true);document.removeEventListener('play',hush,true);document.removeEventListener('fullscreenchange',mount);frame?.remove();returnButton?.remove();fsStyle.remove();document.documentElement.classList.remove('local-translator-native');
    for(const video of document.querySelectorAll('video'))video.muted=muted.get(video)??false;
    chrome.runtime.sendMessage({target:'worker',type:'stop',sessionId:cfg.sessionId,keepView:true}).catch(()=>{});
  });
})();
