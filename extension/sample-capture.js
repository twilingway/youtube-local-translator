chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message.target!=='sample-capture')return;
  (async()=>{
    const stream=await navigator.mediaDevices.getUserMedia({audio:{mandatory:{chromeMediaSource:'tab',chromeMediaSourceId:message.streamId}},video:false});
    const context=new AudioContext();await context.audioWorklet.addModule('pcm-worklet.js');
    const node=new AudioWorkletNode(context,'pcm'),source=context.createMediaStreamSource(stream);
    const socket=new WebSocket('ws://127.0.0.1:8768/sample');
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(Error('Коллектор образцов не ответил')),10000);
      socket.onopen=()=>socket.send(JSON.stringify({type:'auth',token:LOCAL_CONFIG.token,url:message.url,title:message.title,time:message.time}));
      socket.onmessage=e=>{if(JSON.parse(e.data).type==='ready'){clearTimeout(timeout);resolve();}};
      socket.onerror=()=>{clearTimeout(timeout);reject(Error('Не запущен коллектор образцов'));};
    });
    let samples=0,finished=false,lastSecond=-1,timer;
    const finish=async()=>{if(finished)return;finished=true;clearTimeout(timer);if(socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'finish'}));stream.getTracks().forEach(t=>t.stop());await context.close();setTimeout(()=>chrome.runtime.sendMessage({target:'worker',type:'sample-finished'}),300);};
    socket.onclose=()=>{if(!finished)finish();};
    node.port.onmessage=e=>{
      if(finished)return;const pcm=e.data.pcm;if(socket.bufferedAmount>1048576){finish();return;}
      socket.send(pcm.buffer);samples+=pcm.length;
      const second=Math.floor(samples/16000);if(second!==lastSecond){lastSecond=second;chrome.runtime.sendMessage({target:'worker',type:'sample-progress',remaining:Math.max(0,45-second)});}
      if(samples>=45*16000)finish();
    };
    stream.getTracks().forEach(t=>t.onended=()=>finish());source.connect(node);
    const zero=context.createGain();zero.gain.value=0;node.connect(zero).connect(context.destination);
    // Monitor only the captured original source, never a translated player.
    source.connect(context.destination);await context.resume();timer=setTimeout(finish,50000);return {ok:true};
  })().then(reply,error=>reply({error:error.message}));return true;
});
