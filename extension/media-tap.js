// Runs in the source page MAIN world before its MediaSource is constructed.
// Source bytes stay in RAM. There is no media fetch or recording API here.
(()=>{
  if(globalThis.__localTranslatorMediaTap || !globalThis.MediaSource || !globalThis.SourceBuffer)return;
  const sources=new WeakMap(),tracks=new WeakMap(),urls=new Map(),list=[];
  const maxBytes=128*1048576;
  let nextSource=0,nextTrack=0,active=null,totalBytes=0;
  const mainVideo=()=>document.querySelector('#movie_player video.html5-main-video')||document.querySelector('#movie_player video')||document.querySelector('video');
  const getSource=ms=>{let item=sources.get(ms);if(!item){item={id:++nextSource,ms,tracks:[],events:[],bytes:0};sources.set(ms,item);list.push(item);}return item;};
  const originalURL=URL.createObjectURL;
  URL.createObjectURL=function(value){const url=Reflect.apply(originalURL,this,[value]);if(value instanceof MediaSource)urls.set(url,getSource(value));return url;};
  // Revoking the URL after sourceopen is normal MSE usage: the video keeps
  // playing its attached source. Keep our provenance association as well.
  // Never guess the latest source: it may be a recommendation/ad/preload.
  function current(){const v=mainVideo();return urls.get(v?.currentSrc)||urls.get(v?.src)||null;}
  const ranges=buffer=>{try{return Array.from({length:buffer.length},(_,i)=>[buffer.start(i),buffer.end(i)]).slice(0,4);}catch{return [];}};
  function sourceMeta(source){
    const v=mainVideo();return {build:'0.4.9',binding:source?'video-url':'unbound',candidateCount:list.length,sourceId:source?.id??null,
      video:{time:v?.currentTime??0,readyState:v?.readyState??0,buffered:v?ranges(v.buffered):[],srcObject:Boolean(v?.srcObject)},
      tracks:source?.tracks.map(t=>{try{return {id:t.id,active:Array.from(source.ms.sourceBuffers).includes(t.buffer),mode:t.buffer.mode,
        timestampOffset:t.buffer.timestampOffset,buffered:ranges(t.buffer.buffered),appends:t.appends||0,inputBytes:t.inputBytes||0,
        copiedBytes:t.copiedBytes||0,foreignBuffers:t.foreignBuffers||0,copyErrors:t.copyErrors||0,aborts:t.aborts||0};}catch{return {id:t.id,unavailable:true};}})||[]};
  }
  function isInit(bytes){
    if(bytes.length>=4 && bytes[0]===0x1a && bytes[1]===0x45 && bytes[2]===0xdf && bytes[3]===0xa3)return true;
    const type=String.fromCharCode(...bytes.subarray(4,8));return type==='ftyp'||type==='moov';
  }
  function deliver(event){
    if(!active)return;
    if(!active.frame.isConnected || !active.frame.contentWindow){active=null;return;}
    const message={...event,type:'cache-data',sessionId:active.session,generation:active.generation,seq:active.seq++};
    if(event.data){message.data=event.data.slice(0);active.frame.contentWindow.postMessage(message,active.origin,[message.data]);}
    else active.frame.contentWindow.postMessage(message,active.origin);
  }
  function retain(source,event){
    source.events.push(event);source.bytes+=event.data?.byteLength||0;totalBytes+=event.data?.byteLength||0;
    while(totalBytes>maxBytes){
      const owner=list.find(s=>s.events.some(e=>e.op==='append'&&!e.init));if(!owner)break;
      const index=owner.events.findIndex(e=>e.op==='append'&&!e.init),size=owner.events[index].data.byteLength;
      owner.bytes-=size;totalBytes-=size;owner.events.splice(index,1);
    }
    if(active?.source===source)deliver({...event,cacheBytes:source.bytes});
  }
  const add=MediaSource.prototype.addSourceBuffer;
  MediaSource.prototype.addSourceBuffer=function(mime){
    const buffer=Reflect.apply(add,this,[mime]),source=getSource(this),track={id:String(++nextTrack),mime,source,buffer};
    source.tracks.push(track);tracks.set(buffer,track);retain(source,{op:'track',track:track.id,mime});return buffer;
  };
  const append=SourceBuffer.prototype.appendBuffer;
  SourceBuffer.prototype.appendBuffer=function(input){
    const result=Reflect.apply(append,this,[input]),track=tracks.get(this);
    if(track){
      track.appends=(track.appends||0)+1;track.inputBytes=(track.inputBytes||0)+(input.byteLength||0);
      try{
        // instanceof fails for ArrayBuffers created by another window/realm.
        // Use the BufferSource shape accepted by the native appendBuffer API.
        const view=ArrayBuffer.isView(input),bytes=view?new Uint8Array(input.buffer,input.byteOffset,input.byteLength):new Uint8Array(input);
        if(!view && !(input instanceof ArrayBuffer))track.foreignBuffers=(track.foreignBuffers||0)+1;
        if(bytes.byteLength!==input.byteLength)throw Error('BufferSource copy size mismatch');
        const data=bytes.slice().buffer;track.copiedBytes=(track.copiedBytes||0)+data.byteLength;
        retain(track.source,{op:'append',track:track.id,mime:track.mime,data,init:isInit(bytes),
          mode:this.mode,timestampOffset:this.timestampOffset,appendWindowStart:this.appendWindowStart,appendWindowEnd:Number.isFinite(this.appendWindowEnd)?this.appendWindowEnd:null});
      }catch{track.copyErrors=(track.copyErrors||0)+1;}
    }
    return result;
  };
  const abort=SourceBuffer.prototype.abort;
  if(abort)SourceBuffer.prototype.abort=function(){
    const result=Reflect.apply(abort,this,[]),track=tracks.get(this);
    if(track){track.aborts=(track.aborts||0)+1;retain(track.source,{op:'abort',track:track.id,mime:track.mime});}
    return result;
  };
  const change=SourceBuffer.prototype.changeType;
  if(change)SourceBuffer.prototype.changeType=function(mime){
    const result=Reflect.apply(change,this,[mime]),track=tracks.get(this);
    if(track){track.mime=mime;retain(track.source,{op:'change',track:track.id,mime});}return result;
  };
  globalThis.__localTranslatorMediaTap={
    info(){const source=current();return {build:'0.4.9',available:!!source?.tracks.length,tracks:source?.tracks.map(t=>({id:t.id,mime:t.mime}))||[],bytes:source?.bytes||0,
      time:mainVideo()?.currentTime||0,init:!!source?.events.some(e=>e.init),sourceMeta:sourceMeta(source)};},
    start(session,generation,frameId){
      const source=current(),frame=document.getElementById(frameId);
      if(!source)return {error:'Не удалось связать RAM-захват с активным YouTube-видео. Обновите исходную вкладку; другой медиапоток захватываться не будет.',sourceMeta:sourceMeta(null)};
      if(!frame || !source.events.some(e=>e.init))return {error:'Нет исходных MSE-заголовков в RAM. Обновите исходную вкладку YouTube и запустите захват с начала.'};
      const origin=new URL(frame.src).origin;active={session,generation,frame,origin,source,seq:0};
      frame.contentWindow.postMessage({type:'cache-header',sessionId:session,generation,time:mainVideo()?.currentTime||0,
        tracks:source.tracks.map(t=>({id:t.id,mime:source.events.find(e=>e.op==='track'&&e.track===t.id)?.mime||t.mime})),cacheBytes:source.bytes,sourceMeta:sourceMeta(source)},origin);
      for(const event of source.events)deliver(event);
      return {ok:true,events:source.events.length,bytes:source.bytes};
    },
    stop(){active=null;}
  };
})();
