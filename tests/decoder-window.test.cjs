// Decoder scheduling contracts; real MSE/video evidence is a separate browser check.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ranges=(a,b)=>({length:1,start:()=>a,end:()=>b});
function load(){
  let now=0;const c={performance:{now:()=>now},captureTime:x=>x,sourceTime:x=>x,setInterval(){},console};
  vm.runInNewContext(fs.readFileSync(process.env.TRANSLATOR_ENCODED_JS||'extension/encoded-media.js','utf8'),c);
  vm.runInNewContext(fs.readFileSync(process.env.TRANSLATOR_CACHED_JS||'extension/cached-video.js','utf8'),c);
  return {c,time:t=>now=t};
}
test('pending target keeps early frames when native video temporarily reports a future position',()=>{
  const {c}=load(),removed=[];
  const buffer={updating:false,buffered:ranges(0,35),remove:(a,b)=>removed.push([a,b])};
  const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{opened:true,source:{readyState:'open'},video:{raw:{currentTime:120},pendingSourceTime:.061842},buffers:new Map([['video',buffer]]),queues:new Map([['video',[]]])});
  d.pump();assert.deepEqual(removed,[]);
  d.video.pendingSourceTime=null;d.pump();assert.deepEqual(removed,[[0,112]]);
});
test('small leading gap can resolve a pending frame position without moving to a future segment',()=>{
  const {c}=load(),element={currentTime:0,readyState:1,seeking:false,buffered:ranges(.08,8)};
  const video=c.createCachedVideo(element);video.currentTime=.061842;
  assert.ok(Math.abs(element.currentTime-.081)<.00001);
  element.readyState=4;video.synchronize();assert.equal(video.pendingSourceTime,null);
});
test('a future prefetched range does not block queued fragments for the target at zero',()=>{
  const {c}=load();let appended=0;
  const buffer={mode:'segments',updating:false,timestampOffset:0,appendWindowStart:0,appendWindowEnd:Infinity,buffered:ranges(120,125),
    appendBuffer(){appended++;this.buffered=ranges(0,35);},addEventListener(){}};
  const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{opened:true,source:{readyState:'open'},video:{raw:{currentTime:0},pendingSourceTime:0},buffers:new Map([['video',buffer]]),
    queues:new Map([['video',[{op:'append',data:new Uint8Array([1]).buffer}] ]])});
  d.pump();assert.equal(appended,1);
});
test('pending replay bytes are consumed before attempting any lost-window rebuild',()=>{
  const {c,time}=load();const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{video:{pendingSourceTime:0},buffers:new Map([['video',{buffered:ranges(120,125)}]]),queues:new Map([['video',[{op:'append'}]]]),
    recoveries:0,seek(){assert.fail('Queued data must be processed first');},onError(){assert.fail('Queued data must not fail');}});
  d.checkTarget();time(20000);d.checkTarget();assert.equal(d.recoveries,0);
});
test('lost pending window rebuilds from RAM once then reports a finite error instead of looping',async()=>{
  const {c,time}=load(),errors=[];let rebuilds=0;
  const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{video:{raw:{currentTime:0},pendingSourceTime:.061842},buffers:new Map([['video',{buffered:ranges(119,124)}]]),recoveries:0,
    onError:e=>errors.push(e),seek:async()=>{rebuilds++;}});
  d.checkTarget();time(3001);d.checkTarget();await Promise.resolve();await Promise.resolve();await Promise.resolve();
  time(4000);d.checkTarget();time(7001);d.checkTarget();time(11000);d.checkTarget();
  assert.equal(rebuilds,1);assert.equal(errors.length,1);assert.equal(d.failed,true);
});
test('forward replay fill is not mistaken for loss of earlier frames',()=>{
  const {c,time}=load();const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{video:{pendingSourceTime:1000},buffers:new Map([['video',{buffered:ranges(0,30)}]]),recoveries:0,
    seek(){assert.fail('Forward fill must not restart the decoder');},onError(){assert.fail('Forward fill must not fail on a timer');}});
  d.checkTarget();time(20000);d.checkTarget();assert.equal(d.recoveries,0);
});
test('replay preserves the captured SourceBuffer mode before appending bytes',()=>{
  const {c}=load();let appendedMode;
  const buffer={mode:'segments',updating:false,timestampOffset:0,appendWindowStart:0,appendWindowEnd:Infinity,buffered:{length:0},
    appendBuffer(){appendedMode=this.mode;},addEventListener(){}};
  const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{opened:true,source:{readyState:'open'},video:{raw:{currentTime:0},pendingSourceTime:null},buffers:new Map([['video',buffer]]),
    queues:new Map([['video',[{op:'append',mode:'sequence',data:new Uint8Array([1]).buffer}] ]])});
  d.pump();assert.equal(appendedMode,'sequence');
});
test('changing startup buffer 60 to 30 does not seek before playback or consume cached speech',()=>{
  const source=fs.readFileSync(process.env.TRANSLATOR_PLAYER_JS||'extension/player.js','utf8');
  const start=source.indexOf("$('delay').onchange=()=>{");const end=source.indexOf('\n};',start)+3;
  assert.ok(start>=0&&end>start);
  let moved=0,silenced=0;const delay={value:30};
  const context={$:()=>delay,settings:{delay:60},head:50,readyThrough:45,started:false,targetIncrease:60,
    video:{get currentTime(){return 0;},set currentTime(v){moved++;},buffered:ranges(0,40)},
    cues:[],spoken:new Set(),silence(){silenced++;},status(){},renderPlayButton(){}};
  vm.runInNewContext(source.slice(start,end),context);delay.onchange();
  assert.equal(moved,0);assert.equal(silenced,0);assert.equal(context.settings.delay,30);assert.equal(context.targetIncrease,0);
});
test('native parser reset is not blocked by an ahead-filled window or an active append',()=>{
  for(const updating of [false,true]){
    const {c}=load();let aborted=0;const buffer={updating,buffered:ranges(0,70),abort(){aborted++;}};
    const d=Object.create(c.EncodedMedia.prototype);
    Object.assign(d,{opened:true,source:{readyState:'open'},video:{raw:{currentTime:0},pendingSourceTime:0},buffers:new Map([['video',buffer]]),
      queues:new Map([['video',[{op:'abort'},{op:'append',data:new ArrayBuffer(0)}]]]),removing:new Set()});
    d.pump();assert.equal(aborted,1);assert.equal(d.queues.get('video').length,1);
  }
});
test('parser reset waits for decoder-owned removal to finish',()=>{
  const {c}=load();let aborted=0;const buffer={updating:true,buffered:ranges(0,70),abort(){aborted++;}};
  const d=Object.create(c.EncodedMedia.prototype);
  Object.assign(d,{opened:true,source:{readyState:'open'},video:{raw:{currentTime:0},pendingSourceTime:0},buffers:new Map([['video',buffer]]),
    queues:new Map([['video',[{op:'abort'}]]]),removing:new Set(['video'])});
  d.pump();assert.equal(aborted,0);assert.equal(d.queues.get('video').length,1);
});
test('numeric diagnostics survive a source buffer removed after a decode error',()=>{
  const {c}=load(),buffer={get buffered(){throw Error('removed SourceBuffer');}};
  const d=Object.create(c.EncodedMedia.prototype);Object.assign(d,{video:{raw:{readyState:1},pendingSourceTime:0},buffers:new Map([['video',buffer]]),queues:new Map()});
  assert.equal(d.diagnostics().tracks[0].unavailable,true);
});
