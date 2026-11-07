$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:OLLAMA_HOST='127.0.0.1:11439'
$env:OLLAMA_MODELS="$PWD\models\ollama"
$config=Get-Content config.local.json | ConvertFrom-Json
& .runtime\ollama\ollama.exe pull $config.translation_model
if ($LASTEXITCODE) { throw 'Translation model download failed' }
