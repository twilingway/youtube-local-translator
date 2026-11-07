(() => {
  if (globalThis.localTranslatorInstalled) return;
  globalThis.localTranslatorInstalled = true;
  let video, lastURL=location.href;
  const send = type => chrome.runtime.sendMessage({target:'worker',type:'source-event',event:type,
    time:video?.currentTime || 0, duration:Number.isFinite(video?.duration)?video.duration:0,
    paused:video?.paused, rate:video?.playbackRate || 1}).catch(()=>{});
  const clean = enabled => {
    let style=document.getElementById('local-translator-clean-style');
    if(enabled && !style){
      style=document.createElement('style');style.id='local-translator-clean-style';
      style.textContent=`html.local-translator-clean,html.local-translator-clean body{overflow:hidden!important;background:black!important}
        html.local-translator-clean #movie_player{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;max-width:none!important;max-height:none!important;z-index:2147483647!important;background:black!important}
        html.local-translator-clean #movie_player .html5-video-container{position:absolute!important;inset:0!important;width:100%!important;height:100%!important}
        html.local-translator-clean #movie_player video{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;object-fit:contain!important}
        html.local-translator-clean #masthead-container,html.local-translator-clean #secondary,html.local-translator-clean #below{visibility:hidden!important}`;
      document.documentElement.append(style);
    }
    document.documentElement.classList.toggle('local-translator-clean',enabled);
    if(!enabled){style?.remove();document.getElementById('local-translator-cache-relay')?.remove();}
    window.dispatchEvent(new Event('resize'));
  };
  const bind = () => {
    const found=document.querySelector('#movie_player video.html5-main-video')||document.querySelector('#movie_player video')||document.querySelector('video');
    if(found && found!==video) {
      video=found;
      for(const name of ['seeking','seeked','ended','ratechange']) video.addEventListener(name,()=>send(name));
      send('seeked');
    }
    if(location.href!==lastURL) {lastURL=location.href;send('navigation');}
    send('clock');
  };
  setInterval(bind,500); bind();
  chrome.runtime.onMessage.addListener(m=>{
    if(m.type==='start-cache-relay'){
      let frame=document.getElementById('local-translator-cache-relay');
      if(!frame){frame=document.createElement('iframe');frame.id='local-translator-cache-relay';frame.hidden=true;frame.src=chrome.runtime.getURL('cache-relay.html?session='+m.sessionId);document.documentElement.append(frame);}
    }
    if(m.type==='clean-video')clean(m.enabled);if(m.type==='pause-source' && video)video.pause();if(m.type==='seek' && video) {
    const target=Math.max(0,Number(m.time)||0);
    if(Math.abs(video.currentTime-target)<.05)send('seeked');else video.currentTime=target;
  }});
})();
