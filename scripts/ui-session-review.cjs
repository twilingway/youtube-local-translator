const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..'),out=path.join(root,'reports','ui');
const report={time:new Date().toISOString(),kind:'real-extension-ui-and-explicit-synthetic-session-isolation-not-youtube-capture',screenshots:[],checks:[],events:[],errors:[],limitations:['Regular Chrome profile and user backend capture untouched. No second capture started. Session reset/result/source messages below are explicitly synthetic test messages.']};
(async()=>{
  const context=await chromium.launchPersistentContext(path.join(root,'.cache','ui-session-profile'),{
    executablePath:path.join(root,'.cache','chrome-for-testing','chrome-win64','chrome.exe'),headless:false,chromiumSandbox:true,
    viewport:{width:1120,height:850},deviceScaleFactor:1,
    ignoreDefaultArgs:['--disable-extensions','--unsafely-disable-devtools-self-xss-warnings','--enable-unsafe-swiftshader'],
    args:[`--disable-extensions-except=${path.join(root,'extension')}`,`--load-extension=${path.join(root,'extension')}`]
  });
  context.on('close',()=>report.events.push({event:'context-close',time:new Date().toISOString()}));
  context.setDefaultTimeout(5000);
  context.browser()?.on('disconnected',()=>report.events.push({event:'browser-disconnected',time:new Date().toISOString()}));
  const monitor=p=>{p.on('close',()=>report.events.push({event:'page-close',url:p.url(),time:new Date().toISOString()}));p.on('crash',()=>report.events.push({event:'page-crash',url:p.url(),time:new Date().toISOString()}));p.on('pageerror',e=>report.errors.push({url:p.url(),error:e.message}));};
  try{
    report.browser=context.browser()?.version();
    let worker=context.serviceWorkers()[0];if(!worker)worker=await context.waitForEvent('serviceworker',{timeout:15000});
    report.extensionId=worker.url().split('/')[2];
    const base=`chrome-extension://${report.extensionId}`;
    const a=await context.newPage(),b=await context.newPage();monitor(a);monitor(b);
    await a.goto(base+'/player.html?session=ui-session-A');await b.goto(base+'/player.html?session=ui-session-B');
    const diag=p=>p.evaluate(()=>globalThis.translatorDiagnostics());
    async function shot(p,name){const file=path.join(out,name+'.png');await p.screenshot({path:file,timeout:10000});const zoom=await worker.evaluate(async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url===url);return t?await chrome.tabs.getZoom(t.id):null;},p.url());report.screenshots.push({path:file,bytes:fs.statSync(file).size,url:p.url(),viewport:p.viewportSize(),zoom,viewed:false,scroll:await p.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}))});}
    report.checks.push({name:'idle timeline disabled',pass:await a.locator('#timeline').isDisabled()});
    await shot(a,'player-new-idle-1120');
    await a.locator('#play').click();
    await a.locator('#original').fill('0.3');await a.locator('#dub').fill('0.7');
    await a.locator('#cleanVideo').uncheck();await a.locator('#cleanVideo').check();
    report.checks.push({name:'volume and clean checkbox controls',diagnostics:await diag(a),cleanChecked:await a.locator('#cleanVideo').isChecked()});
    await a.evaluate(()=>{globalThis.testSender=new BroadcastChannel('translator:ui-session-A');testSender.postMessage({type:'reset',epoch:'synthetic-epoch-A',settings:{mode:'both',voice:'male',delay:20},mime:'video/webm;codecs=vp8,opus'});});
    await a.waitForFunction(()=>translatorDiagnostics().epoch==='synthetic-epoch-A');
    await a.evaluate(()=>{testSender.postMessage({type:'result',epoch:'synthetic-epoch-A',end:10,cues:[{start:0,end:10,text:'Тест изоляции сессий: субтитры только в A'}]});testSender.postMessage({type:'source',time:40,captureTime:0,duration:125});});
    await a.locator('#subtitle').getByText('Тест изоляции сессий: субтитры только в A').waitFor();
    const da=await diag(a),db=await diag(b);
    report.checks.push({name:'synthetic reset/result/source isolated between different session IDs',pass:da.epoch==='synthetic-epoch-A'&&da.metrics.resets===1&&da.metrics.results===1&&db.epoch===null&&db.metrics.resets===0&&db.metrics.results===0,playerA:da,playerB:db,subtitleB:await b.locator('#subtitle').textContent(),timelineAEnabled:await a.locator('#timeline').isEnabled(),timelineBDisabled:await b.locator('#timeline').isDisabled()});
    await shot(a,'player-new-subtitle-1120');await shot(b,'player-new-isolated-B');
    await a.locator('#subtitles').uncheck();
    report.checks.push({name:'subtitle checkbox hides cue',pass:await a.locator('#subtitle').textContent()===''});
    await a.locator('h1').click();await a.keyboard.press('c');
    await a.waitForFunction(()=>document.querySelector('#subtitle').textContent.includes('Тест изоляции'));
    report.checks.push({name:'C shortcut restores subtitle',pass:await a.locator('#subtitles').isChecked()});
    await a.setViewportSize({width:1000,height:800});await shot(a,'player-new-subtitle-1000');
    await a.bringToFront();
    try{
      await a.locator('#fullscreen').click();
      await a.waitForFunction(()=>document.fullscreenElement?.id==='stage',null,{timeout:3000});
      report.checks.push({name:'fullscreen enters stage',pass:await a.evaluate(()=>document.fullscreenElement?.id==='stage')});
      await shot(a,'player-new-fullscreen');await a.evaluate(()=>document.exitFullscreen());await a.waitForFunction(()=>!document.fullscreenElement,null,{timeout:3000});
    }catch(e){report.checks.push({name:'fullscreen enters stage',pass:false,error:e.message});}
    await a.locator('#timeline').fill('70');await a.locator('#timeline').dispatchEvent('change');
    report.checks.push({name:'synthetic source timeline seek invalidates own epoch',pass:(await diag(a)).epoch===null,status:await a.locator('#status').textContent(),otherEpoch:(await diag(b)).epoch});
    const guard=await b.evaluate(async()=>{await chrome.storage.session.set({activeSession:'ui-session-A'});const stop=await chrome.runtime.sendMessage({target:'worker',type:'stop',sessionId:'ui-session-B'});const seek=await chrome.runtime.sendMessage({target:'worker',type:'seek',sessionId:'ui-session-B',time:12});const active=await chrome.storage.session.get('activeSession');await chrome.storage.session.remove('activeSession');return{stop,seek,active};});
    report.checks.push({name:'worker ignores foreign session stop and seek (test profile metadata only)',pass:guard.stop.ignored===true&&guard.seek.ignored===true&&guard.active.activeSession==='ui-session-A',details:guard});
    const yt=await context.newPage();await yt.bringToFront();monitor(yt);const requests=[];yt.on('requestfailed',r=>requests.push({url:r.url(),failure:r.failure()?.errorText}));
    report.events.push({event:'youtube-navigation-start',time:new Date().toISOString()});
    try{
      await yt.goto('https://www.youtube.com/watch?v=jNQXAC9IVRw',{waitUntil:'domcontentloaded',timeout:30000});
      await yt.locator('#movie_player').waitFor({timeout:15000});
      report.youtube={url:yt.url(),title:await yt.title(),moviePlayerFound:true,body:(await yt.locator('body').innerText()).slice(0,5000)};
      await shot(yt,'youtube-real-before-clean');
      const tab=await worker.evaluate(async url=>(await chrome.tabs.query({})).find(t=>t.url===url)?.id,yt.url());
      const inject=await worker.evaluate(async tabId=>{await chrome.scripting.executeScript({target:{tabId},files:['source.js']});await chrome.tabs.sendMessage(tabId,{type:'clean-video',enabled:true});return true;},tab);
      report.youtube.cleanInjected=inject;await yt.waitForFunction(()=>document.documentElement.classList.contains('local-translator-clean'));
      report.youtube.cleanGeometry=await yt.locator('#movie_player').boundingBox();
      await shot(yt,'youtube-real-clean');
    }catch(e){report.youtube={...(report.youtube||{}),url:yt.isClosed()?'closed':yt.url(),error:e.message,contextPages:context.pages().length,requests};if(!yt.isClosed())await shot(yt,'youtube-retry-result').catch(err=>report.errors.push({step:'youtube screenshot',error:err.message}));}
    report.events.push({event:'youtube-navigation-finish',time:new Date().toISOString()});
  }catch(e){report.error=e.stack;process.exitCode=1;}
  finally{report.events.push({event:'intentional-context-close',time:new Date().toISOString()});await context.close();fs.writeFileSync(path.join(out,'session-ui-review.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({report:path.join(out,'session-ui-review.json'),screenshots:report.screenshots.map(x=>({path:x.path,bytes:x.bytes})),checks:report.checks.map(x=>({name:x.name,pass:x.pass})),youtube:report.youtube,error:report.error}));}
})().catch(e=>{console.error(e);process.exitCode=1;});
