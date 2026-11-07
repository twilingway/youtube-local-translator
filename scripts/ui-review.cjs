const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'reports', 'ui');
const report = {time:new Date().toISOString(), browser:'Chrome for Testing 157.0.8103.38', profile:path.join(root,'.cache','ui-chrome-profile'), extensionPath:path.join(root,'extension'), captures:[], interactions:[], console:[], network:[], limitations:['No new capture started: the user has an active backend session in their regular Chrome profile.'], visualVerdict:'pending review'};
const logPage = page => {
  page.on('pageerror',e=>report.console.push({url:page.url(),type:'pageerror',message:e.message}));
  page.on('console',m=>{if(m.type()==='error')report.console.push({url:page.url(),type:'error',message:m.text()});});
  page.on('requestfailed',r=>report.network.push({url:r.url(),failure:r.failure()?.errorText}));
};
(async()=>{
  let context;
  try {
    context = await chromium.launchPersistentContext(report.profile, {
      executablePath:path.join(root,'.cache','chrome-for-testing','chrome-win64','chrome.exe'),
      headless:false, chromiumSandbox:true, viewport:{width:1120,height:850}, deviceScaleFactor:1,
      ignoreDefaultArgs:['--disable-extensions','--unsafely-disable-devtools-self-xss-warnings','--enable-unsafe-swiftshader'],
      args:[`--disable-extensions-except=${report.extensionPath}`,`--load-extension=${report.extensionPath}`],
    });
    report.actualVersion = context.browser()?.version();
    let worker=context.serviceWorkers()[0];
    if(!worker)worker=await context.waitForEvent('serviceworker',{timeout:20000});
    report.extensionId=worker.url().split('/')[2];
    async function shot(page,name) {
      const file=path.join(out,name+'.png');
      await page.screenshot({path:file});
      const tab=await worker.evaluate(async url=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url===url);return tab?{id:tab.id,zoom:await chrome.tabs.getZoom(tab.id)}:null;},page.url());
      report.captures.push({path:file,bytes:fs.statSync(file).size,url:page.url(),viewport:page.viewportSize(),zoom:tab?.zoom,viewed:false,dimensions:await page.evaluate(()=>({innerWidth,innerHeight,devicePixelRatio,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight}))});
    }
    const popup=await context.newPage();logPage(popup);
    await popup.setViewportSize({width:378,height:460});
    await popup.goto(`chrome-extension://${report.extensionId}/popup.html`);
    await shot(popup,'popup-default');
    await popup.locator('#mode').selectOption('subtitles');
    await popup.locator('#voice').selectOption('female');
    await popup.locator('#delay').fill('60');
    report.interactions.push({page:'popup',action:'Changed real mode, voice and buffer controls',values:await popup.locator('body').evaluate(()=>({mode:document.querySelector('#mode').value,voice:document.querySelector('#voice').value,delay:document.querySelector('#delay').value}))});
    await shot(popup,'popup-controls');
    const player=await context.newPage();logPage(player);
    await player.goto(`chrome-extension://${report.extensionId}/player.html`);
    await player.locator('#play').click();
    await player.locator('#original').fill('0.35');
    await player.locator('#dub').fill('0.65');
    report.interactions.push({page:'player',action:'Clicked continue and adjusted original/dub volume controls; idle session only',diagnostics:await player.evaluate(()=>globalThis.translatorDiagnostics())});
    await shot(player,'player-idle');
    await player.locator('#pause').click();
    report.interactions.push({page:'player',action:'Clicked pause on idle player'});
    const yt=await context.newPage();logPage(yt);
    try {
      await yt.goto('https://www.youtube.com/watch?v=jNQXAC9IVRw',{waitUntil:'domcontentloaded',timeout:45000});
      await yt.locator('h1').first().waitFor({timeout:20000}).catch(()=>{});
      report.youtube={title:await yt.title(),url:yt.url(),bodyText:(await yt.locator('body').innerText()).slice(0,7000),video:await yt.locator('video').evaluateAll(vs=>vs.map(v=>({currentTime:v.currentTime,duration:Number.isFinite(v.duration)?v.duration:null,paused:v.paused,readyState:v.readyState,error:v.error?.message}))) };
    }catch(e){report.youtube={url:yt.url(),error:e.message};}
    await shot(yt,'youtube-availability');
  }catch(e){report.error=e.stack;process.exitCode=1;}
  finally {
    if(context)await context.close();
    fs.writeFileSync(path.join(out,'playwright-review.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({report:path.join(out,'playwright-review.json'),error:report.error,captures:report.captures.map(({path,bytes,viewport,zoom})=>({path,bytes,viewport,zoom})),youtube:report.youtube?.title||report.youtube?.error}));
  }
})();
