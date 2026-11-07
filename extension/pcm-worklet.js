class PCM extends AudioWorkletProcessor {
  constructor() {super();this.sum=0;this.count=0;this.phase=0;this.out=[];this.start=0;}
  process(inputs,outputs) {
    const channels=inputs[0];
    if(!channels?.length) return true;
    for(let i=0;i<channels[0].length;i++) {
      let value=0;for(const ch of channels)value+=ch[i]/channels.length;
      this.sum+=value;this.count++;this.phase+=16000;
      if(this.phase>=sampleRate) {
        if(!this.out.length)this.start=currentTime+i/sampleRate;
        this.out.push(Math.round(Math.max(-1,Math.min(1,this.sum/this.count))*32767));
        this.sum=0;this.count=0;this.phase-=sampleRate;
        if(this.out.length===1600) {const pcm=new Int16Array(this.out);this.port.postMessage({time:this.start,pcm},[pcm.buffer]);this.out=[];}
      }
    }
    return true;
  }
}
registerProcessor('pcm',PCM);
