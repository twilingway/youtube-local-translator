// Runs in the source page MAIN world before its MediaSource is constructed.
// Source bytes stay in RAM. There is no media fetch or recording API here.
(()=>{
  if(globalThis.__localTranslatorMediaTap || !globalThis.MediaSource || !globalThis.SourceBuffer)return;
  const sources=new WeakMap(),tracks=new WeakMap(),urls=new Map(),list=[];
  const maxBytes=128*1048576;
  let nextSource=0,nextTrack=0,active=null,totalBytes=0;
  const getSource=ms=>{let item=sources.get(ms);if(!item){item={id:++nextSource,ms,tracks:[],events:[],bytes:0};sources.set(ms,item);list.push(item);}return item;};
  const originalURL=URL.createObjectURL;
  URL.createObjectURL=function(value){const url=Reflect.apply(originalURL,this,[value]);if(value instanceof MediaSource)urls.set(url,getSource(value));return url;};
  const revoke=URL.revokeObjectURL;URL.revokeObjectURL=function(url){urls.delete(url);return Reflect.apply(revoke,this,[url]);};
  function current(){const v=document.querySelector('video');return urls.get(v?.currentSrc)||urls.get(v?.src)||list.at(-1);}
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
    const buffer=Reflect.apply(add,this,[mime]),source=getSource(this),track={id:String(++nextTrack),mime,source};
    source.tracks.push(track);tracks.set(buffer,track);retain(source,{op:'track',track:track.id,mime});return buffer;
  };
  const append=SourceBuffer.prototype.appendBuffer;
  SourceBuffer.prototype.appendBuffer=function(input){
    const result=Reflect.apply(append,this,[input]),track=tracks.get(this);
    if(track){
      const bytes=input instanceof ArrayBuffer?new Uint8Array(input):new Uint8Array(input.buffer,input.byteOffset,input.byteLength);
      try{retain(track.source,{op:'append',track:track.id,mime:track.mime,data:bytes.slice().buffer,init:isInit(bytes),
        timestampOffset:this.timestampOffset,appendWindowStart:this.appendWindowStart,appendWindowEnd:Number.isFinite(this.appendWindowEnd)?this.appendWindowEnd:null});}catch{}
    }
    return result;
  };
  const change=SourceBuffer.prototype.changeType;
  if(change)SourceBuffer.prototype.changeType=function(mime){
    const result=Reflect.apply(change,this,[mime]),track=tracks.get(this);
    if(track){track.mime=mime;retain(track.source,{op:'change',track:track.id,mime});}return result;
  };
  globalThis.__localTranslatorMediaTap={
    info(){const source=current();return {available:!!source?.tracks.length,tracks:source?.tracks.map(t=>({id:t.id,mime:t.mime}))||[],bytes:source?.bytes||0,
      time:document.querySelector('video')?.currentTime||0,init:!!source?.events.some(e=>e.init)};},
    start(session,generation,frameId){
      const source=current(),frame=document.getElementById(frameId);
      if(!source || !frame || !source.events.some(e=>e.init))return {error:'Нет исходных MSE-заголовков в RAM. Обновите исходную вкладку YouTube и запустите захват с начала.'};
      const origin=new URL(frame.src).origin;active={session,generation,frame,origin,source,seq:0};
      frame.contentWindow.postMessage({type:'cache-header',sessionId:session,generation,time:document.querySelector('video')?.currentTime||0,
        tracks:source.tracks.map(t=>({id:t.id,mime:source.events.find(e=>e.op==='track'&&e.track===t.id)?.mime||t.mime})),cacheBytes:source.bytes},origin);
      for(const event of source.events)deliver(event);
      return {ok:true,events:source.events.length,bytes:source.bytes};
    },
    stop(){active=null;}
  };
})();
