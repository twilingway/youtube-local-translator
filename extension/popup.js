chrome.storage.session.get('lastError').then(({lastError})=>{if(lastError)document.querySelector('#status').textContent=lastError;});
const restoreOptions=chrome.storage.local.get(['translationOptions','qualityMinuteMigration']).then(async({translationOptions,qualityMinuteMigration})=>{
  translationOptions=translationOptions||{};
  if(!qualityMinuteMigration){translationOptions.delay=60;translationOptions.speakerCount=2;await chrome.storage.local.set({translationOptions,qualityMinuteMigration:1});}
  for(const [key,value]of Object.entries(translationOptions||{})){
    const input=document.getElementById(key);if(!input)continue;
    if(input.type==='checkbox')input.checked=value;else input.value=value;
  }
  document.querySelector('#videoMode').dispatchEvent(new Event('change'));
  document.querySelector('#speakers').dispatchEvent(new Event('change'));
});
document.querySelector('#sample').onclick=async()=>{
  const button=document.querySelector('#sample');button.disabled=true;
  try{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});const result=await chrome.runtime.sendMessage({target:'worker',type:'sample-start',tabId:tab.id});if(result?.error)throw Error(result.error);document.querySelector('#status').textContent='Собираем 45 секунд оригинальной речи. Оставьте видео играть; перевод не запускается.';}
  catch(error){document.querySelector('#status').textContent=error.message;button.disabled=false;}
};
document.querySelector('#videoMode').onchange=()=>{
  const mode=document.querySelector('#videoMode').value,player=document.querySelector('#playerMode');
  document.querySelector('#captureSettings').hidden=mode!=='capture';
  const allowed=mode==='ram'?['tab']:mode==='native'?['youtube']:['tab','youtube','window'];
  for(const option of player.options)option.hidden=option.disabled=!allowed.includes(option.value);
  if(!allowed.includes(player.value))player.value=allowed[0];player.disabled=allowed.length===1;
  document.querySelector('#playerHint').textContent=mode==='ram'?'RAM-видео воспроизводится во вкладке нашего плеера.':mode==='native'?'Откроется вторая страница YouTube; видео может загружаться повторно.':'Захват вкладки поддерживает все три вида плеера.';
};
document.querySelector('#speakers').onchange=()=>{document.querySelector('#manualVoiceRow').hidden=document.querySelector('#speakers').checked;};
document.querySelector('#playerMode').onchange=()=>{if(document.querySelector('#playerMode').value==='window'){document.querySelector('#videoMode').value='capture';document.querySelector('#videoMode').dispatchEvent(new Event('change'));}};
for(const input of document.querySelectorAll('select,input'))input.addEventListener('change',()=>{
  const options={};for(const field of document.querySelectorAll('select,input'))options[field.id]=field.type==='checkbox'?field.checked:field.type==='number'?Number(field.value):field.value;
  chrome.storage.local.set({translationOptions:options});
});
document.querySelector('#start').onclick = async () => {
  const button = document.querySelector('#start'); button.disabled = true;
  try {
    await restoreOptions;
    const build=await chrome.runtime.sendMessage({target:'worker',type:'worker-build'});
    if(build?.build!=='0.4.7' || chrome.runtime.getManifest().version!=='0.4.7')throw Error('Код расширения обновлён. Нажмите ↻ у расширения в chrome://extensions и повторите запуск.');
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const options={
      mode: document.querySelector('#mode').value, voice: document.querySelector('#voice').value,
      playerMode:document.querySelector('#playerMode').value,
      videoMode:document.querySelector('#videoMode').value,
      videoHeight:Number(document.querySelector('#videoHeight').value),videoFps:Number(document.querySelector('#videoFps').value),videoMbps:Number(document.querySelector('#videoMbps').value),
      speakers:document.querySelector('#speakers').checked,
      speakerCount:Number(document.querySelector('#speakerCount').value),qualityMinute:true,
      delay: Math.max(10, Math.min(60, Number(document.querySelector('#delay').value) || 60))};
    await chrome.storage.local.set({translationOptions:options});
    const result = await chrome.runtime.sendMessage({target: 'worker', type: 'start', tabId: tab.id,...options});
    if (result.error) throw new Error(result.error);
    window.close();
  } catch (e) { document.querySelector('#status').textContent = e.message; button.disabled = false; }
};
