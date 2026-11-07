$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .venv\Scripts\python.exe scripts\run.py
if ($LASTEXITCODE) { throw 'Сервис завершился с ошибкой. Смотрите вывод и reports/ollama.log.' }
