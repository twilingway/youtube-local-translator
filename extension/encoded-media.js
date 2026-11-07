class EncodedMedia {
  constructor(video,tracks,onError){
    this.video=video;this.tracks=tracks;this.onError=onError;this.records=[];this.bytes=0;this.next=0;this.chain=Promise.resolve();this.generation=0;this.recoveries=0;this.repairing=false;this.closed=false;this.failed=false;this.create();
  }
  create(){
    const generation=++this.generation;
    this.opened=false;
    this.buffers=new Map();this.queues=new Map();this.removing=new Set();this.source=new MediaSource();
    if(this.url)URL.revokeObjectURL(this.url);this.url=URL.createObjectURL(this.source);this.video.src=this.url;
    this.source.addEventListener('sourceopen',()=>{
      if(generation!==this.generation)return;
      for(const track of this.tracks)this.track(track.id,track.mime);
      for(const record of this.records)this.queue(record);
      this.opened=true;
      this.pump();
    },{once:true});
  }
  track(id,mime){
    if(this.buffers.has(id))return;
    const buffer=this.source.addSourceBuffer(mime);this.buffers.set(id,buffer);this.queues.set(id,[]);
    const generation=this.generation;
    buffer.addEventListener('updateend',()=>{if(generation===this.generation){this.removing.delete(id);this.video.synchronize();this.pump();}});
    buffer.addEventListener('error',()=>{this.failed=true;this.onError('Ошибка исходных сжатых фрагментов: '+mime);});
  }
  accept(message){
    this.chain=this.chain.then(async()=>{
      if(message.seq!==this.next++)throw Error('Пропущен исходный сжатый фрагмент');
      if(message.data?.byteLength>32*1048576)throw Error('Слишком большой исходный фрагмент');
      const record={...message,digest:message.data?await CaptureArchive.hash(message.data):null,end:null};
      this.records.push(record);this.bytes+=message.data?.byteLength||0;
      if(this.opened && this.source.readyState==='open'){this.queue(record);this.pump();}
    }).catch(error=>this.onError(error.message));return this.chain;
  }
  queue(record){
    if(record.op==='track'){this.track(record.track,record.mime);return;}
    if(!this.buffers.has(record.track))this.track(record.track,record.mime);
    this.queues.get(record.track).push(record);
  }
  pump(){
    if(this.closed || this.failed || !this.opened || this.source.readyState!=='open')return;
    // A native default seek/decoder jump may briefly report a future position.
    // While a requested seek is pending, retain and fill ITS frame window.
    const raw=this.video.raw,position=Math.max(0,this.video.pendingSourceTime??raw.currentTime);
    for(const [id,buffer]of this.buffers){
      const queue=this.queues.get(id);
      // abort is a parser reset, not media data. It must neither wait behind
      // the ahead-window throttle nor leave a partial MP4 fragment pending.
      if(queue?.[0]?.op==='abort' && !(buffer.updating && this.removing?.has(id))){
        queue.shift();try{buffer.abort();}catch(error){this.failed=true;this.onError('Не удалось сбросить видеопарсер: '+error.message);}continue;
      }
      if(buffer.updating)continue;
      if(buffer.buffered.length && buffer.buffered.start(0)<position-12){this.removing?.add(id);buffer.remove(0,position-8);continue;}
      const currentRange=Array.from({length:buffer.buffered.length},(_,i)=>[buffer.buffered.start(i),buffer.buffered.end(i)])
        .find(([a,b])=>position>=a-.25 && position<b);
      // A prefetched fragment at 120 s must not stop replay of queued 0 s
      // fragments. Throttle only the continuous range around our target.
      if(currentRange && currentRange[1]>position+30)continue;
      const record=this.queues.get(id).shift();if(!record)continue;
      try{
        if(record.op==='change'){buffer.changeType(record.mime);continue;}
        if(record.mode && buffer.mode!==record.mode)buffer.mode=record.mode;
        const offset=record.timestampOffset||0;
        if(buffer.timestampOffset!==offset)buffer.timestampOffset=offset;
        const start=record.appendWindowStart||0,end=Math.min(record.appendWindowEnd??Infinity,this.end??Infinity);
        if(buffer.appendWindowStart!==start || buffer.appendWindowEnd!==end){
          if(buffer.appendWindowEnd<=start)buffer.appendWindowEnd=Infinity;
          buffer.appendWindowStart=start;buffer.appendWindowEnd=end;
        }
        buffer.appendBuffer(record.data);
        buffer.addEventListener('updateend',()=>{record.end=buffer.buffered.length?buffer.buffered.end(buffer.buffered.length-1):record.end;},{once:true});
      }catch(error){this.queues.get(id).unshift(record);this.failed=true;this.onError(error.message);}
    }
    this.checkTarget();
  }
  checkTarget(){
    const target=this.video.pendingSourceTime;
    if(target===null){this.targetWait=null;return;}
    if(this.repairing || this.closed || this.failed)return;
    const ranges=Array.from(this.buffers.values(),b=>Array.from({length:b.buffered.length},(_,i)=>[b.buffered.start(i),b.buffered.end(i)]));
    // Wait for both tracks before diagnosing a lost window. A bounded rebuild
    // reuses retained bytes; it never seeks or downloads the source again.
    if(!ranges.length || ranges.some(r=>!r.length))return;
    if([...this.buffers.values()].some(b=>b.updating) || [...(this.queues?.values()||[])].some(q=>q.length)){this.targetWait=null;return;}
    const covered=ranges.every(r=>r.some(([a,b])=>target>=a-.25 && target<b));
    if(covered){this.targetWait=null;return;}
    // Appending towards a later seek target can legitimately take time. Only
    // rebuild if a track has already lost the requested earlier frames.
    if(!ranges.some(r=>r[0][0]>target+.25)){this.targetWait=null;return;}
    if(!this.targetWait || Math.abs(this.targetWait.target-target)>.02){this.targetWait={target,since:performance.now()};return;}
    if(performance.now()-this.targetWait.since<3000)return;
    this.targetWait=null;
    if(this.recoveries>=1){this.failed=true;this.onError('Не удалось восстановить нужные кадры из RAM. Завершите перевод, обновите исходную вкладку YouTube и запустите заново.');return;}
    this.recoveries++;this.repairing=true;
    this.seek(captureTime(target),true).catch(error=>{if(!this.closed){this.failed=true;this.onError('Не удалось восстановить видео из RAM: '+error.message);}}).finally(()=>{this.repairing=false;});
  }
  async seek(position,recovery=false){
    await this.chain;
    if(this.closed)return;
    if(!recovery){this.recoveries=0;this.failed=false;this.targetWait=null;}
    let prior=-1;
    for(const record of this.records){
      if(record.seq<=prior || (record.data && await CaptureArchive.hash(record.data)!==record.digest))throw Error('Повреждён RAM-кэш исходного видео');
      prior=record.seq;
    }
    if(this.closed)return;
    this.create();this.video.currentTime=position;
  }
  prune(before){this.records=this.records.filter(r=>r.op!=='append'||r.init||r.end===null||r.end>=before);this.bytes=this.records.reduce((n,r)=>n+(r.data?.byteLength||0),0);}
  finish(end){
    this.end=end;
    if(this.source.readyState!=='open')return;
    if([...this.queues.values()].every(q=>!q.length)&&[...this.buffers.values()].every(b=>!b.updating)){
      try{this.source.duration=end;this.source.endOfStream();}catch{}
    }
  }
  diagnostics(){return {recoveries:this.recoveries,repairing:this.repairing,failed:this.failed,rawReadyState:this.video.raw.readyState,
    pending:this.video.pendingSourceTime,tracks:Array.from(this.buffers,([id,b])=>{try{return {id,updating:b.updating,queued:this.queues.get(id)?.length??0,
      ranges:Array.from({length:b.buffered.length},(_,i)=>[b.buffered.start(i),b.buffered.end(i)])};}catch{return {id,unavailable:true};}})};}
  close(){this.closed=true;this.generation++;if(this.url)URL.revokeObjectURL(this.url);}
}
globalThis.EncodedMedia=EncodedMedia;
