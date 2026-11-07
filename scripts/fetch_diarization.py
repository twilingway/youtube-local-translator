"""Project-local official sherpa-onnx assets. No source video/audio is recorded."""
import hashlib,json,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
out=ROOT/'models/diarization';out.mkdir(exist_ok=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def metadata(tag):
    with opener.open('https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/'+tag,timeout=30) as r:return json.load(r)
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
sources=[]
for tag,names in [('speaker-segmentation-models',['sherpa-onnx-pyannote-segmentation-3-0.tar.bz2','0-four-speakers-zh.wav','1-two-speakers-en.wav','2-two-speakers-en.wav','3-two-speakers-en.wav']),
                  ('speaker-recongition-models',['nemo_en_titanet_small.onnx','wespeaker_en_voxceleb_resnet34.onnx'])]:
    release=metadata(tag)
    for name in names:
        asset=next(a for a in release['assets'] if a['name']==name)
        path=out/name if not name.endswith('.wav') else ROOT/'reports'/name
        expected=(asset.get('digest') or '').removeprefix('sha256:')
        if not path.exists() or path.stat().st_size!=asset['size'] or (expected and digest(path)!=expected):
            print('Downloading '+name,flush=True)
            with opener.open(asset['browser_download_url'],timeout=90) as response,path.with_suffix(path.suffix+'.part').open('wb') as f:
                while chunk:=response.read(1024*1024):f.write(chunk)
            part=path.with_suffix(path.suffix+'.part')
            if part.stat().st_size!=asset['size'] or (expected and digest(part)!=expected):raise RuntimeError('Checksum/size mismatch: '+name)
            part.replace(path)
        sources.append({'url':asset['browser_download_url'],'bytes':path.stat().st_size,'sha256':digest(path),'path':str(path)})
        if name.endswith('.tar.bz2'):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    target=(out/member.name).resolve()
                    if not target.is_relative_to(out.resolve()) or member.issym() or member.islnk():raise RuntimeError('Unsafe archive member')
                archive.extractall(out,filter='data')
(ROOT/'reports/diarization-sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
print('Diarization assets ready.',flush=True)
