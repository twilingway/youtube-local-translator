const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
(async()=>{
  const context=await chromium.launchPersistentContext(path.join(root,'.cache','mse-repro-profile'),{
    executablePath:path.join(root,'.cache','chrome-for-testing','chrome-win64','chrome.exe'),headless:false,chromiumSandbox:true,
    viewport:{width:1120,height:850},deviceScaleFactor:1,
    ignoreDefaultArgs:['--unsafely-disable-devtools-self-xss-warnings','--enable-unsafe-swiftshader']
  });
  try {
    const page=await context.newPage();
    await page.setContent('<button>Запустить синтетический тест</button>');
    await page.getByRole('button').click();
    const result=await page.evaluate(async()=>{
      document.body.innerHTML='<h1>Синтетический тест MediaRecorder → MediaSource</h1><p>Две эпохи одного canvas+oscillator stream; это не YouTube.</p><canvas width="640" height="360"></canvas><video muted autoplay playsinline controls width="640"></video>';
      const delay=ms=>new Promise(r=>setTimeout(r,ms));
      const canvas=document.querySelector('canvas'), ctx=canvas.getContext('2d'),video=document.querySelector('video');
      const start=performance.now();
      const timer=setInterval(()=>{ctx.fillStyle='#12223b';ctx.fillRect(0,0,640,360);ctx.fillStyle='#fff';ctx.font='32px sans-serif';ctx.fillText(((performance.now()-start)/1000).toFixed(1)+' sec real stream',40,180);},50);
      const ac=new AudioContext();await Promise.race([ac.resume(),delay(5000).then(()=>{throw new Error('AudioContext activation timeout');})]);const destination=ac.createMediaStreamDestination(),osc=ac.createOscillator();osc.frequency.value=440;osc.connect(destination);osc.start();
      const stream=canvas.captureStream(20);stream.addTrack(destination.stream.getAudioTracks()[0]);
      const mime='video/webm;codecs=vp8,opus';
      const results=[];
      for(let epoch=1;epoch<=2;epoch++){
        video.pause();video.removeAttribute('src');video.load();
        const ms=new MediaSource(),url=URL.createObjectURL(ms);video.src=url;
        await Promise.race([new Promise(r=>ms.addEventListener('sourceopen',r,{once:true})),delay(5000).then(()=>{throw new Error('MediaSource sourceopen timeout');})]);
        const buffer=ms.addSourceBuffer(mime);buffer.mode='segments';
        const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:2500000,audioBitsPerSecond:96000});
        const observations=[],chunks=[];let chain=Promise.resolve();
        function ranges(){return Array.from({length:video.buffered.length},(_,i)=>[video.buffered.start(i),video.buffered.end(i)]);}
        recorder.ondataavailable=e=>{if(!e.data.size)return;chunks.push(e.data.size);chain=chain.then(async()=>{const bytes=await e.data.arrayBuffer();await new Promise((resolve,reject)=>{buffer.addEventListener('updateend',resolve,{once:true});buffer.addEventListener('error',reject,{once:true});buffer.appendBuffer(bytes);});video.play().catch(()=>{});observations.push({elapsed:(performance.now()-start)/1000,chunkBytes:e.data.size,buffered:ranges(),position:video.currentTime,paused:video.paused,readyState:video.readyState,timestampOffset:buffer.timestampOffset});});};
        recorder.start(1000);await delay(4500);await new Promise(r=>{recorder.addEventListener('stop',r,{once:true});recorder.stop();});await chain;
        await delay(1200);
        results.push({epoch,streamElapsed:(performance.now()-start)/1000,chunks,observations,final:{buffered:ranges(),position:video.currentTime,paused:video.paused,readyState:video.readyState,error:video.error?.message}});
        video.pause();URL.revokeObjectURL(url);await delay(3000);
      }
      clearInterval(timer);stream.getTracks().forEach(t=>t.stop());osc.stop();await ac.close();
      return {kind:'synthetic-browser-repro-not-youtube',mime,results};
    });
    result.browser=context.browser()?.version();result.time=new Date().toISOString();
    const file=path.join(root,'reports','ui','mse-reset-repro.json');fs.writeFileSync(file,JSON.stringify(result,null,2));
    await page.screenshot({path:path.join(root,'reports','ui','mse-reset-repro.png')});
    console.log(JSON.stringify({report:file,result}));
  }finally{await context.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
