// Application-level backpressure: socket.bufferedAmount is not a model ACK.
class PCMQueue {
  constructor(send,maxSeconds=240){this.send=send;this.limit=maxSeconds*16000;this.reset(null);}
  reset(epoch){this.epoch=epoch;this.pending=[];this.inflight=null;this.samples=0;this.ready=false;this.maxSeconds=0;this.sent=0;this.completed=0;this.lastEnd=0;}
  enqueue(pcm,start,final=false){
    if(this.samples+pcm.length>this.limit)throw Error('Лимит сохранённого звука: обработка остановлена без пропуска фрагментов очереди.');
    if(!pcm.length)start=this.lastEnd;
    const item={type:pcm.length?'pcm':'flush',epoch:this.epoch,pcm,start,final,end:start+pcm.length/16000};this.lastEnd=item.end;
    this.pending.push(item);this.samples+=pcm.length;this.maxSeconds=Math.max(this.maxSeconds,this.samples/16000);this.pump();
  }
  accept(message){
    if(message.epoch!==this.epoch)return false;
    if(message.type==='reset'){this.ready=true;this.pump();return true;}
    const item=this.inflight;
    if(message.type!=='result' || !item || Math.abs((message.start??-1)-item.start)>.01 || Math.abs((message.end??-1)-item.end)>.01)return false;
    this.samples-=item.pcm.length;this.inflight=null;this.completed++;this.pump();return true;
  }
  pump(){
    if(!this.ready || this.inflight || !this.pending.length)return;
    this.inflight=this.pending.shift();this.inflight.sentAt=performance.now();this.sent++;this.send(this.inflight);
  }
  stats(){return {pendingPackets:this.pending.length,inflight:this.inflight?1:0,audioSeconds:this.samples/16000,
    maxAudioSeconds:this.maxSeconds,sent:this.sent,completed:this.completed,
    inflightSeconds:this.inflight?(performance.now()-this.inflight.sentAt)/1000:0};}
}
globalThis.PCMQueue=PCMQueue;
