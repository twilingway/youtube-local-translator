"""Preserve the original UTF-8 manifest strings; do not pipe through PowerShell."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
data = json.loads((root / 'extension/manifest.json').read_text(encoding='utf-8'))
data['version'] = '0.3.0'
data['web_accessible_resources'][0]['resources'] = [
    'player.html', 'player.js', 'style.css', 'archive.js', 'native-video.js'
]
(root / '.next/extension/manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
