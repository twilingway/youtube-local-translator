// MAIN-world source selection, with explicitly synthetic media objects.
// Real URL revocation/MSE playback is validated separately in Chrome.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
  let next=0;const sent=[],revoked=[];
  class Buffer{constructor(){this.mode='segments';this.timestampOffset=0;this.appendWindowStart=0;this.appendWindowEnd=Infinity;this.buffered={length:0};}appendBuffer(){}changeType(){}abort(){this.nativeAborts=(this.nativeAborts||0)+1;}}
  class Media{constructor(){this.sourceBuffers=[];this.readyState='open';}addSourceBuffer(){const b=new Buffer();this.sourceBuffers.push(b);return b;}}
  const video={src:'',currentSrc:'',currentTime:0,readyState:4,buffered:{length:0}};
  const main={...video},frame={src:'chrome-extension://test/cache-relay.html',isConnected:true,contentWindow:{postMessage:m=>sent.push(m)}};
  const URLClass=class extends URL{static createObjectURL(){return 'blob:fixture/'+(++next);}static revokeObjectURL(url){revoked.push(url);}};
  const ctx={MediaSource:Media,SourceBuffer:Buffer,URL:URLClass,document:{querySelector:s=>s.startsWith('#movie_player')?main:video,getElementById:()=>frame}};
  vm.runInNewContext(fs.readFileSync(process.env.TRANSLATOR_MEDIA_TAP_JS||'extension/media-tap.js','utf8'),ctx);
  function media(time){const ms=new ctx.MediaSource(),url=ctx.URL.createObjectURL(ms),b=ms.addSourceBuffer('video/mp4');b.timestampOffset=time;
    b.appendBuffer(new Uint8Array([0,0,0,8,102,116,121,112]));return {ms,url,b};}
  return {ctx,main,video,sent,revoked,media,tap:ctx.__localTranslatorMediaTap};
}
test('revoking an attached source URL never switches capture to a later preload',()=>{
  const h=harness(),a=h.media(0);h.main.src=h.main.currentSrc=a.url;h.ctx.URL.revokeObjectURL(a.url);
  const b=h.media(120);const info=h.tap.info();assert.equal(info.tracks[0].id,'1');assert.equal(info.sourceMeta.binding,'video-url');
  assert.deepEqual(h.revoked,[a.url]);h.tap.start('session','generation','relay');
  assert.equal(h.sent[0].type,'cache-header');assert.equal(h.sent[0].tracks[0].id,'1');
  assert.ok(h.sent.filter(m=>m.op==='append').every(m=>m.timestampOffset===0));
});
test('unknown video URL fails explicitly instead of capturing the newest source',()=>{
  const h=harness();h.media(120);h.main.src=h.main.currentSrc='blob:untracked';
  assert.equal(h.tap.info().available,false);assert.equal(h.tap.info().sourceMeta.binding,'unbound');
  assert.ok(h.tap.start('session','generation','relay').error);assert.equal(h.sent.length,0);
});
test('main YouTube video wins over a different first video element',()=>{
  const h=harness(),preview=h.media(120),active=h.media(0);h.video.src=h.video.currentSrc=preview.url;h.main.src=h.main.currentSrc=active.url;
  assert.equal(h.tap.info().tracks[0].id,'2');
});
test('captured append mode is included without changing the source mode',()=>{
  const h=harness(),a=h.media(0);h.main.src=h.main.currentSrc=a.url;a.b.mode='sequence';a.b.appendBuffer(new Uint8Array([1,2,3]));
  h.tap.start('session','generation','relay');const append=h.sent.filter(m=>m.op==='append').at(-1);
  assert.equal(append.mode,'sequence');assert.equal(a.b.mode,'sequence');
});
test('MAIN capture build agrees with the extension manifest',()=>{
  const h=harness(),file=process.env.TRANSLATOR_MEDIA_TAP_JS||'extension/media-tap.js';
  const manifest=JSON.parse(fs.readFileSync(path.join(path.dirname(file),'manifest.json'),'utf8'));
  assert.equal(h.tap.info().build,manifest.version);
});
test('cross-realm ArrayBuffer is copied at its full native byte length',()=>{
  const h=harness(),a=h.media(0);h.main.src=h.main.currentSrc=a.url;
  const foreign=vm.runInNewContext('new Uint8Array([0,0,0,8,102,116,121,112]).buffer');
  a.b.appendBuffer(foreign);h.tap.start('session','generation','relay');
  assert.equal(h.sent.filter(m=>m.op==='append').at(-1).data.byteLength,8);
  const stats=h.tap.info().sourceMeta.tracks[0];assert.equal(stats.inputBytes,stats.copiedBytes);assert.equal(stats.copyErrors,0);assert.ok(stats.foreignBuffers>=1);
});
test('native parser abort is captured in order before subsequent media data',()=>{
  const h=harness(),a=h.media(0);h.main.src=h.main.currentSrc=a.url;
  a.b.abort();a.b.appendBuffer(new Uint8Array([1,2,3]));h.tap.start('session','generation','relay');
  assert.equal(a.b.nativeAborts,1);assert.equal(h.tap.info().sourceMeta.tracks[0].aborts,1);
  assert.deepEqual(h.sent.filter(m=>m.op).map(m=>m.op),['track','append','abort','append']);
});
