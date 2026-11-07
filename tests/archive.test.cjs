const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {webcrypto}=require('node:crypto');
const context={crypto:webcrypto};vm.runInNewContext(fs.readFileSync(process.env.TRANSLATOR_ARCHIVE_JS||'extension/archive.js','utf8'),context);
const Archive=context.CaptureArchive,bytes=()=>new Uint8Array([1,2,3,4]).buffer;
test('archive retains and verifies real byte checksums in order',async()=>{
  const a=new Archive();await a.add(bytes(),0,1);await a.add(bytes(),1,2);
  assert.equal(await a.verify(),true);assert.equal(a.bytes,8);
});
test('archive rejects a missing recorder chunk instead of claiming continuous history',async()=>{
  const a=new Archive();await a.add(bytes(),0,1);await assert.rejects(a.add(bytes(),2,3),/порядок/);
  assert.equal(a.chunks.length,1);
});
test('checksum detects mutation of retained RAM bytes',async()=>{
  const a=new Archive();await a.add(bytes(),0,1);new Uint8Array(a.chunks[0].data)[2]=9;
  await assert.rejects(a.verify(),/Повреждён/);
});
test('removed initialization segment cannot be claimed as replayable archive',async()=>{
  const a=new Archive();await a.add(bytes(),0,1);await a.add(bytes(),1,2);a.prune(1);
  assert.equal(a.bytes,4);await assert.rejects(a.verify(),/Начало/);
});
