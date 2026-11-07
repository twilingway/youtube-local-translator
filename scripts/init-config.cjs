const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),file=path.join(root,'extension','manifest.json');
const manifest=JSON.parse(fs.readFileSync(file,'utf8'));
if(!manifest.key){
  const {publicKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048,publicKeyEncoding:{type:'spki',format:'der'},privateKeyEncoding:{type:'pkcs8',format:'der'}});
  manifest.key=publicKey.toString('base64');fs.writeFileSync(file,JSON.stringify(manifest,null,2)+'\n');
}
const digest=crypto.createHash('sha256').update(Buffer.from(manifest.key,'base64')).digest('hex').slice(0,32);
const id=[...digest].map(c=>String.fromCharCode(97+parseInt(c,16))).join('');
const configPath=path.join(root,'config.local.json');
if(!fs.existsSync(configPath))fs.writeFileSync(configPath,JSON.stringify({token:crypto.randomBytes(32).toString('base64url'),extension_id:id,translation_model:'translategemma:4b',asr_model:'whisper-quality',tts_backend:'qwen-native',diarization_backend:'sherpa'},null,2)+'\n');
const config=JSON.parse(fs.readFileSync(configPath,'utf8'));
if(config.extension_id!==id)throw Error('Extension key changed; review config.local.json');
fs.writeFileSync(path.join(root,'extension','local-config.js'),'const LOCAL_CONFIG = '+JSON.stringify({token:config.token})+';\n');
console.log('Extension ID: '+id);
