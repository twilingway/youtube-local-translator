// Isolated API contract tests, not a real tabCapture/YouTube verification.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(){
  const calls={constraints:null,recorders:[],messages:[],sent:[],nodes:[]};let listener,socket;
  const track={stop(){},getSettings:()=>({width:1920,height:1080,frameRate:60})};
  class Socket{static OPEN=1;constructor(){socket=this;this.readyState=1;this.bufferedAmount=0;queueMicrotask(()=>this.onopen());}send(raw){const m=JSON.parse(raw);calls.sent.push(m);if(m.type==='auth')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'ready'})}));}close(){}}
  class Context{constructor(){this.currentTime=0;this.state='running';this.audioWorklet={addModule:async()=>{}};}createMediaStreamSource(){return{connect(){}};}createGain(){return{gain:{value:1},connect(){return this;}};}async resume(){}async close(){this.state='closed';}}
  class Recorder{static isTypeSupported(){return true;}constructor(stream,opts){calls.recorders.push(opts);this.state='inactive';}start(){this.state='recording';}stop(){this.state='inactive';}}
  const sandbox={console,crypto:require('node:crypto').webcrypto,WebSocket:Socket,MediaRecorder:Recorder,AudioContext:Context,
    AudioWorkletNode:class{constructor(){this.port={};calls.nodes.push(this);}connect(){return this;}},
    BroadcastChannel:class{postMessage(m){calls.messages.push(m);}},
    navigator:{mediaDevices:{getUserMedia:async constraints=>{calls.constraints=constraints;return{getTracks:()=>[track],getVideoTracks:()=>constraints.video?[track]:[]};}}},
    chrome:{runtime:{onMessage:{addListener:f=>listener=f},sendMessage:async()=>({ok:true})}},
    LOCAL_CONFIG:{token:'explicit-test-token'},setInterval(){},setTimeout(){return 1;},clearTimeout(){},performance:{now:()=>0},Date,Int16Array,Uint8Array,btoa:s=>Buffer.from(s,'binary').toString('base64'),
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(process.env.TRANSLATOR_PCM_QUEUE_JS||'extension/pcm-queue.js','utf8'),sandbox);
  vm.runInContext(fs.readFileSync(process.env.TRANSLATOR_OFFSCREEN_JS||'extension/offscreen.js','utf8'),sandbox);
  return {calls,stats:()=>vm.runInContext('flow.stats()',sandbox),reply:message=>socket.onmessage({data:JSON.stringify(message)}),send:message=>new Promise(resolve=>listener({target:'capture',...message},{},resolve))};
}
test('native mode requests only tab audio and never constructs MediaRecorder',async()=>{
  const h=harness(),r=await h.send({type:'start',sessionId:'test',streamId:'fake-tab-id',videoMode:'native',mode:'both',delay:30});
  assert.equal(r.ok,true);assert.equal(h.calls.constraints.video,false);assert.equal(h.calls.recorders.length,0);
  assert.equal(h.calls.constraints.audio.mandatory.chromeMediaSource,'tab');
  assert.equal(h.calls.messages.find(m=>m.type==='reset').mime,null);
});
test('capture profile controls requested height frame ceiling and bitrate',async()=>{
  const h=harness(),r=await h.send({type:'start',sessionId:'test',streamId:'fake-tab-id',videoMode:'capture',videoHeight:2160,videoFps:60,videoMbps:12,mode:'both',delay:30});
  assert.equal(r.ok,true);assert.equal(h.calls.constraints.video.mandatory.maxHeight,2160);
  assert.equal(h.calls.constraints.video.mandatory.maxFrameRate,60);assert.equal(h.calls.recorders[0].videoBitsPerSecond,12000000);
});

test('changing mode resets the same capture into the requested mode without recapture',async()=>{
  const h=harness();await h.send({type:'start',sessionId:'test',streamId:'fake-tab-id',videoMode:'native',mode:'both',voice:'male',delay:30});
  const first=h.calls.sent.find(m=>m.type==='reset');
  const result=await h.send({type:'configure',sessionId:'test',mode:'voice',voice:'female',speakers:true});
  assert.equal(result.ok,true);
  const resets=h.calls.sent.filter(m=>m.type==='reset');assert.equal(resets.length,2);
  assert.equal(resets[1].mode,'voice');assert.equal(resets[1].voice,'female');assert.notEqual(resets[1].epoch,first.epoch);
  assert.equal(h.calls.recorders.length,0);assert.equal(h.calls.nodes.length,1);
});
test('actual offscreen packetizer holds a 100-second port burst until matching model results arrive',async()=>{
  const h=harness();await h.send({type:'start',sessionId:'test',streamId:'fake',videoMode:'native',mode:'both',delay:30});
  const epoch=h.calls.sent.find(m=>m.type==='reset').epoch;h.reply({type:'reset',epoch});
  for(let i=0;i<1000;i++)h.calls.nodes[0].port.onmessage({data:{time:i*.1,pcm:new Int16Array(1600)}});
  assert.equal(h.calls.sent.filter(m=>m.type==='pcm').length,1);assert.ok(h.stats().audioSeconds>=98);assert.ok(h.stats().pendingPackets>6);
  let done=0;
  while(h.stats().inflight){const m=h.calls.sent.filter(m=>m.type==='pcm')[done++],end=m.start+Buffer.from(m.data,'base64').length/32000;h.reply({type:'result',epoch,start:m.start,end,cues:[]});}
  assert.equal(done,20);assert.equal(h.stats().audioSeconds,0);assert.equal(h.calls.sent.filter(m=>m.type==='reset').length,1);
});
test('speech is retained across a short pause until there are five seconds of ASR context',async()=>{
  const h=harness();await h.send({type:'start',sessionId:'test',streamId:'fake',videoMode:'native',mode:'both',delay:30});
  const epoch=h.calls.sent.find(m=>m.type==='reset').epoch;h.reply({type:'reset',epoch});
  for(let i=0;i<20;i++)h.calls.nodes[0].port.onmessage({data:{time:i*.1,pcm:new Int16Array(1600).fill(i<15?3276:0)}});
  assert.equal(h.calls.sent.filter(m=>m.type==='pcm').length,0);
  for(let i=20;i<50;i++)h.calls.nodes[0].port.onmessage({data:{time:i*.1,pcm:new Int16Array(1600)}});
  const audio=h.calls.sent.filter(m=>m.type==='pcm');assert.equal(audio.length,1);assert.equal(Buffer.from(audio[0].data,'base64').length/32000,5);assert.equal(audio[0].final,true);
});
