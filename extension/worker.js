let starting = false;
const isPlayer=tab=>tab.url===chrome.runtime.getURL('player.html') || tab.url?.startsWith(chrome.runtime.getURL('player.html')+'?');
function isOwnedPlayer(tab,state){
  if(!tab)return false;
  if(isPlayer(tab))return true;
  if(state.playerMode!=='youtube' || tab.id!==state.playerTab)return false;
  try{return new URL(tab.url).hostname==='www.youtube.com' && new URL(tab.url).searchParams.get('v')===state.playerVideoId;}catch{return false;}
}
async function closeOldPlayers(except){
  const tabs=await chrome.tabs.query({});
  const ids=tabs.filter(tab=>isPlayer(tab) && tab.id!==except).map(tab=>tab.id);
  if(ids.length)await chrome.tabs.remove(ids);
}
async function stopSession(m){
      const state=await chrome.storage.session.get(['activeSession','sourceTab','playerTab','playerMode','playerVideoId']);
      const {activeSession,sourceTab,playerTab}=state;
      if(m.sessionId!==activeSession)return {ok:true,ignored:true};
      if(m.reason)await chrome.storage.session.set({lastError:m.reason});
      await chrome.runtime.sendMessage({target:'capture',type:'stop'}).catch(()=>{});
      if ((await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length) await chrome.offscreen.closeDocument();
      if(sourceTab)await chrome.tabs.sendMessage(sourceTab,{type:'clean-video',enabled:false}).catch(()=>{});
      await chrome.storage.session.remove(['pending','sourceTab','activeSession','playerTab','playerMode','playerVideoId']);
      if(playerTab) {
        const tab=await chrome.tabs.get(playerTab).catch(()=>null);
        if(tab && isOwnedPlayer(tab,state) && !m.keepView)await chrome.tabs.remove(playerTab);
      }
      if(sourceTab && !m.keepView)await chrome.tabs.update(sourceTab,{active:true}).catch(()=>{});

  return {ok:true};
}
chrome.runtime.onMessage.addListener((m, sender, respond) => {
  if (m.target !== 'worker') return;
  (async () => {
    if(m.type==='worker-build')return {build:'0.4.9'};
    if(m.type==='sample-start'){
      if((await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length)throw Error('Сначала завершите текущий перевод.');
      const tab=await chrome.tabs.get(m.tabId);
      if(!/^https:\/\/www\.youtube\.com\/watch\?/.test(tab.url||''))throw Error('Откройте исходный ролик YouTube.');
      const inspection=await chrome.scripting.executeScript({target:{tabId:m.tabId},func:prefix=>{
        const video=document.querySelector('video');return {ownView:[...document.querySelectorAll('iframe')].some(f=>f.src.startsWith(prefix)),paused:video?.paused??true,time:video?.currentTime||0};
      },args:[chrome.runtime.getURL('player.html')]});
      const info=inspection?.[0]?.result;if(info?.ownView || info?.paused)throw Error('Включите исходное видео со звуком.');
      await chrome.offscreen.createDocument({url:'sample-capture.html',reasons:['USER_MEDIA'],justification:'По запросу пользователя собрать45сек оригинальной речи для коротких сравнительных образцов'});
      try{
        const streamId=await chrome.tabCapture.getMediaStreamId({targetTabId:m.tabId});
        await chrome.storage.session.set({sampleOwned:true});
        const result=await chrome.runtime.sendMessage({target:'sample-capture',streamId,url:tab.url,title:tab.title||'',time:info?.time||0});
        if(result?.error)throw Error(result.error);
        await chrome.action.setBadgeText({text:'45'});
      }catch(error){await chrome.offscreen.closeDocument().catch(()=>{});await chrome.storage.session.remove('sampleOwned');throw error;}
    }else if(m.type==='sample-progress'||m.type==='sample-finished'){
      if(sender.url!==chrome.runtime.getURL('sample-capture.html'))return {ok:true,ignored:true};
      const {sampleOwned}=await chrome.storage.session.get('sampleOwned');if(!sampleOwned)return {ok:true,ignored:true};
      if(m.type==='sample-progress')await chrome.action.setBadgeText({text:String(m.remaining)});
      else{await chrome.action.setBadgeText({text:''});await chrome.storage.session.remove('sampleOwned');await chrome.offscreen.closeDocument().catch(()=>{});}
    }else if (m.type === 'start') {
      if (starting) throw new Error('Запуск уже выполняется');
      starting = true;
      let ownsOffscreen=false,cleanedSource=false;
      try {
        const contexts = await chrome.runtime.getContexts({contextTypes: ['OFFSCREEN_DOCUMENT']});
        if (contexts.length) {
          const state=await chrome.storage.session.get(['playerTab','playerMode','playerVideoId','activeSession','activeOptions']);
          const {playerTab}=state;
          let existing=playerTab?await chrome.tabs.get(playerTab).catch(()=>null):null;
          if(!existing)existing=(await chrome.tabs.query({})).find(isPlayer);
          if(existing && isOwnedPlayer(existing,state)) {
            const options={mode:m.mode,voice:m.voice,speakers:m.speakers!==false,speakerCount:Number(m.speakerCount??2),qualityMinute:m.qualityMinute!==false,delay:Number(m.delay)||60};
            if(m.mode && JSON.stringify(options)!==JSON.stringify(state.activeOptions)){
              const applied=await chrome.runtime.sendMessage({target:'capture',type:'configure',sessionId:state.activeSession,...options});
              if(applied?.error)throw Error(applied.error);
              await chrome.storage.session.set({activeOptions:options});
            }
            await chrome.storage.session.set({playerTab:existing.id});
            await chrome.windows.update(existing.windowId,{focused:true});
            await chrome.tabs.update(existing.id,{active:true});
            return {ok:true,existing:true};
          }
          throw new Error('Сначала остановите текущую сессию в плеере');
        }
        const health=await fetch('http://127.0.0.1:8765/health').then(r=>r.json()).catch(()=>null);
        if(!health?.ready)throw new Error('Дождитесь готовности локального сервиса в терминале запуска');
        const tab = await chrome.tabs.get(m.tabId);
        if (!/^https:\/\/www\.youtube\.com\/watch\?/.test(tab.url || '')) throw new Error('Откройте страницу видео youtube.com/watch');
        const inspection=await chrome.scripting.executeScript({target:{tabId:m.tabId},func:(prefix)=>{
          const ownView=[...document.querySelectorAll('iframe')].some(frame=>frame.src.startsWith(prefix));
          const video=document.querySelector('#movie_player video.html5-main-video')||document.querySelector('#movie_player video')||document.querySelector('video');
          return {ownView,hasVideo:!!video,paused:video?.paused,ended:video?.ended,readyState:video?.readyState,
            muted:video?.muted,volume:video?.volume,time:video?.currentTime};
        },args:[chrome.runtime.getURL('player.html')]});
        let sourceState=inspection?.[0]?.result;
        if(sourceState?.ownView)throw new Error('Это вкладка перевода. Откройте обычную вкладку YouTube и запустите исходное видео.');
        if(sourceState?.hasVideo && (sourceState.paused || sourceState.ended)){
          const playback=await chrome.scripting.executeScript({target:{tabId:m.tabId},world:'MAIN',func:async()=>{
            const video=document.querySelector('#movie_player video.html5-main-video')||document.querySelector('#movie_player video')||document.querySelector('video');if(!video)return {hasVideo:false};
            if(video.ended)video.currentTime=0;
            try{
              await Promise.race([video.play(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Видео ещё загружается')),4500))]);
            }catch(error){return {paused:video.paused,playError:error.name==='NotAllowedError'?'Chrome не разрешил автоматический запуск. Нажмите ▶ в YouTube и повторите «Переводить».':'Не удалось запустить YouTube. Дождитесь загрузки видео и повторите.'};}
            return {hasVideo:true,paused:video.paused,ended:video.ended,readyState:video.readyState,muted:video.muted,volume:video.volume,time:video.currentTime};
          }});
          sourceState={...sourceState,...playback?.[0]?.result};
          if(sourceState.playError)throw Error(sourceState.playError);
        }
        if(sourceState && (!sourceState.hasVideo || sourceState.paused || sourceState.ended || sourceState.readyState<2))throw new Error('Сначала включите исходное видео YouTube и дождитесь начала воспроизведения.');
        if(sourceState && (sourceState.muted || sourceState.volume===0))throw new Error('Включите звук в исходном видео. При захвате его прямой вывод отключится автоматически.');
        m.videoMode=['native','ram'].includes(m.videoMode)?m.videoMode:'capture';
        if(m.videoMode==='ram'){
          m.playerMode='tab';
          const probe=await chrome.scripting.executeScript({target:{tabId:m.tabId},world:'MAIN',func:()=>globalThis.__localTranslatorMediaTap?.info()||{available:false}});
          if(probe?.[0]?.result?.build!==chrome.runtime.getManifest().version)throw Error('Обновите саму исходную страницу YouTube: в ней остался старый обработчик захвата. Одного обновления расширения недостаточно.');
          if(probe?.[0]?.result?.sourceMeta?.binding==='unbound')throw Error('RAM-захват не связан с активным видео. Обновите исходную вкладку YouTube после обновления расширения.');
          if(!probe?.[0]?.result?.available || !probe[0].result.init)throw Error('Нет исходных сжатых фрагментов. Обновите вкладку YouTube после обновления расширения и снова включите видео.');
        }
        if(m.videoMode==='native' && m.playerMode!=='youtube')throw Error('Исходное видео доступно в режиме «На странице YouTube».');
        m.sourceStart=sourceState?.time||0;
        await chrome.scripting.executeScript({target: {tabId: m.tabId}, files: ['source.js']});
        await chrome.tabs.sendMessage(m.tabId,{type:'clean-video',enabled:true});
        cleanedSource=true;
        await chrome.offscreen.createDocument({url: 'offscreen.html', reasons: ['USER_MEDIA'], justification: 'Захват выбранной вкладки YouTube для локального перевода'});
        ownsOffscreen=true;
        const streamId = await chrome.tabCapture.getMediaStreamId({targetTabId: m.tabId});
        const sessionId=crypto.randomUUID();
        const playerMode=m.playerMode||'window',playerVideoId=new URL(tab.url).searchParams.get('v');
        await chrome.storage.session.set({pending: {...m,sessionId}, sourceTab: m.tabId,activeSession:sessionId,activeOptions:{mode:m.mode,voice:m.voice,speakers:m.speakers!==false,speakerCount:Number(m.speakerCount??2),qualityMinute:m.qualityMinute!==false,delay:Number(m.delay)||60},playerTab:null,playerMode,playerVideoId,videoMode:m.videoMode});
        const captured=await chrome.runtime.sendMessage({...m,streamId,sessionId,target:'capture',type:'start',waitForPlayer:true});
        if(captured?.error)throw new Error(captured.error);
        await closeOldPlayers();
        if(playerMode==='youtube'){
          const view=await chrome.tabs.create({url:'about:blank',active:false});
          await chrome.storage.session.set({playerTab:view.id});
          await chrome.tabs.update(view.id,{url:tab.url,active:true});
        }else if(playerMode==='tab'){
          const view=await chrome.tabs.create({url:chrome.runtime.getURL('player.html?'+(m.videoMode==='ram'?'ram=1&':'')+'session='+sessionId),active:true});
          await chrome.storage.session.set({playerTab:view.id});
        }else{
          const window=await chrome.windows.create({url: 'player.html?session='+sessionId, type: 'popup', width: 1120, height: 850});
          const playerTab=window.tabs?.[0]?.id;
          if(playerTab)await chrome.storage.session.set({playerTab});
        }
      } catch (e) {
        if (ownsOffscreen) {
          await chrome.offscreen.closeDocument().catch(()=>{});
          await chrome.storage.session.remove(['pending','sourceTab','activeSession','playerTab','playerMode','playerVideoId']);
        }
        if(cleanedSource)await chrome.tabs.sendMessage(m.tabId,{type:'clean-video',enabled:false}).catch(()=>{});
        throw e;
      } finally { starting = false; }
    } else if (m.type === 'player-ready') {
      const {pending,activeSession,playerTab} = await chrome.storage.session.get(['pending','activeSession','playerTab']);
      if (pending && pending.sessionId===m.sessionId) { await chrome.runtime.sendMessage({target:'capture',type:'ui-ready',sessionId:m.sessionId}); await chrome.storage.session.remove('pending'); }
      else if(m.sessionId===activeSession && sender.tab?.id===playerTab)await chrome.runtime.sendMessage({target:'capture',type:'resync-for-player',sessionId:m.sessionId}).catch(()=>{});
    } else if(m.type==='view-config'){
      const state=await chrome.storage.session.get(['playerTab','activeSession','playerMode','playerVideoId','videoMode']);
      return state.playerMode==='youtube' && sender.tab?.id===state.playerTab?{sessionId:state.activeSession,videoId:state.playerVideoId,videoMode:state.videoMode}:{};
    } else if (m.type === 'stop') {
      return stopSession(m);
    } else if(m.type==='cache-relay-ready'){
      const state=await chrome.storage.session.get(['activeSession','sourceTab','videoMode']);
      if(state.activeSession!==m.sessionId || state.sourceTab!==sender.tab?.id || state.videoMode!=='ram')return {ok:true,ignored:true};
      await chrome.storage.session.set({cacheRelayReady:m.sessionId});
    } else if(m.type==='cache-resync'){
      const state=await chrome.storage.session.get(['activeSession','sourceTab','videoMode','cacheGeneration','cacheRelayReady']);
      if(state.activeSession!==m.sessionId || state.videoMode!=='ram')return {ok:true,ignored:true};
      if(sender.tab && sender.tab.id!==state.sourceTab)return {ok:true,ignored:true};
      const generation=m.generation||state.cacheGeneration;
      if(!generation)return {ok:true,waiting:true};
      await chrome.storage.session.set({cacheGeneration:generation});
      await chrome.tabs.sendMessage(state.sourceTab,{type:'start-cache-relay',sessionId:m.sessionId});
      if(state.cacheRelayReady!==m.sessionId)return {ok:true,waiting:true};
      const result=await chrome.scripting.executeScript({target:{tabId:state.sourceTab},world:'MAIN',func:(session,generation)=>globalThis.__localTranslatorMediaTap?.start(session,generation,'local-translator-cache-relay')||{error:'MSE source tap unavailable'},args:[m.sessionId,generation]});
      if(result?.[0]?.result?.error)throw Error(result[0].result.error);
    } else if (m.type === 'source-event') {
      const {sourceTab} = await chrome.storage.session.get('sourceTab');
      if (sender.tab?.id === sourceTab) await chrome.runtime.sendMessage({...m,target:'capture'}).catch(()=>{});
    } else if(m.type==='native-seek'){
      const {playerTab,activeSession,videoMode}=await chrome.storage.session.get(['playerTab','activeSession','videoMode']);
      if(m.sessionId!==activeSession || sender.tab?.id!==playerTab || videoMode!=='native')return {ok:true,ignored:true};
      const time=Math.max(0,Number(m.time)||0);
      const result=await chrome.scripting.executeScript({target:{tabId:playerTab},world:'MAIN',func:target=>{
        const p=document.getElementById('movie_player'),v=document.querySelector('video');
        if(typeof p?.seekTo==='function'){p.seekTo(target,true);return {method:'youtube-player'};}
        if(v){v.currentTime=target;return {method:'media-element'};}
        return {method:'not-ready'};
      },args:[time]});
      return result?.[0]?.result||{method:'not-ready'};
    } else if (m.type === 'seek') {
      const {sourceTab,activeSession} = await chrome.storage.session.get(['sourceTab','activeSession']);
      if(m.sessionId!==activeSession)return {ok:true,ignored:true};
      if (sourceTab) await chrome.tabs.sendMessage(sourceTab, {type:'seek', time:m.time});
    } else if(m.type==='clean-video') {
      const {sourceTab,activeSession}=await chrome.storage.session.get(['sourceTab','activeSession']);
      if(m.sessionId===activeSession && sourceTab)await chrome.tabs.sendMessage(sourceTab,{type:'clean-video',enabled:m.enabled});
    } else if(m.type==='pause-source') {
      const {sourceTab,activeSession}=await chrome.storage.session.get(['sourceTab','activeSession']);
      if(m.sessionId===activeSession && sourceTab)await chrome.tabs.sendMessage(sourceTab,{type:'pause-source'});
    }
    return {ok:true};
  })().then(respond, e=>respond({error:e.message}));
  return true;
});
chrome.tabs.onRemoved.addListener(async id => {
  const state=await chrome.storage.session.get(['sourceTab','playerTab','activeSession','playerMode','playerVideoId']);
  const {sourceTab,playerTab,activeSession}=state;
  if(playerTab===id) {
    await stopSession({sessionId:activeSession,keepView:true}).catch(()=>{});
    return;
  }
  if (sourceTab === id) {
    await chrome.runtime.sendMessage({target:'capture',type:'stop'}).catch(()=>{});
    await chrome.offscreen.closeDocument().catch(()=>{});
    await chrome.storage.session.remove(['pending','sourceTab','activeSession','playerTab','playerMode','playerVideoId']);
    if(playerTab) {
      const tab=await chrome.tabs.get(playerTab).catch(()=>null);
      if(tab && isOwnedPlayer(tab,state))await chrome.tabs.remove(playerTab);
    }
  }
});
