// The parent is our worker-owned YouTube view, never the captured source tab.
function createNativeVideo(sessionId){
  const events=new EventTarget();
  let state={time:0,paused:true,ended:false,readyState:0,buffered:[]},pendingPosition=null,volume=0,speed=1,seekId=0,seekTimer=null;
  const send=(command,extra={})=>parent.postMessage({type:'native-command',sessionId,command,...extra},'https://www.youtube.com');
  const ranges=()=>state.buffered.map(([a,b])=>[Math.max(0,captureTime(a)),Math.max(0,captureTime(b))]);
  window.addEventListener('message',e=>{
    if(e.source!==parent || e.origin!=='https://www.youtube.com' || e.data?.type!=='native-state' || e.data.sessionId!==sessionId)return;
    if(e.data.error){document.getElementById('error').textContent='YouTube: '+e.data.error;return;}
    const before=state;state=e.data;
    if(state.ad){send('pause');document.getElementById('error').textContent='Реклама в плеере просмотра: пропустите её через «Качество YouTube», затем продолжите.';}
    if(pendingPosition!==null && state.seekAck===seekId && !state.seeking){pendingPosition=null;clearTimeout(seekTimer);const error=document.getElementById('error');if(error.textContent.startsWith('YouTube не подтвердил'))error.textContent='';}
    if(!before.paused && state.paused)events.dispatchEvent(new Event('pause'));
    if(before.readyState>=3 && state.readyState<3 && !state.paused)events.dispatchEvent(new Event('waiting'));
  });
  return {
    native:true,
    get currentTime(){return pendingPosition??Math.max(0,captureTime(state.time));},
    set currentTime(value){
      clearTimeout(seekTimer);pendingPosition=value;const id=++seekId;send('seek',{time:sourceTime(value),seekId:id});
      seekTimer=setTimeout(()=>{if(pendingPosition!==null && seekId===id){send('pause');document.getElementById('error').textContent='YouTube не подтвердил позицию видео. Ожидаем загрузку; озвучка не будет запускаться на неверном кадре.';}},15000);
    },
    get paused(){return state.paused;},get ended(){return state.ended;},get readyState(){return pendingPosition!==null || state.seeking?0:state.readyState;},
    get buffered(){const r=ranges();return {length:r.length,start:i=>r[i][0],end:i=>r[i][1]};},
    get volume(){return volume;},set volume(value){volume=value;send('volume',{value});},
    get playbackRate(){return speed;},set playbackRate(value){speed=value;send('speed',{value});},defaultPlaybackRate:1,preservesPitch:true,
    play(){send('play');return Promise.resolve();},pause(){send('pause');},
    addEventListener(...args){events.addEventListener(...args);},
    getVideoPlaybackQuality(){return {totalVideoFrames:state.totalFrames||0,droppedVideoFrames:state.droppedFrames||0};},
    nativeState:()=>state,command:send
  };
}
