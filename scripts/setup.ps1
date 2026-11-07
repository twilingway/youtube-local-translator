$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:UV_CACHE_DIR="$PWD\.cache\uv"
$env:UV_PYTHON_INSTALL_DIR="$PWD\.runtime\python"
uv python install 3.11 --no-bin --no-registry
if ($LASTEXITCODE) { throw 'Python download failed' }
if (!(Test-Path .venv\Scripts\python.exe)) { uv venv --python 3.11 .venv }
uv pip install --python .venv\Scripts\python.exe torch==2.11.0+cu128 torchaudio==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE) { throw 'PyTorch installation failed' }
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if ($LASTEXITCODE) { throw 'Dependencies installation failed' }
node scripts\init-config.cjs
if ($LASTEXITCODE) { throw 'Config initialization failed' }
& .venv\Scripts\python.exe scripts\download_models.py
if ($LASTEXITCODE) { throw 'Model download failed' }
& .venv\Scripts\python.exe scripts\fetch_speakers.py
if ($LASTEXITCODE) { throw 'Speaker model download failed' }
& .venv\Scripts\python.exe scripts\fetch_diarization.py
if ($LASTEXITCODE) { throw 'Diarization model download failed' }
& .venv\Scripts\python.exe scripts\download_native_tts.py
if ($LASTEXITCODE) { throw 'Qwen CUDA runtime/model download failed' }
& .venv\Scripts\python.exe scripts\prepare_voice_presets.py
if ($LASTEXITCODE) { throw 'Static voice reference preparation failed' }
if (!(Test-Path .runtime\ollama\ollama.exe)) {
  New-Item -ItemType Directory -Force .runtime\ollama | Out-Null
  & .venv\Scripts\python.exe scripts\fetch_ollama.py
  if ($LASTEXITCODE) { throw 'Ollama download failed' }
}
& .venv\Scripts\python.exe scripts\bootstrap_translation.py
if ($LASTEXITCODE) { throw 'Translation model download failed' }
Write-Host 'Готово. Запустите scripts/start.ps1.'
