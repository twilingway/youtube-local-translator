import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from service.config import ROOT, config
from huggingface_hub import snapshot_download
import urllib.request

model=config().get('asr_model','whisper-quality')
repo='Systran/faster-whisper-large-v3' if model=='whisper-quality' else 'dropbox-dash/faster-whisper-large-v3-turbo'
snapshot_download(repo, local_dir=ROOT/'models'/model,
                  allow_patterns=['*.json','*.bin','*.txt'])
target=ROOT/'models/silero.pt'
if not target.exists():
    temp=target.with_suffix('.part')
    urllib.request.urlretrieve('https://models.silero.ai/models/tts/ru/v5_6_ru.pt', temp)
    temp.replace(target)
print('Whisper and Silero ready')
