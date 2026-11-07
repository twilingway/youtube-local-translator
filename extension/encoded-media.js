class EncodedMedia {
  constructor(video,tracks,onError){
    this.video=video;this.tracks=tracks;this.onError=onError;this.records=[];this.bytes=0;this.next=0;this.chain=Promise.resolve();this.generation=0;this.create();
  }
  create(){
    const generation=++this.generation;
    this.opened=false;
    this.buffers=new Map();this.queues=new Map();this.source=new MediaSource();
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
    buffer.addEventListener('updateend',()=>{if(generation===this.generation){this.video.synchronize();this.pump();}});
    buffer.addEventListener('error',()=>this.onError('Ошибка исходных сжатых фрагментов: '+mime));
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
    if(!this.opened || this.source.readyState!=='open')return;
    const raw=this.video.raw,position=Math.max(raw.currentTime,this.video.targetSourceTime);
    for(const [id,buffer]of this.buffers){
      if(buffer.updating)continue;
      if(buffer.buffered.length && buffer.buffered.start(0)<position-12){buffer.remove(0,position-8);continue;}
      if(buffer.buffered.length && buffer.buffered.end(buffer.buffered.length-1)>position+30)continue;
      const record=this.queues.get(id).shift();if(!record)continue;
      try{
        if(record.op==='change'){buffer.changeType(record.mime);continue;}
        const offset=record.timestampOffset||0;
        if(buffer.timestampOffset!==offset)buffer.timestampOffset=offset;
        const start=record.appendWindowStart||0,end=Math.min(record.appendWindowEnd??Infinity,this.end??Infinity);
        if(buffer.appendWindowStart!==start || buffer.appendWindowEnd!==end){
          if(buffer.appendWindowEnd<=start)buffer.appendWindowEnd=Infinity;
          buffer.appendWindowStart=start;buffer.appendWindowEnd=end;
        }
        buffer.appendBuffer(record.data);
        buffer.addEventListener('updateend',()=>{record.end=buffer.buffered.length?buffer.buffered.end(buffer.buffered.length-1):record.end;},{once:true});
      }catch(error){this.queues.get(id).unshift(record);this.onError(error.message);}
    }
  }
  async seek(position){
    await this.chain;
    let prior=-1;
    for(const record of this.records){
      if(record.seq<=prior || (record.data && await CaptureArchive.hash(record.data)!==record.digest))throw Error('Повреждён RAM-кэш исходного видео');
      prior=record.seq;
    }
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
  close(){this.generation++;if(this.url)URL.revokeObjectURL(this.url);}
}
globalThis.EncodedMedia=EncodedMedia;
