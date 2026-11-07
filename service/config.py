import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault('HF_HOME', str(ROOT / 'models' / 'huggingface'))
os.environ.setdefault('TORCH_HOME', str(ROOT / 'models' / 'torch'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('DO_NOT_TRACK', '1')
CONFIG = ROOT / 'config.local.json'

def config():
    return json.loads(CONFIG.read_text(encoding='utf-8-sig'))
