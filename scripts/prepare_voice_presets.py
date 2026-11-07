"""One-time synthetic preset assets. Main Qwen runtime never loads Silero."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import soundfile as sf
from service.config import ROOT
out=ROOT/'models/voice-presets';out.mkdir(exist_ok=True)
names=('eugene','aidar','xenia','baya','kseniya')
missing=[name for name in names if not (out/f'{name}.wav').exists()]
if missing:
    import torch
    torch.set_num_threads(4)
    model=torch.package.PackageImporter(str(ROOT/'models/silero.pt')).load_pickle('tts_models','model')
    for name in missing:
        with torch.inference_mode():audio=model.apply_tts(text='Сегодня мы проверяем перевод видео на русский язык.',speaker=name,sample_rate=24000).numpy()
        sf.write(out/f'{name}.wav',audio,24000,subtype='PCM_16')
print('Static voice references ready; no original recording, Silero not required at runtime.')
