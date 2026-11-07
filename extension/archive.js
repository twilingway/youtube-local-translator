// Integrity of captured bytes, not a guarantee of the source site's delivery.
class CaptureArchive {
  constructor(){this.chunks=[];this.bytes=0;this.next=0;this.failure='';}
  async add(data,seq,end){
    if(seq!==this.next || !Number.isFinite(end) || end<(this.chunks.at(-1)?.end??0)){
      this.failure='Нарушен порядок фрагментов архива';throw Error(this.failure);
    }
    const digest=await CaptureArchive.hash(data);
    const chunk=Object.freeze({data,seq,end,digest});
    this.next++;this.chunks.push(chunk);this.bytes+=data.byteLength;return chunk;
  }
  static async hash(data){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');}
  async verify(chunks=this.chunks){
    if(!chunks.length || chunks[0].seq!==0)throw Error('Начало архива удалено; нужен новый захват');
    let seq=0,end=0;
    for(const c of chunks){
      if(c.seq!==seq++ || c.end<end || await CaptureArchive.hash(c.data)!==c.digest)throw Error('Повреждён или пропущен фрагмент архива');
      end=c.end;
    }
    return true;
  }
  prune(before){this.chunks=this.chunks.filter(c=>c.end>before);this.bytes=this.chunks.reduce((n,c)=>n+c.data.byteLength,0);}
}
globalThis.CaptureArchive=CaptureArchive;
