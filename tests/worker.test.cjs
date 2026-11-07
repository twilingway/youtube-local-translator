const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const prefix='chrome-extension://test/player.html';
const workerCode=fs.readFileSync(process.env.TRANSLATOR_WORKER_JS||'extension/worker.js','utf8');
const manifestVersion=JSON.parse(fs.readFileSync(path.join(path.dirname(process.env.TRANSLATOR_WORKER_JS||'extension/worker.js'),'manifest.json'),'utf8')).version;
function harness({active=false,state={},tabs=[],sourceProbe={build:manifestVersion,available:true,init:true},sourceState={ownView:false,hasVideo:true,paused:false,ended:false,readyState:4,muted:false,volume:1}}={}){
  const calls=[],listeners={},store={...state};let offscreen=active;
  const runtime={getURL:path=>'chrome-extension://test/'+path,getManifest:()=>({version:manifestVersion}),
    onMessage:{addListener:f=>listeners.message=f},getContexts:async()=>offscreen?[{}]:[],
    sendMessage:async m=>{calls.push(['message',m]);return {ok:true};}};
  const chrome={runtime,storage:{session:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,store[k]])),
    set:async value=>Object.assign(store,value),remove:async keys=>{for(const key of keys)delete store[key];}}},
    tabs:{query:async()=>tabs,get:async id=>{const tab=tabs.find(t=>t.id===id);if(!tab)throw Error('missing');return tab;},
      create:async options=>{const tab={id:100,windowId:1,...options};tabs.push(tab);calls.push(['tab-create',options]);return tab;},
      update:async(id,value)=>{calls.push(['tab-update',id,value]);const tab=tabs.find(t=>t.id===id);if(tab)Object.assign(tab,value);return tab;},remove:async ids=>calls.push(['remove',ids]),
      sendMessage:async(id,m)=>calls.push(['source-message',id,m]),onRemoved:{addListener:f=>listeners.removed=f}},
    windows:{update:async(id,value)=>calls.push(['focus',id,value]),create:async options=>{calls.push(['create',options]);return {tabs:[{id:99}]};}},
    offscreen:{createDocument:async()=>{offscreen=true;calls.push(['offscreen-create']);},closeDocument:async()=>{offscreen=false;calls.push(['offscreen-close']);}},action:{setBadgeText:async options=>calls.push(['badge',options])},
    tabCapture:{getMediaStreamId:async options=>{calls.push(['capture-id',options]);return 'stream';}},scripting:{executeScript:async options=>{calls.push(['execute-script',options]);return String(options.func).includes('__localTranslatorMediaTap?.info')?[{result:sourceProbe}]:options.world==='MAIN'?[{result:{method:'youtube-player'}}]:options.func?[{result:sourceState}]:[];}}};
  vm.runInNewContext(workerCode,{chrome,URL,crypto:{randomUUID:()=> 'new-session'},fetch:async()=>({json:async()=>({ready:true})})});
  return {calls,store,send:(msg,sender={})=>new Promise(resolve=>listeners.message({target:'worker',...msg},sender,resolve))};
}
test('repeated start focuses current player and creates no window or capture',async()=>{
  const h=harness({active:true,state:{activeSession:'one',playerTab:7},tabs:[{id:7,windowId:3,url:prefix+'?session=one'}]});
  const result=await h.send({type:'start',tabId:4});assert.equal(result.existing,true);
  assert.ok(h.calls.some(c=>c[0]==='focus'));assert.ok(!h.calls.some(c=>['create','offscreen-create','offscreen-close'].includes(c[0])));
});
test('stale MAIN capture hook requires refreshing YouTube before opening a new capture or player',async()=>{
  const h=harness({tabs:[{id:4,windowId:1,url:'https://www.youtube.com/watch?v=test'}],sourceProbe:{build:'outdated',available:true,init:true}});
  const result=await h.send({type:'start',tabId:4,videoMode:'ram',playerMode:'tab',mode:'voice',voice:'male',delay:60});
  assert.match(result.error,/старый обработчик/);
  assert.ok(!h.calls.some(c=>['offscreen-create','capture-id','tab-create','create'].includes(c[0])));
});
test('old window cannot stop or seek newer session',async()=>{
  const h=harness({active:true,state:{activeSession:'new',sourceTab:4,playerTab:7}});
  assert.equal((await h.send({type:'stop',sessionId:'old'})).ignored,true);
  assert.equal((await h.send({type:'seek',sessionId:'old',time:100})).ignored,true);
  assert.equal(h.calls.length,0);assert.equal(h.store.activeSession,'new');
});

test('changed popup mode reconfigures existing capture instead of ignoring the choice',async()=>{
  const h=harness({active:true,state:{activeSession:'one',playerTab:7,activeOptions:{mode:'both',voice:'male',speakers:true}},tabs:[{id:7,windowId:3,url:prefix+'?session=one'}]});
  const result=await h.send({type:'start',tabId:4,mode:'voice',voice:'male',speakers:true});
  assert.equal(result.existing,true);
  const update=h.calls.find(c=>c[0]==='message'&&c[1].type==='configure')[1];
  assert.equal(update.mode,'voice');assert.equal(update.sessionId,'one');
  assert.ok(!h.calls.some(c=>['create','offscreen-create','offscreen-close'].includes(c[0])));
  assert.equal(h.store.activeOptions.mode,'voice');
});
test('new session closes only old project players and preserves foreign tabs',async()=>{
  const h=harness({state:{playerTab:7},tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'},
    {id:7,url:prefix+'?session=old'},{id:8,url:'https://example.com'}, {id:9,url:'about:blank'}]});
  assert.equal((await h.send({type:'start',tabId:4,mode:'both',voice:'male',delay:20})).ok,true);
  const removed=h.calls.find(c=>c[0]==='remove')[1];assert.deepEqual(Array.from(removed),[7]);
  assert.equal(h.store.playerTab,99);assert.equal(h.store.activeSession,'new-session');
});
test('stop closes owned player and restores source',async()=>{
  const h=harness({active:true,state:{activeSession:'one',sourceTab:4,playerTab:7},tabs:[{id:7,url:prefix+'?session=one'}]});
  await h.send({type:'stop',sessionId:'one'});
  assert.ok(h.calls.some(c=>c[0]==='remove' && c[1]===7));
  assert.ok(h.calls.some(c=>c[0]==='source-message' && c[2].type==='clean-video' && c[2].enabled===false));
  assert.equal(h.store.activeSession,undefined);
});
if(workerCode.includes('view-config')){
  test('explicit sample capture uses original tab without creating a translated player',async()=>{
    const h=harness({tabs:[{id:4,title:'test',url:'https://www.youtube.com/watch?v=test'}]});
    assert.equal((await h.send({type:'sample-start',tabId:4})).ok,true);
    assert.equal(h.calls.find(c=>c[0]==='capture-id')[1].targetTabId,4);
    assert.ok(h.calls.some(c=>c[0]==='message'&&c[1].target==='sample-capture'));
    assert.ok(!h.calls.some(c=>c[0]==='create'||c[0]==='tab-create'||c[0]==='message'&&c[1].target==='capture'));
  });
  test('native seek calls MAIN only for current owned native view',async()=>{
    const h=harness({state:{activeSession:'one',playerTab:100,videoMode:'native'}});
    assert.equal((await h.send({type:'native-seek',sessionId:'one',time:123},{tab:{id:4}})).ignored,true);
    assert.equal((await h.send({type:'native-seek',sessionId:'old',time:123},{tab:{id:100}})).ignored,true);
    assert.equal(h.calls.length,0);
    assert.equal((await h.send({type:'native-seek',sessionId:'one',time:123},{tab:{id:100}})).method,'youtube-player');
    const script=h.calls.find(c=>c[0]==='execute-script')[1];assert.equal(script.world,'MAIN');assert.equal(script.target.tabId,100);assert.equal(script.args[0],123);
  });
  test('native mode is audio-only selection, scoped to owned YouTube view',async()=>{
    const h=harness({tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'}],sourceState:{hasVideo:true,paused:false,readyState:4,muted:false,volume:1,time:135}});
    const result=await h.send({type:'start',tabId:4,playerMode:'youtube',videoMode:'native',mode:'both',delay:30});
    assert.equal(result.ok,true);assert.equal(h.store.videoMode,'native');
    const message=h.calls.find(c=>c[0]==='message'&&c[1].target==='capture'&&c[1].type==='start')[1];
    assert.equal(message.videoMode,'native');assert.equal(message.sourceStart,135);
    assert.equal((await h.send({type:'view-config'},{tab:{id:100}})).videoMode,'native');
    assert.equal((await h.send({type:'view-config'},{tab:{id:4}})).videoMode,undefined);
  });
  test('native mode cannot open a standalone window with no original video',async()=>{
    const h=harness({tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'}]});
    assert.ok((await h.send({type:'start',tabId:4,playerMode:'window',videoMode:'native'})).error);
    assert.ok(!h.calls.some(c=>c[0]==='capture-id'||c[0]==='offscreen-create'));
  });
  test('never recaptures translated view or silently captures a paused source',async()=>{
    for(const sourceState of [{ownView:true},{hasVideo:true,paused:true},{hasVideo:true,ended:true},{hasVideo:true,readyState:4,muted:true}]){
      const h=harness({tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'}],sourceState});
      const result=await h.send({type:'start',tabId:4,playerMode:'youtube'});
      assert.ok(result.error);assert.ok(!h.calls.some(c=>c[0]==='capture-id' || c[0]==='offscreen-create'));
    }
  });
  test('YouTube mode captures original tab and only embeds in owned view',async()=>{
    const h=harness({tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'}]});
    const result=await h.send({type:'start',tabId:4,playerMode:'youtube',mode:'both',voice:'male',delay:30});
    assert.equal(result.ok,true);assert.equal(h.store.sourceTab,4);assert.equal(h.store.playerTab,100);
    assert.equal(h.calls.find(c=>c[0]==='capture-id')[1].targetTabId,4);
    assert.ok(!h.calls.some(c=>c[0]==='create'));
    assert.equal((await h.send({type:'view-config'},{tab:{id:4}})).sessionId,undefined);
    assert.equal((await h.send({type:'view-config'},{tab:{id:100}})).sessionId,'new-session');
    await h.send({type:'player-ready',sessionId:'new-session'});
    assert.ok(h.calls.some(c=>c[0]==='message' && c[1].type==='ui-ready'));
  });
  test('stopping YouTube view never closes original source',async()=>{
    const h=harness({active:true,state:{activeSession:'one',sourceTab:4,playerTab:100,playerMode:'youtube',playerVideoId:'test'},
      tabs:[{id:4,url:'https://www.youtube.com/watch?v=test'},{id:100,url:'https://www.youtube.com/watch?v=test'}]});
    await h.send({type:'stop',sessionId:'one'});
    assert.ok(h.calls.some(c=>c[0]==='remove' && c[1]===100));
    assert.ok(!h.calls.some(c=>c[0]==='remove' && c[1]===4));
  });
}
