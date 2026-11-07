const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={performance};vm.runInNewContext(fs.readFileSync(process.env.TRANSLATOR_PCM_QUEUE_JS||'extension/pcm-queue.js','utf8'),context);
const Queue=context.PCMQueue,pcm=seconds=>new Int16Array(seconds*16000),ack=item=>({type:'result',epoch:item.epoch,start:item.start,end:item.end});
test('100 seconds arriving as a burst never put more than one item into service and lose no packets',()=>{
  const sent=[],q=new Queue(item=>sent.push(item));q.reset('one');
  for(let i=0;i<20;i++)q.enqueue(pcm(5),i*5,true);
  assert.equal(sent.length,0);q.accept({type:'reset',epoch:'one'});assert.equal(sent.length,1);
  for(let i=0;i<20;i++){assert.equal(sent.length,i+1);assert.equal(sent[i].start,i*5);assert.equal(q.stats().inflight,1);q.accept(ack(sent[i]));}
  assert.equal(q.stats().audioSeconds,0);assert.equal(q.stats().pendingPackets,0);assert.equal(q.stats().completed,20);assert.equal(q.stats().maxAudioSeconds,100);
});
test('seek invalidates pending PCM; stale and duplicate results never unlock a new packet',()=>{
  const sent=[],q=new Queue(item=>sent.push(item));q.reset('old');q.accept({type:'reset',epoch:'old'});q.enqueue(pcm(5),0);
  const old=sent[0];q.reset('new');q.enqueue(pcm(5),0);q.enqueue(pcm(5),5);
  assert.equal(q.accept(ack(old)),false);assert.equal(sent.length,1);
  q.accept({type:'reset',epoch:'new'});const fresh=sent[1];q.accept(ack(fresh));assert.equal(sent.length,3);
  assert.equal(q.accept(ack(fresh)),false);assert.equal(q.stats().pendingPackets,0);assert.equal(q.stats().inflight,1);
});
test('empty final flush stays behind its audio and uses the last end timestamp',()=>{
  const sent=[],q=new Queue(item=>sent.push(item));q.reset('x');q.accept({type:'reset',epoch:'x'});q.enqueue(pcm(5),.1);q.enqueue(new Int16Array(),0,true);
  assert.equal(sent.length,1);q.accept(ack(sent[0]));assert.equal(sent[1].type,'flush');assert.equal(sent[1].start,5.1);q.accept(ack(sent[1]));assert.equal(q.stats().inflight,0);
});
test('queue memory is bounded and a packet is explicitly rejected rather than silently omitted',()=>{
  const q=new Queue(()=>{},10);q.reset('x');q.enqueue(pcm(8),0);assert.throws(()=>q.enqueue(pcm(3),8),/Лимит/);assert.equal(q.stats().audioSeconds,8);
});
