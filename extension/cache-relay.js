const relaySession=new URLSearchParams(location.search).get('session');
const cacheBus=new BroadcastChannel('cache-input:'+relaySession);
let relayAllowed=false;
window.addEventListener('message',event=>{
  const message=event.data;
  if(!relayAllowed || event.source!==parent || event.origin!=='https://www.youtube.com' || message?.sessionId!==relaySession)return;
  if(message.type==='cache-header' || message.type==='cache-data')cacheBus.postMessage(message);
});
chrome.runtime.sendMessage({target:'worker',type:'cache-relay-ready',sessionId:relaySession}).then(result=>{
  if(result?.ok && !result.ignored){relayAllowed=true;return chrome.runtime.sendMessage({target:'worker',type:'cache-resync',sessionId:relaySession});}
}).catch(()=>{});
