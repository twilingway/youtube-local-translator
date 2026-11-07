const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),file=path.join(root,'config.local.json');
const config=JSON.parse(fs.readFileSync(file,'utf8'));
config.asr_model='whisper-quality';
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Selected local ASR large-v3; takes effect on next service start.');
