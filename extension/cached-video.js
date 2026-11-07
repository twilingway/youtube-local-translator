// Original encoded media retains YouTube's timestamps. The ASR/player API uses
// the session capture clock, mapped by the existing sourceTime/captureTime.
function createCachedVideo(element){
  let goal=null;
  function synchronize(){
    if(goal===null || element.readyState<1)return;
    const ranges=Array.from({length:element.buffered.length},(_,i)=>[element.buffered.start(i),element.buffered.end(i)]);
    // Container/audio preroll can put the first common frame a few ms after
    // capture zero. Never wait forever for that tiny, nonexistent interval.
    if(!ranges.some(([a,b])=>goal>=a&&goal<b)){
      const next=ranges.find(([a])=>a>goal && a-goal<=.25);
      if(next)goal=next[0]+.001;
    }
    if(!element.seeking && Math.abs(element.currentTime-goal)<.25 && element.readyState>=2){goal=null;return;}
    if(!element.seeking && Array.from({length:element.buffered.length},(_,i)=>[element.buffered.start(i),element.buffered.end(i)]).some(([a,b])=>goal>=a&&goal<b))element.currentTime=goal;
  }
  setInterval(synchronize,100);
  return new Proxy(element,{get(target,key){
    if(key==='raw')return element;
    if(key==='synchronize')return synchronize;
    if(key==='targetSourceTime')return goal??sourceTime(0);
    if(key==='pendingSourceTime')return goal;
    if(key==='currentTime')return Math.max(0,captureTime(goal??target.currentTime));
    if(key==='readyState')return goal!==null || target.seeking?0:target.readyState;
    if(key==='buffered'){
      const ranges=Array.from({length:target.buffered.length},(_,i)=>[captureTime(target.buffered.start(i)),captureTime(target.buffered.end(i))]).filter(([,b])=>b>0).map(([a,b])=>[Math.max(0,a),b]);
      return {length:ranges.length,start:i=>ranges[i][0],end:i=>ranges[i][1]};
    }
    const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
  },set(target,key,value){
    if(key==='currentTime'){goal=sourceTime(value);synchronize();return true;}
    return Reflect.set(target,key,value,target);
  }});
}
